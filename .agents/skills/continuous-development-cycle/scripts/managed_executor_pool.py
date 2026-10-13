#!/usr/bin/env python3
"""CDC 2.11.0 managed executor-pool planning, dispatch and completion contract."""
from __future__ import annotations

from git_object_integrity import git_object_environment

import argparse
import copy
import hashlib
import json
import os
import math
import re
import subprocess
import sys
from pathlib import Path

from parallel_task_planner import validate_write_path, portable_path_key, overlaps

PLAN_SCHEMA = "managed-executor-pool-plan/v1"
STATE_SCHEMA = "managed-executor-pool-state/v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
STORE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ROLES = {"writer", "read_only", "review"}
TASK_STATUSES = {"planned", "queued", "running", "succeeded", "failed", "cancelled", "stale", "omitted"}
ACTIVE = {"queued", "running"}
RECOVERABLE = {"failed", "cancelled", "stale"}
AUTHORITY_FIELDS = (
    "authorizes_worker_launch",
    "authorizes_shared_branch_write",
    "authorizes_merge",
    "authorizes_release",
    "authorizes_scope_expansion",
    "authorizes_scheduler_mutation",
    "authorizes_user_approval",
)

PLAN_FIELDS = {
    "schema", "pool_id", "change_id", "parent_invocation_id", "base_sha", "integrator_id",
    "coordination_ref", "coordination_store_id",
    "max_parallel", "total_runtime_budget_seconds", "total_cost_budget_units", "tasks",
}
TASK_FIELDS = {
    "id", "role", "required", "dependencies", "executor_id", "branch", "worktree",
    "write_paths", "expected_outputs", "expected_evidence", "backend_preferences",
    "max_runtime_seconds", "max_cost_units",
}
STATE_FIELDS = {
    "plan_digest", "schema", "pool_id", "change_id", "parent_invocation_id", "base_sha", "integrator_id",
    "coordination_ref", "coordination_store_id",
    "revision", "execution_mode", "tasks", "runtime_consumed_seconds", "cost_consumed_units",
    *AUTHORITY_FIELDS,
}
TASK_STATE_FIELDS = {
    "id", "status", "attempt_ids", "active_attempt_id", "reservation_token",
    "accepted_result_ref", "integrated", "discarded", "runtime_seconds", "cost_units",
}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def _refs(value, name, allow_empty=False):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{name} must be a list of nonempty strings")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} contains duplicates")
    return value


def _positive_number(value, name):
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def _nonnegative_number(value, name):
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value


def _coordination_ref(value, name="coordination_ref"):
    if not isinstance(value, str) or not value.startswith("refs/heads/"):
        raise ValueError(f"{name} must be an exact refs/heads/ ref")
    suffix = value.removeprefix("refs/heads/")
    if not suffix or value != "refs/heads/" + suffix:
        raise ValueError(f"{name} must be canonical")
    validate_write_path(suffix)
    return value


def _coordination_store_id(value):
    if not isinstance(value, str) or not STORE_ID.fullmatch(value):
        raise ValueError("coordination_store_id must be sha256:<hex>")
    return value


def _portable_paths(value, name, required):
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    if required and not value:
        raise ValueError(f"{name} must not be empty")
    keys = []
    for path in value:
        validate_write_path(path)
        keys.append(portable_path_key(path))
    if len(keys) != len(set(keys)):
        raise ValueError(f"{name} contains portable aliases")
    return value


def _canonical_coordination_ref(value):
    if not isinstance(value, str) or not value.startswith("refs/heads/"):
        raise ValueError("coordination_ref must be an exact refs/heads/ ref")
    suffix = value.removeprefix("refs/heads/")
    validate_write_path(suffix)
    if value != "refs/heads/" + suffix:
        raise ValueError("coordination_ref must be canonical")
    return value


def _store_id(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError("coordination_store_id must be sha256:<hex>")
    return value


def _acyclic(tasks):
    graph = {task["id"]: task["dependencies"] for task in tasks}
    visiting, done = set(), set()

    def visit(node):
        if node in done:
            return
        if node in visiting:
            raise ValueError("cyclic task dependency")
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        done.add(node)

    for node in graph:
        visit(node)


def _reject_required_optional_dependencies(tasks):
    by_id = {task["id"]: task for task in tasks}
    for task in tasks:
        if not task["required"]:
            continue
        stack = list(task["dependencies"])
        seen = set()
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            dependency = by_id[dep]
            if not dependency["required"]:
                raise ValueError(
                    f"required task cannot depend on optional prerequisite: {task['id']} -> {dep}"
                )
            stack.extend(dependency["dependencies"])


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("managed executor pool plan fields/schema mismatch")
    for name in ("pool_id", "change_id", "parent_invocation_id", "integrator_id"):
        _text(plan[name], name)
    _canonical_coordination_ref(plan["coordination_ref"])
    _store_id(plan["coordination_store_id"])
    if not isinstance(plan["base_sha"], str) or not SHA.fullmatch(plan["base_sha"]):
        raise ValueError("base_sha must be a full lowercase SHA")
    if type(plan["max_parallel"]) is not int or plan["max_parallel"] < 1:
        raise ValueError("max_parallel must be a positive integer")
    _positive_number(plan["total_runtime_budget_seconds"], "total_runtime_budget_seconds")
    _positive_number(plan["total_cost_budget_units"], "total_cost_budget_units")
    if not isinstance(plan["tasks"], list) or not plan["tasks"]:
        raise ValueError("tasks must not be empty")
    ids = []
    for index, task in enumerate(plan["tasks"]):
        if not isinstance(task, dict) or set(task) != TASK_FIELDS:
            raise ValueError("managed executor task fields mismatch")
        _text(task["id"], f"tasks[{index}].id")
        if task["role"] not in ROLES:
            raise ValueError("unsupported managed executor role")
        if type(task["required"]) is not bool:
            raise ValueError("task required must be boolean")
        _refs(task["dependencies"], f"tasks[{index}].dependencies", allow_empty=True)
        _text(task["executor_id"], f"tasks[{index}].executor_id")
        _refs(task["expected_outputs"], f"tasks[{index}].expected_outputs")
        _refs(task["expected_evidence"], f"tasks[{index}].expected_evidence")
        _refs(task["backend_preferences"], f"tasks[{index}].backend_preferences")
        _positive_number(task["max_runtime_seconds"], f"tasks[{index}].max_runtime_seconds")
        _positive_number(task["max_cost_units"], f"tasks[{index}].max_cost_units")
        if task["max_runtime_seconds"] > plan["total_runtime_budget_seconds"]:
            raise ValueError("task runtime budget exceeds pool budget")
        if task["max_cost_units"] > plan["total_cost_budget_units"]:
            raise ValueError("task cost budget exceeds pool budget")
        _portable_paths(task["write_paths"], f"tasks[{index}].write_paths", task["role"] == "writer")
        if task["role"] == "writer":
            _text(task["branch"], f"tasks[{index}].branch")
            _text(task["worktree"], f"tasks[{index}].worktree")
        elif task["branch"] is not None or task["worktree"] is not None or task["write_paths"]:
            raise ValueError("non-writer task cannot declare writer isolation or write_paths")
        ids.append(task["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate managed executor task id")
    writer_branches = []
    writer_worktrees = []
    for task in plan["tasks"]:
        if task["role"] != "writer":
            continue
        branch_name = task["branch"].removeprefix("refs/heads/")
        validate_write_path(branch_name)
        validate_write_path(task["worktree"])
        writer_branches.append(portable_path_key(branch_name))
        writer_worktrees.append(portable_path_key(task["worktree"]))
    if len(writer_branches) != len(set(writer_branches)):
        raise ValueError("writer branches must be portable-unique")
    if len(writer_worktrees) != len(set(writer_worktrees)):
        raise ValueError("writer worktrees must be portable-unique")
    coordination_key = portable_path_key(plan["coordination_ref"].removeprefix("refs/heads/"))
    if coordination_key in set(writer_branches):
        raise ValueError("coordination_ref must be portable-isolated from writer branches")
    known = set(ids)
    for task in plan["tasks"]:
        if task["id"] in task["dependencies"] or not set(task["dependencies"]) <= known:
            raise ValueError("invalid managed executor dependency")
    _acyclic(plan["tasks"])
    task_map = {task["id"]: task for task in plan["tasks"]}
    def visit_required_dependencies(task_id, seen=None):
        seen = set() if seen is None else seen
        for dep in task_map[task_id]["dependencies"]:
            if dep in seen:
                continue
            seen.add(dep)
            if not task_map[dep]["required"]:
                raise ValueError("required task cannot depend on optional task")
            visit_required_dependencies(dep, seen)
    for task in plan["tasks"]:
        if task["required"]:
            visit_required_dependencies(task["id"])
    if plan["max_parallel"] > len(plan["tasks"]):
        raise ValueError("max_parallel exceeds task count")
    return plan


def initial_state(plan, *, parallel_capable):
    validate_plan(plan)
    if type(parallel_capable) is not bool:
        raise ValueError("parallel_capable must be boolean")
    state = {
        "schema": STATE_SCHEMA,
        "plan_digest": canonical_state_ref(plan),
        "pool_id": plan["pool_id"],
        "change_id": plan["change_id"],
        "parent_invocation_id": plan["parent_invocation_id"],
        "base_sha": plan["base_sha"],
        "integrator_id": plan["integrator_id"],
        "coordination_ref": plan["coordination_ref"],
        "coordination_store_id": plan["coordination_store_id"],
        "revision": 0,
        "execution_mode": "parallel" if parallel_capable else "sequential_fallback",
        "tasks": [
            {
                "id": task["id"], "status": "planned", "attempt_ids": [],
                "active_attempt_id": None, "reservation_token": None,
                "accepted_result_ref": None, "integrated": False, "discarded": False,
                "runtime_seconds": 0, "cost_units": 0,
            }
            for task in plan["tasks"]
        ],
        "runtime_consumed_seconds": 0,
        "cost_consumed_units": 0,
        **{name: False for name in AUTHORITY_FIELDS},
    }
    return validate_state(plan, state)


def _task_map(plan):
    return {task["id"]: task for task in plan["tasks"]}


def _state_map(state):
    return {task["id"]: task for task in state["tasks"]}


def validate_state(plan, state):
    validate_plan(plan)
    if not isinstance(state, dict) or set(state) != STATE_FIELDS or state.get("schema") != STATE_SCHEMA:
        raise ValueError("managed executor pool state fields/schema mismatch")
    for field in ("pool_id", "change_id", "parent_invocation_id", "base_sha", "integrator_id",
                  "coordination_ref", "coordination_store_id"):
        if state[field] != plan[field]:
            raise ValueError(f"pool state {field} mismatch")
    if state["plan_digest"] != canonical_state_ref(plan):
        raise ValueError("pool plan digest binding mismatch")
    if type(state["revision"]) is not int or state["revision"] < 0:
        raise ValueError("pool state revision must be a nonnegative integer")
    if state["execution_mode"] not in {"parallel", "sequential_fallback"}:
        raise ValueError("invalid execution_mode")
    if not isinstance(state["tasks"], list) or len(state["tasks"]) != len(plan["tasks"]):
        raise ValueError("pool state task set mismatch")
    pmap = _task_map(plan)
    seen = []
    runtime_sum = 0
    cost_sum = 0
    for task in state["tasks"]:
        if not isinstance(task, dict) or set(task) != TASK_STATE_FIELDS:
            raise ValueError("managed executor task state fields mismatch")
        task_id = task["id"]
        if task_id not in pmap:
            raise ValueError("pool state contains unknown task")
        seen.append(task_id)
        if task["status"] not in TASK_STATUSES:
            raise ValueError("invalid managed executor task status")
        if task["status"] == "omitted" and pmap[task_id]["required"]:
            raise ValueError("required task cannot be omitted")
        _refs(task["attempt_ids"], f"{task_id}.attempt_ids", allow_empty=True)
        if task["active_attempt_id"] is not None:
            _text(task["active_attempt_id"], f"{task_id}.active_attempt_id")
            if task["active_attempt_id"] not in task["attempt_ids"]:
                raise ValueError("active attempt must be in attempt history")
        if task["reservation_token"] is not None:
            _text(task["reservation_token"], f"{task_id}.reservation_token")
        if task["status"] in ACTIVE and (task["active_attempt_id"] is None or task["reservation_token"] is None):
            raise ValueError("active task requires active_attempt_id and reservation_token")
        if task["status"] not in ACTIVE and (task["active_attempt_id"] is not None or task["reservation_token"] is not None):
            raise ValueError("non-active task cannot retain active attempt/reservation")
        if task["accepted_result_ref"] is not None:
            _text(task["accepted_result_ref"], f"{task_id}.accepted_result_ref")
        if type(task["integrated"]) is not bool or type(task["discarded"]) is not bool:
            raise ValueError("integrated/discarded must be boolean")
        if task["integrated"] and task["discarded"]:
            raise ValueError("result cannot be both integrated and discarded")
        if task["integrated"] and (task["status"] != "succeeded" or task["accepted_result_ref"] is None):
            raise ValueError("integrated task requires accepted succeeded result")
        if task["discarded"] and (task["status"] != "succeeded" or task["accepted_result_ref"] is None
                                  or pmap[task_id]["required"]):
            raise ValueError("only optional accepted succeeded result may be discarded")
        if task["status"] == "succeeded" and task["accepted_result_ref"] is None:
            raise ValueError("succeeded task requires accepted result")
        if task["status"] != "succeeded" and task["accepted_result_ref"] is not None:
            raise ValueError("only succeeded task may retain accepted result")
        if task["status"] != "succeeded" and (task["integrated"] or task["discarded"]):
            raise ValueError("only succeeded task may retain result disposition")
        runtime_sum += _nonnegative_number(task["runtime_seconds"], f"{task_id}.runtime_seconds")
        cost_sum += _nonnegative_number(task["cost_units"], f"{task_id}.cost_units")
        if task["runtime_seconds"] > pmap[task_id]["max_runtime_seconds"]:
            raise ValueError("task runtime budget exceeded")
        if task["cost_units"] > pmap[task_id]["max_cost_units"]:
            raise ValueError("task cost budget exceeded")
    if seen != [task["id"] for task in plan["tasks"]]:
        raise ValueError("pool state task order/identity mismatch")
    _nonnegative_number(state["runtime_consumed_seconds"], "runtime_consumed_seconds")
    _nonnegative_number(state["cost_consumed_units"], "cost_consumed_units")
    if not math.isclose(state["runtime_consumed_seconds"], runtime_sum, rel_tol=0, abs_tol=1e-9):
        raise ValueError("runtime consumption does not match task state")
    if not math.isclose(state["cost_consumed_units"], cost_sum, rel_tol=0, abs_tol=1e-9):
        raise ValueError("cost consumption does not match task state")
    if runtime_sum > plan["total_runtime_budget_seconds"]:
        raise ValueError("pool runtime budget exceeded")
    if cost_sum > plan["total_cost_budget_units"]:
        raise ValueError("pool cost budget exceeded")
    for name in AUTHORITY_FIELDS:
        if type(state[name]) is not bool or state[name]:
            raise ValueError(f"{name} must remain false")
    return state


def ready_task_ids(plan, state):
    validate_state(plan, state)
    smap = _state_map(state)
    ready = []
    for task in plan["tasks"]:
        current = smap[task["id"]]
        if current["status"] != "planned":
            continue
        if all(smap[dep]["status"] == "succeeded" and smap[dep]["integrated"] for dep in task["dependencies"]):
            ready.append(task["id"])
    return ready


def _active_writer_paths(plan, state):
    pmap, smap = _task_map(plan), _state_map(state)
    paths = []
    for task_id, current in smap.items():
        if current["status"] in ACTIVE and pmap[task_id]["role"] == "writer":
            paths.extend(pmap[task_id]["write_paths"])
    return paths


def canonical_state_ref(state):
    payload = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _expect_revision(state, expected_revision):
    if type(expected_revision) is not int or expected_revision != state["revision"]:
        raise ValueError("stale pool state revision")


def _advance_revision(state):
    state["revision"] += 1
    return state


def _remaining_task_budget(task, current):
    remaining_runtime = task["max_runtime_seconds"] - current["runtime_seconds"]
    remaining_cost = task["max_cost_units"] - current["cost_units"]
    if remaining_runtime < 0 or remaining_cost < 0:
        raise ValueError("task remaining budget cannot be negative")
    return remaining_runtime, remaining_cost


def dispatch(plan, state):
    validate_state(plan, state)
    smap = _state_map(state)
    pmap = _task_map(plan)
    active_ids = [task_id for task_id, current in smap.items() if current["status"] in ACTIVE]
    active_count = len(active_ids)
    cap = 1 if state["execution_mode"] == "sequential_fallback" else plan["max_parallel"]
    slots = max(0, cap - active_count)
    active_remaining = [_remaining_task_budget(pmap[task_id], smap[task_id]) for task_id in active_ids]
    reserved_runtime = sum(item[0] for item in active_remaining)
    reserved_cost = sum(item[1] for item in active_remaining)
    runtime_left = plan["total_runtime_budget_seconds"] - state["runtime_consumed_seconds"] - reserved_runtime
    cost_left = plan["total_cost_budget_units"] - state["cost_consumed_units"] - reserved_cost
    chosen = []
    chosen_remaining = {}
    writer_paths = _active_writer_paths(plan, state)
    for task_id in ready_task_ids(plan, state):
        if len(chosen) >= slots:
            break
        task = pmap[task_id]
        remaining_runtime, remaining_cost = _remaining_task_budget(task, smap[task_id])
        if remaining_runtime <= 0 or remaining_cost <= 0:
            continue
        if remaining_runtime > runtime_left or remaining_cost > cost_left:
            continue
        if task["role"] == "writer":
            if any(overlaps(path, claimed) for path in task["write_paths"] for claimed in writer_paths):
                continue
            writer_paths.extend(task["write_paths"])
        chosen.append(task_id)
        chosen_remaining[task_id] = (remaining_runtime, remaining_cost)
        runtime_left -= remaining_runtime
        cost_left -= remaining_cost
    assignments = [
        {
            "task_id": task_id,
            "executor_id": pmap[task_id]["executor_id"],
            "role": pmap[task_id]["role"],
            "base_sha": plan["base_sha"],
            "branch": pmap[task_id]["branch"],
            "worktree": pmap[task_id]["worktree"],
            "write_paths": list(pmap[task_id]["write_paths"]),
            "backend_preferences": list(pmap[task_id]["backend_preferences"]),
        }
        for task_id in chosen
    ]
    return {
        "schema": "managed-executor-dispatch/v1",
        "pool_id": plan["pool_id"],
        "parent_invocation_id": plan["parent_invocation_id"],
        "integrator_id": plan["integrator_id"],
        "execution_mode": state["execution_mode"],
        "parallel_capable": state["execution_mode"] == "parallel",
        "max_parallel": cap,
        "task_ids": chosen,
        "assignments": assignments,
        "reserved_runtime_seconds": sum(chosen_remaining[task_id][0] for task_id in chosen),
        "reserved_cost_units": sum(chosen_remaining[task_id][1] for task_id in chosen),
        "fallback_serialized": state["execution_mode"] == "sequential_fallback",
        **{name: False for name in AUTHORITY_FIELDS},
    }


def queue_task(plan, state, task_id, attempt_id, *, expected_revision, reservation_token):
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    _text(attempt_id, "attempt_id")
    _text(reservation_token, "reservation_token")
    if task_id not in dispatch(plan, state)["task_ids"]:
        raise ValueError("task is not eligible for the current dispatch batch")
    result = copy.deepcopy(state)
    current = _state_map(result)[task_id]
    if attempt_id in current["attempt_ids"]:
        raise ValueError("duplicate attempt_id")
    current["attempt_ids"].append(attempt_id)
    current["active_attempt_id"] = attempt_id
    current["reservation_token"] = reservation_token
    current["status"] = "queued"
    return validate_state(plan, _advance_revision(result))


def mark_running(plan, state, task_id, attempt_id, *, expected_revision, reservation_token):
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    result = copy.deepcopy(state)
    current = _state_map(result).get(task_id)
    if (current is None or current["status"] != "queued" or current["active_attempt_id"] != attempt_id
            or current["reservation_token"] != reservation_token):
        raise ValueError("running transition requires matching queued reservation")
    if min(_remaining_task_budget(_task_map(plan)[task_id], current)) <= 0:
        raise ValueError("task budget exhausted before launch")
    current["status"] = "running"
    return validate_state(plan, _advance_revision(result))


def _result_paths_within_claim(task, changed_paths):
    if task["role"] != "writer":
        return not changed_paths
    for changed in changed_paths:
        validate_write_path(changed)
        key = portable_path_key(changed)
        if not any(key == portable_path_key(claim) or key.startswith(portable_path_key(claim) + "/") for claim in task["write_paths"]):
            return False
    return bool(changed_paths)


def _git_changed_paths(base_sha, result_commit, git_worktree):
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(git_worktree), "diff", "--name-only", "--no-renames", "-z",
             base_sha, result_commit],
            env=git_object_environment(), stderr=subprocess.PIPE, timeout=15,
        )
        text = raw.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot derive worker changed paths: {exc}") from exc
    paths = [path for path in text.split("\0") if path]
    _portable_paths(paths, "git changed paths", required=True)
    return paths


def _git_touched_paths(base_sha, result_commit, git_worktree):
    try:
        commits = subprocess.check_output(
            ["git", "-C", str(git_worktree), "rev-list", "--reverse", "--topo-order",
             f"{base_sha}..{result_commit}"],
            env=git_object_environment(), text=True, stderr=subprocess.PIPE, timeout=15,
        ).splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot inspect worker commit history: {exc}") from exc
    if not commits or commits[-1] != result_commit:
        raise ValueError("worker result history is empty or incomplete")
    previous = base_sha
    touched = []
    seen_keys = set()
    for commit in commits:
        try:
            parent_row = subprocess.check_output(
                ["git", "-C", str(git_worktree), "rev-list", "--parents", "-n", "1", commit],
                env=git_object_environment(), text=True, stderr=subprocess.PIPE, timeout=15,
            ).strip().split()
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(f"cannot inspect worker commit parents: {exc}") from exc
        if len(parent_row) != 2 or parent_row[0] != commit or parent_row[1] != previous:
            raise ValueError("worker result history must be one exact linear chain from base")
        try:
            raw = subprocess.check_output(
                ["git", "-C", str(git_worktree), "diff-tree", "--no-commit-id",
                 "--name-only", "--no-renames", "-r", "-z", previous, commit],
                env=git_object_environment(), stderr=subprocess.PIPE, timeout=15,
            )
            paths = [p for p in raw.decode("utf-8").split("\0") if p]
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot derive touched worker paths: {exc}") from exc
        for path in paths:
            validate_write_path(path)
            key = portable_path_key(path)
            if key not in seen_keys:
                seen_keys.add(key)
                touched.append(path)
        previous = commit
    if previous != result_commit:
        raise ValueError("worker result history does not end at result_commit")
    if not touched:
        raise ValueError("writer result history must touch at least one path")
    return touched


def _verify_writer_result_git(task, base_sha, result_commit, git_worktree):
    if not isinstance(result_commit, str) or not SHA.fullmatch(result_commit):
        raise ValueError("writer result_commit must be a full lowercase SHA")
    if not isinstance(git_worktree, (str, Path)) or not Path(git_worktree).is_dir():
        raise ValueError("writer result requires a live git_worktree")
    branch = task["branch"]
    branch_ref = branch if branch.startswith("refs/heads/") else "refs/heads/" + branch.removeprefix("refs/heads/")
    try:
        for sha in (base_sha, result_commit):
            kind = subprocess.check_output(
                ["git", "-C", str(git_worktree), "cat-file", "-t", sha],
                env=git_object_environment(), text=True, stderr=subprocess.PIPE, timeout=15,
            ).strip()
            if kind != "commit":
                raise ValueError("worker result ancestry endpoint is not a commit")
        ancestry = subprocess.run(
            ["git", "-C", str(git_worktree), "merge-base", "--is-ancestor", base_sha, result_commit],
            env=git_object_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15,
        )
        if ancestry.returncode != 0:
            raise ValueError("worker result commit does not descend from contracted base")
        live_branch = subprocess.check_output(
            ["git", "-C", str(git_worktree), "rev-parse", "--verify", branch_ref],
            env=git_object_environment(), text=True, stderr=subprocess.PIPE, timeout=15,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot verify worker result git ancestry: {exc}") from exc
    if live_branch != result_commit:
        raise ValueError("worker result commit is not exact assigned branch head")
    final_paths = _git_changed_paths(base_sha, result_commit, git_worktree)
    touched_paths = _git_touched_paths(base_sha, result_commit, git_worktree)
    return final_paths, touched_paths

def accept_result(plan, state, *, task_id, attempt_id, result_ref, base_sha,
                  executor_id, parent_invocation_id, integrator_id, branch, worktree,
                  reservation_token, result_commit, changed_paths, output_refs, evidence_refs,
                  runtime_seconds, cost_units, git_worktree=None, expected_revision):
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    _text(result_ref, "result_ref")
    _text(reservation_token, "reservation_token")
    if base_sha != plan["base_sha"]:
        raise ValueError("worker result base_sha mismatch")
    if parent_invocation_id != plan["parent_invocation_id"]:
        raise ValueError("worker result parent invocation mismatch")
    if integrator_id != plan["integrator_id"]:
        raise ValueError("worker result integrator mismatch")
    pmap, smap = _task_map(plan), _state_map(state)
    if task_id not in pmap:
        raise ValueError("unknown result task")
    current = smap[task_id]
    if (current["status"] != "running" or current["active_attempt_id"] != attempt_id
            or current["reservation_token"] != reservation_token):
        raise ValueError("result requires exact durable running reservation")
    task = pmap[task_id]
    if executor_id != task["executor_id"] or branch != task["branch"] or worktree != task["worktree"]:
        raise ValueError("worker result assignment identity mismatch")
    _portable_paths(changed_paths, "changed_paths", task["role"] == "writer")
    if not _result_paths_within_claim(task, changed_paths):
        raise ValueError("worker result changed paths escape declared write set")
    if task["role"] == "writer":
        observed_changed_paths, touched_paths = _verify_writer_result_git(
            task, base_sha, result_commit, git_worktree)
        if {portable_path_key(x) for x in observed_changed_paths} != {portable_path_key(x) for x in changed_paths}:
            raise ValueError("reported changed paths do not match exact Git diff")
        if {portable_path_key(x) for x in touched_paths} != {portable_path_key(x) for x in changed_paths}:
            raise ValueError("reported changed paths do not match history touched paths")
        if not _result_paths_within_claim(task, observed_changed_paths):
            raise ValueError("Git diff changed paths escape declared write set")
        if not _result_paths_within_claim(task, touched_paths):
            raise ValueError("worker history touched paths escape declared write set")
    elif result_commit is not None:
        raise ValueError("non-writer result cannot claim result_commit")
    _refs(output_refs, "output_refs")
    _refs(evidence_refs, "evidence_refs")
    if not set(task["expected_outputs"]) <= set(output_refs):
        raise ValueError("worker result missing expected outputs")
    if not set(task["expected_evidence"]) <= set(evidence_refs):
        raise ValueError("worker result missing expected evidence")
    runtime = _nonnegative_number(runtime_seconds, "runtime_seconds")
    cost = _nonnegative_number(cost_units, "cost_units")
    if (current["runtime_seconds"] + runtime > task["max_runtime_seconds"]
            or current["cost_units"] + cost > task["max_cost_units"]):
        raise ValueError("worker result exceeds task budget")
    if state["runtime_consumed_seconds"] + runtime > plan["total_runtime_budget_seconds"]:
        raise ValueError("worker result exceeds pool runtime budget")
    if state["cost_consumed_units"] + cost > plan["total_cost_budget_units"]:
        raise ValueError("worker result exceeds pool cost budget")
    result = copy.deepcopy(state)
    current = _state_map(result)[task_id]
    current.update(status="succeeded", active_attempt_id=None, reservation_token=None,
                   accepted_result_ref=result_ref, integrated=False, discarded=False,
                   runtime_seconds=current["runtime_seconds"] + runtime,
                   cost_units=current["cost_units"] + cost)
    result["runtime_consumed_seconds"] += runtime
    result["cost_consumed_units"] += cost
    return validate_state(plan, _advance_revision(result))


def fail_attempt(plan, state, task_id, attempt_id, *, terminal_status, reservation_token,
                 expected_revision, runtime_seconds=0, cost_units=0):
    if terminal_status not in RECOVERABLE:
        raise ValueError("failure transition requires failed/cancelled/stale")
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    _text(reservation_token, "reservation_token")
    current = _state_map(state).get(task_id)
    if (current is None or current["status"] not in ACTIVE or current["active_attempt_id"] != attempt_id
            or current["reservation_token"] != reservation_token):
        raise ValueError("failure does not match active task reservation")
    runtime = _nonnegative_number(runtime_seconds, "runtime_seconds")
    cost = _nonnegative_number(cost_units, "cost_units")
    task = _task_map(plan)[task_id]
    if current["runtime_seconds"] + runtime > task["max_runtime_seconds"] or current["cost_units"] + cost > task["max_cost_units"]:
        raise ValueError("failed attempt exceeds task budget")
    result = copy.deepcopy(state)
    current = _state_map(result)[task_id]
    current.update(status=terminal_status, active_attempt_id=None, reservation_token=None,
                   runtime_seconds=current["runtime_seconds"] + runtime,
                   cost_units=current["cost_units"] + cost)
    result["runtime_consumed_seconds"] += runtime
    result["cost_consumed_units"] += cost
    return validate_state(plan, _advance_revision(result))


def retry_task(plan, state, task_id, *, expected_revision):
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    result = copy.deepcopy(state)
    current = _state_map(result).get(task_id)
    if current is None or current["status"] not in RECOVERABLE:
        raise ValueError("retry requires failed/cancelled/stale task")
    if min(_remaining_task_budget(_task_map(plan)[task_id], current)) <= 0:
        raise ValueError("task budget exhausted; explicit authorized replanning required")
    current["status"] = "planned"
    return validate_state(plan, _advance_revision(result))


def mark_integrated(plan, state, task_id, result_ref, *, expected_revision):
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    result = copy.deepcopy(state)
    current = _state_map(result).get(task_id)
    if (current is None or current["status"] != "succeeded" or current["accepted_result_ref"] != result_ref
            or current["discarded"]):
        raise ValueError("integration requires matching non-discarded accepted succeeded result")
    current["integrated"] = True
    return validate_state(plan, _advance_revision(result))


def omit_optional_task(plan, state, task_id, *, expected_revision):
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    result = copy.deepcopy(state)
    current = _state_map(result).get(task_id)
    task = _task_map(plan).get(task_id)
    if task is None or task["required"] or current is None:
        raise ValueError("omit requires an optional task")
    if current["status"] not in {"planned", *RECOVERABLE}:
        raise ValueError("optional omission requires planned or recoverable task")
    if (current["active_attempt_id"] is not None or current["reservation_token"] is not None
            or current["accepted_result_ref"] is not None or current["integrated"] or current["discarded"]):
        raise ValueError("optional omission requires no active or accepted result")
    current["status"] = "omitted"
    return validate_state(plan, _advance_revision(result))


def discard_optional_result(plan, state, task_id, result_ref, *, expected_revision):
    validate_state(plan, state)
    _expect_revision(state, expected_revision)
    result = copy.deepcopy(state)
    current = _state_map(result).get(task_id)
    task = _task_map(plan).get(task_id)
    if (task is None or task["required"] or current is None or current["status"] != "succeeded"
            or current["accepted_result_ref"] != result_ref or current["integrated"]):
        raise ValueError("discard requires matching unintegrated optional succeeded result")
    current["discarded"] = True
    return validate_state(plan, _advance_revision(result))


def assess(plan, state):
    validate_state(plan, state)
    pmap, smap = _task_map(plan), _state_map(state)
    blockers = []
    runnable = ready_task_ids(plan, state)
    for task in plan["tasks"]:
        current = smap[task["id"]]
        if current["status"] in ACTIVE:
            blockers.append(f"{task['id']}:active")
        if current["status"] == "succeeded" and not current["integrated"] and not current["discarded"]:
            blockers.append(f"{task['id']}:unintegrated_success")
        if task["required"]:
            if current["status"] == "planned":
                blockers.append(f"{task['id']}:runnable" if task["id"] in runnable else f"{task['id']}:dependency_wait")
            elif current["status"] in RECOVERABLE:
                blockers.append(f"{task['id']}:recovery_required")
        else:
            if current["status"] == "planned":
                blockers.append(f"{task['id']}:optional_runnable" if task["id"] in runnable else f"{task['id']}:optional_dependency_wait")
            elif current["status"] in RECOVERABLE:
                blockers.append(f"{task['id']}:optional_disposition_required")
            elif current["status"] in ACTIVE:
                blockers.append(f"{task['id']}:optional_active")
    complete = not blockers and all(
        (smap[task["id"]]["status"] == "succeeded" and smap[task["id"]]["integrated"])
        if task["required"] else (
            smap[task["id"]]["status"] == "omitted"
            or (smap[task["id"]]["status"] == "succeeded"
                and (smap[task["id"]]["integrated"] or smap[task["id"]]["discarded"]))
        )
        for task in plan["tasks"]
    )
    return {
        "schema": "managed-executor-pool-assessment/v1",
        "pool_id": plan["pool_id"],
        "complete": complete,
        "terminal_allowed": complete,
        "runnable_task_ids": runnable,
        "blockers": blockers,
        "next_action": None if complete else ("dispatch_ready_tasks" if runnable else "observe_or_recover_pool"),
        **{name: False for name in AUTHORITY_FIELDS},
    }


def queue_task_cas(store, expected_store_revision, plan, task_id, attempt_id, *, reservation_token):
    """Atomically reserve one task through a durable compare-and-swap state store.

    The store contract is read() -> (revision, state) and
    compare_and_swap(expected_revision, new_state) -> new_revision.
    A successful queue CAS reserves the attempt but does NOT authorize launch.
    Launch authority is granted only by launch_task_cas() after a second durable CAS.
    """
    store_revision, state = store.read()
    if store_revision != expected_store_revision or state is None:
        raise ValueError("stale expected pool-store revision")
    validate_state(plan, state)
    next_state = queue_task(
        plan, state, task_id, attempt_id,
        expected_revision=state["revision"], reservation_token=reservation_token,
    )
    new_store_revision = store.compare_and_swap(expected_store_revision, next_state)
    return {
        "schema": "managed-executor-queue-reservation/v1",
        "store_revision": new_store_revision,
        "state_revision": next_state["revision"],
        "state_ref": canonical_state_ref(next_state),
        "task_id": task_id,
        "attempt_id": attempt_id,
        "reservation_token": reservation_token,
        "launch_allowed": False,
        **{name: False for name in AUTHORITY_FIELDS},
    }


def claim_launch_cas(store, expected_store_revision, plan, task_id, attempt_id, *,
                     reservation_token):
    """Consume a queued reservation with one durable queued->running CAS.

    Only this successful transition grants physical worker-launch authority.
    """
    store_revision, state = store.read()
    if store_revision != expected_store_revision or state is None:
        raise ValueError("stale expected pool-store revision")
    validate_state(plan, state)
    current = _state_map(state).get(task_id)
    if (current is None or current["status"] != "queued"
            or current["active_attempt_id"] != attempt_id
            or current["reservation_token"] != reservation_token):
        raise ValueError("launch claim does not match live queued reservation")
    next_state = mark_running(
        plan, state, task_id, attempt_id,
        expected_revision=state["revision"], reservation_token=reservation_token,
    )
    new_store_revision = store.compare_and_swap(expected_store_revision, next_state)
    return {
        "schema": "managed-executor-launch-claim/v1",
        "store_revision": new_store_revision,
        "state_revision": next_state["revision"],
        "state_ref": canonical_state_ref(next_state),
        "task_id": task_id,
        "attempt_id": attempt_id,
        "reservation_token": reservation_token,
        "launch_allowed": True,
        **{name: False for name in AUTHORITY_FIELDS},
    }


def launch_task_cas(store, expected_store_revision, plan, task_id, attempt_id, *, reservation_token):
    """Compatibility alias for the one-shot durable launch claim."""
    return claim_launch_cas(
        store, expected_store_revision, plan, task_id, attempt_id,
        reservation_token=reservation_token,
    )

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("--state")
    parser.add_argument("--parallel-capable", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = validate_plan(json.loads(Path(args.plan).read_text()))
        state = initial_state(plan, parallel_capable=args.parallel_capable) if args.state is None else validate_state(
            plan, json.loads(Path(args.state).read_text())
        )
        output = {"dispatch": dispatch(plan, state), "assessment": assess(plan, state)}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
