#!/usr/bin/env python3
"""Pure deterministic recovery recommendations; never executes or grants authority."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
from pathlib import Path

ACTIONS = {"reconcile_live_state", "inspect_exact_invocation", "verify_pending_writes", "reconcile_external", "preserve_external_guard", "migrate_released_lease", "reconcile_scheduler", "repair_scheduler_if_authorized", "verify_delivery", "reconcile_chat_binding", "restore_chat_if_authorized", "refresh_capability_registry", "route_backend", "wait_retry_after", "record_blocker", "resume_next_action", "reload_policy", "validate_policy", "reconcile_checkpoint", "diagnose_progress", "execute_or_block", "escalate_owner"}
OUTCOMES = {"continue", "waiting_external", "blocked", "reconcile"}
MODES = {"native_runtime", "official_ui", "official_cli"}
NAMESPACES = {"native_runtime": "managed_cloud_runtime", "official_ui": "codex_cloud_ui", "official_cli": "codex_cloud_cli"}
BASE_FIELDS = {"id", "diagnosis_code", "priority", "requires_all", "forbids", "actions", "outcome"}
SCOPE_FIELDS = {"repository", "environment_id", "mode", "toolchain_fingerprint", "policy_digest"}
BINDING_FIELDS = {"schema", "repository", "environment_namespace", "environment_id", "access_mode", "toolchain_fingerprint", "policy_digest", "input_digests"}
SUBJECT_FIELDS = (BINDING_FIELDS - {"schema", "input_digests"}) | {"failure_signature"}
EVENT_FIELDS = {"event_id", "at_utc", "subject", "action_fingerprint", "attempt_id", "operation_key", "state", "evidence_ref", "evidence_digest", "new_signal_ref", "completed_correction_ref", "outcome"}
SELECTION_FIELDS = {"action", "reason", "recipe_id", "steps", "outcome", "authorizes_takeover", "authorizes_product_write", "authorizes_external_start", "authorizes_scheduler_mutation", "recipe", "selected_signal"}
AUTHORITIES = {"takeover": False, "product_write": False, "external_start": False, "scheduler_mutation": False}
# These inputs cannot make a diagnostic effective. Candidate identity is relevant
# only to a handler explicitly reading it; none of this module's handlers does.
INCIDENTAL_INPUTS = {"chat", "chat_id", "task", "task_id", "wake", "wake_id", "time", "timestamp", "at_utc", "now_utc", "candidate", "candidate_sha"}

def _text(v, n):
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{n} must be nonempty text")

def _tokens(v, n):
    if not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v):
        raise ValueError(f"{n} invalid")
    if len(set(v)) != len(v):
        raise ValueError(f"{n} contains duplicates")
    return v

def _fields(v, fields, name):
    if not isinstance(v, dict) or set(v) != set(fields):
        raise ValueError(f"{name} fields mismatch")

def _digest(v, n):
    if not isinstance(v, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", v) is None:
        raise ValueError(f"{n} invalid digest")

def _utc(v):
    if not isinstance(v, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", v) is None:
        raise ValueError("UTC timestamp must use Z")
    try:
        return datetime.fromisoformat(v[:-1] + "+00:00")
    except ValueError as e:
        raise ValueError("invalid UTC timestamp") from e

def _hash(v):
    return "sha256:" + hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()

def _nullable(v, validate, n):
    if v is not None:
        validate(v, n)

def _digest_map(v, n):
    if not isinstance(v, dict):
        raise ValueError(f"{n} must be a digest map")
    for k, val in v.items():
        _text(k, n + ".key")
        _digest(val, n + "." + k)

def _verification(v):
    _fields(v, {"required_facts", "success_next_action", "failure_next_action"}, "verification")
    _tokens(v["required_facts"], "verification.required_facts")
    if (not isinstance(v["success_next_action"], str) or v["success_next_action"] not in ACTIONS
            or not isinstance(v["failure_next_action"], str) or v["failure_next_action"] not in ACTIONS):
        raise ValueError("non-allowlisted verification branch")

def _recipe(r, v2):
    fields = BASE_FIELDS | ({"scope", "provenance", "max_age_seconds", "verification"} if v2 else set())
    _fields(r, fields, "recipe")
    _text(r["id"], "recipe.id")
    _text(r["diagnosis_code"], "diagnosis_code")
    if type(r["priority"]) is not int or r["priority"] < 0:
        raise ValueError("priority invalid")
    for n in ("requires_all", "forbids", "actions"):
        _tokens(r[n], n)
    if set(r["actions"]) - ACTIONS:
        raise ValueError("recipe contains non-allowlisted action")
    if not isinstance(r["outcome"], str) or r["outcome"] not in OUTCOMES:
        raise ValueError("unsupported outcome")
    if v2:
        if not r["actions"]:
            raise ValueError("v2 actions must be nonempty")
        _fields(r["scope"], SCOPE_FIELDS, "scope")
        for k, val in r["scope"].items():
            _nullable(val, _digest if k in {"policy_digest", "toolchain_fingerprint"} else _text, "scope." + k)
        if r["scope"]["mode"] is not None and (not isinstance(r["scope"]["mode"], str) or r["scope"]["mode"] not in MODES):
            raise ValueError("invalid scope mode")
        _fields(r["provenance"], {"evidence_ref", "evidence_sha256", "verified_at_utc"}, "provenance")
        _text(r["provenance"]["evidence_ref"], "evidence_ref")
        _digest(r["provenance"]["evidence_sha256"], "evidence_sha256")
        _utc(r["provenance"]["verified_at_utc"])
        if type(r["max_age_seconds"]) is not int or r["max_age_seconds"] <= 0:
            raise ValueError("max_age_seconds invalid")
        _verification(r["verification"])

def validate_catalog(c):
    _fields(c, {"schema", "recipes"}, "catalog")
    if not isinstance(c["schema"], str) or c["schema"] not in {"recovery-recipe-catalog/v1", "recovery-recipe-catalog/v2"}:
        raise ValueError("invalid recovery catalog")
    if not isinstance(c["recipes"], list) or not c["recipes"]:
        raise ValueError("recipes must be nonempty list")
    ids = set()
    for r in c["recipes"]:
        _recipe(r, c["schema"] == "recovery-recipe-catalog/v2")
        if r["id"] in ids:
            raise ValueError("duplicate recipe id")
        ids.add(r["id"])
    return c

def validate_diagnosis(d):
    _fields(d, {"schema", "code", "facts", "reference"}, "diagnosis")
    if d["schema"] != "recovery-diagnosis/v1":
        raise ValueError("invalid recovery diagnosis")
    _text(d["code"], "diagnosis.code")
    _tokens(d["facts"], "diagnosis.facts")
    _text(d["reference"], "diagnosis.reference")
    return d

def _binding_values(v):
    for k in ("repository", "environment_namespace", "environment_id"):
        _text(v[k], k)
    if not isinstance(v["access_mode"], str) or v["access_mode"] not in MODES or v["environment_namespace"] != NAMESPACES[v["access_mode"]]:
        raise ValueError("access mode/namespace mismatch")
    _digest(v["toolchain_fingerprint"], "toolchain_fingerprint")
    _digest(v["policy_digest"], "policy_digest")

def validate_bindings(b):
    _fields(b, BINDING_FIELDS, "bindings")
    if b["schema"] != "recovery-bindings/v1":
        raise ValueError("invalid recovery bindings")
    _binding_values(b)
    _digest_map(b["input_digests"], "input_digests")
    return b

def _event(e, repository):
    _fields(e, EVENT_FIELDS, "history event")
    for k in ("event_id", "attempt_id"):
        _text(e[k], k)
    _utc(e["at_utc"])
    _fields(e["subject"], SUBJECT_FIELDS, "subject")
    _binding_values(e["subject"])
    _text(e["subject"]["failure_signature"], "failure_signature")
    if e["subject"]["repository"] != repository:
        raise ValueError("history repository mismatch")
    _digest(e["action_fingerprint"], "action_fingerprint")
    _nullable(e["operation_key"], _digest, "operation_key")
    for k in ("evidence_ref", "new_signal_ref", "completed_correction_ref"):
        _nullable(e[k], _text, k)
    _nullable(e["evidence_digest"], _digest, "evidence_digest")
    if not isinstance(e["state"], str) or e["state"] not in {"prepared", "submitting", "unknown", "terminal"}:
        raise ValueError("invalid history state")
    if e["outcome"] is not None and (not isinstance(e["outcome"], str) or e["outcome"] not in {"verified", "failed", "blocked", "cancelled"}):
        raise ValueError("invalid history outcome")
    if (e["state"] == "terminal") != (e["outcome"] is not None):
        raise ValueError("history state/outcome mismatch")
    if (e["evidence_ref"] is None) != (e["evidence_digest"] is None):
        raise ValueError("history evidence must be paired")
    if e["outcome"] == "verified" and e["evidence_ref"] is None:
        raise ValueError("verified history requires evidence")

def validate_history(h):
    _fields(h, {"schema", "repository", "revision", "events"}, "history")
    if h["schema"] != "recovery-observation-history/v1":
        raise ValueError("invalid recovery history")
    _text(h["repository"], "history.repository")
    if type(h["revision"]) is not int or h["revision"] < 0 or not isinstance(h["events"], list):
        raise ValueError("invalid history revision/events")
    seen = set()
    attempts = {}
    for e in h["events"]:
        _event(e, h["repository"])
        if e["event_id"] in seen:
            raise ValueError("duplicate history event id")
        seen.add(e["event_id"])
        prior = attempts.get(e["attempt_id"])
        if prior is not None:
            for key in ("subject", "action_fingerprint", "operation_key"):
                if e[key] != prior[key]:
                    raise ValueError("history attempt identity changed")
            if prior["state"] == "terminal":
                raise ValueError("terminal history attempt is immutable")
            if _utc(e["at_utc"]) < _utc(prior["at_utc"]):
                raise ValueError("history attempt timestamp regressed")
        attempts[e["attempt_id"]] = e
    return h

def append_history(h, event):
    validate_history(h)
    result = copy.deepcopy(h)
    result["events"].append(copy.deepcopy(event))
    result["revision"] += 1
    validate_history(result)
    return result

def _subject(d, b):
    # Observation reference/chat identity is deliberately absent.
    return {"failure_signature": d["code"], **{k: b[k] for k in SUBJECT_FIELDS - {"failure_signature"}}}

def _subject_events(d, b, h):
    if h["repository"] != b["repository"]:
        raise ValueError("bindings/history repository mismatch")
    subject = _subject(d, b)
    return [e for e in h["events"] if e["subject"] == subject]

def _unresolved(events):
    attempts = {}
    for e in events:
        attempts[e["attempt_id"]] = e
    return [e for e in attempts.values() if e["state"] != "terminal"]

def _signal(s):
    if s is None:
        return
    _fields(s, {"reference", "digest", "changed_inputs", "completed_correction_ref"}, "new_signal")
    _text(s["reference"], "new_signal.reference")
    _digest(s["digest"], "new_signal.digest")
    _digest_map(s["changed_inputs"], "new_signal.changed_inputs")
    _nullable(s["completed_correction_ref"], _text, "completed_correction_ref")

def _effective_signal(s, b, events):
    if s is None or any(e["new_signal_ref"] == s["reference"] for e in events):
        return False
    changed = {k: v for k, v in s["changed_inputs"].items() if k not in INCIDENTAL_INPUTS}
    # Parameters are supplied only to action_plan, so select can qualify a
    # claimed change provisionally. action_plan compares the exact consumed
    # fingerprint over actual handler read dependencies before returning a plan.
    if (changed and b["input_digests"].get(s["reference"]) == s["digest"]
            and all(b["input_digests"].get(k) == v for k, v in changed.items())):
        return True
    correction = s["completed_correction_ref"]
    # A concrete correction must itself have completed with bound verified proof.
    return correction is not None and any(e["state"] == "terminal" and e["outcome"] == "verified"
        and e["evidence_ref"] == correction and e["evidence_digest"] == s["digest"]
        for e in events) and not any(e["completed_correction_ref"] == correction for e in events)

def _result(action, reason, recipe=None, steps=None, outcome=None, v2=True, selected_signal=None):
    result = {"action": action, "reason": reason, "recipe_id": recipe["id"] if recipe else None,
              "steps": copy.deepcopy(steps if steps is not None else recipe["actions"] if recipe else ["escalate_owner"]),
              "outcome": outcome if outcome is not None else recipe["outcome"] if recipe else "blocked",
              **{"authorizes_" + k: False for k in AUTHORITIES}}
    if v2:
        result["recipe"] = copy.deepcopy(recipe)
        result["selected_signal"] = copy.deepcopy(selected_signal)
    return result

def _applicable(r, d, b, now):
    if r["diagnosis_code"] != d["code"] or not set(r["requires_all"]) <= set(d["facts"]) or set(r["forbids"]) & set(d["facts"]):
        return False
    scope = r["scope"]
    for k, value in scope.items():
        binding_key = "access_mode" if k == "mode" else k
        if value is not None and value != b[binding_key]:
            return False
    if any(value is None for value in scope.values()) and r["provenance"]["evidence_sha256"] not in b["input_digests"].values():
        return False
    age = (now - _utc(r["provenance"]["verified_at_utc"])).total_seconds()
    return 0 <= age <= r["max_age_seconds"]

def select(c, d, *, bindings=None, now_utc=None, history=None, new_signal=None):
    validate_catalog(c)
    validate_diagnosis(d)
    if c["schema"] == "recovery-recipe-catalog/v1":
        facts = set(d["facts"])
        matches = [r for r in c["recipes"] if r["diagnosis_code"] == d["code"] and set(r["requires_all"]) <= facts and not (set(r["forbids"]) & facts)]
        if not matches:
            return _result("blocked", "no_deterministic_recipe", v2=False)
        r = min(matches, key=lambda r: (r["priority"], r["id"]))
        return _result("apply_recipe", "deterministic_recipe_selected", recipe=r, v2=False)
    validate_bindings(bindings)
    validate_history(history)
    now = _utc(now_utc)
    _signal(new_signal)
    events = _subject_events(d, bindings, history)
    if _unresolved(events):
        return _result("reconcile", "unresolved_recovery_attempt", steps=["reconcile_external"], outcome="reconcile")
    matches = sorted((r for r in c["recipes"] if _applicable(r, d, bindings, now)), key=lambda r: (r["priority"], r["id"]))
    if events and not _effective_signal(new_signal, bindings, events):
        if matches and events[-1]["outcome"] == "verified" and events[-1]["evidence_digest"] == matches[0]["provenance"]["evidence_sha256"]:
            return _result("apply_recipe", "verified_evidence_reused", recipe=matches[0], steps=["resume_next_action"])
        return _result("blocked", "recovery_observation_consumed", steps=["record_blocker"])
    correction_retry = (events and new_signal is not None
                        and new_signal["completed_correction_ref"] is not None
                        and any(e["outcome"] == "verified" and e["evidence_ref"] == new_signal["completed_correction_ref"]
                                and e["evidence_digest"] == new_signal["digest"] for e in events)
                        and not any(e["completed_correction_ref"] == new_signal["completed_correction_ref"] for e in events))
    if matches:
        return _result("apply_recipe", "completed_correction_retry" if correction_retry else "deterministic_recipe_selected", recipe=matches[0], selected_signal=new_signal)
    return _result("apply_recipe", "completed_correction_retry" if correction_retry else "bounded_diagnostic_required", steps=["inspect_exact_invocation"], outcome="reconcile", selected_signal=new_signal)

def _argv(v, name, *, allow_empty=False):
    if not isinstance(v, list) or (not v and not allow_empty):
        raise ValueError(f"{name} must be an argv list")
    if any(not isinstance(x, str) or not x or x != x.strip() or "\x00" in x for x in v):
        raise ValueError(f"{name} invalid exact argv")

def _parameters(handler, p):
    if not isinstance(p, dict):
        raise ValueError("parameters must be an object")
    dependency_fields = {"dependency_ids", "required_by_check", "installed_evidence_ref", "approved_missing_only_setup_argv"}
    if handler == "refresh_capability_registry":
        _fields(p, {"executable", "expected_version", "profile_binding", "evidence_ref"}, "discovery parameters")
        _text(p["executable"], "executable")
        _nullable(p["expected_version"], _text, "expected_version")
        _digest(p["profile_binding"], "profile_binding")
        _text(p["evidence_ref"], "evidence_ref")
    elif handler in {"inspect_exact_invocation", "resume_next_action"} and set(p) == dependency_fields:
        _tokens(p["dependency_ids"], "dependency_ids")
        if not p["dependency_ids"]:
            raise ValueError("dependency_ids must be nonempty")
        _text(p["required_by_check"], "required_by_check")
        _nullable(p["installed_evidence_ref"], _text, "installed_evidence_ref")
        _argv(p["approved_missing_only_setup_argv"], "approved_missing_only_setup_argv", allow_empty=True)
        if p["installed_evidence_ref"] is not None and p["approved_missing_only_setup_argv"]:
            raise ValueError("present dependencies must not be reinstalled")
        if handler == "resume_next_action" and p["installed_evidence_ref"] is None:
            raise ValueError("dependency resume requires installed evidence")
    elif handler == "inspect_exact_invocation":
        base = {"invocation_ref", "error_evidence_ref", "approved_read_argv"}
        if set(p) == base | {"diagnostic_limit"}:
            if type(p["diagnostic_limit"]) is not int or p["diagnostic_limit"] != 1:
                raise ValueError("diagnostic_limit must be 1")
        elif set(p) == base | {"bound_route_ref"}:
            _text(p["bound_route_ref"], "bound_route_ref")
        else:
            raise ValueError("inspection parameters fields mismatch")
        _text(p["invocation_ref"], "invocation_ref")
        _text(p["error_evidence_ref"], "error_evidence_ref")
        _argv(p["approved_read_argv"], "approved_read_argv")
    elif handler == "reconcile_external":
        _fields(p, {"operation_key", "journal_ref", "task_id", "task_mode"}, "reconciliation parameters")
        _digest(p["operation_key"], "operation_key")
        _text(p["journal_ref"], "journal_ref")
        _nullable(p["task_id"], _text, "task_id")
        if not isinstance(p["task_mode"], str) or p["task_mode"] not in {"DEVELOPMENT", "COMPUTE_ONLY"}:
            raise ValueError("invalid task_mode")
    elif handler == "record_blocker":
        _fields(p, {"evidence_ref", "reason"}, "blocker parameters")
        _text(p["evidence_ref"], "evidence_ref")
        _text(p["reason"], "reason")
    elif handler == "resume_next_action":
        _fields(p, {"next_action_ref", "evidence_ref"}, "resume parameters")
        _text(p["next_action_ref"], "next_action_ref")
        _text(p["evidence_ref"], "evidence_ref")
    else:
        raise ValueError("handler lacks an approved typed parameter contract")

def _read_inputs(handler, parameters, bindings):
    """Project only read dependencies of this concrete typed handler.

    Input names are either these fixed semantic roles or the exact reference
    values in its typed parameters. Other map entries may attest signals, but
    cannot change an action fingerprint. No handler here reads candidate source.
    """
    roles = {"qualification"}
    references = set()
    if handler == "refresh_capability_registry":
        roles |= {"profile", "executable", "expected_version"}
        references.add(parameters["evidence_ref"])
    elif handler in {"inspect_exact_invocation", "resume_next_action"} and "dependency_ids" in parameters:
        roles |= {"installed_dependencies", "setup"}
        roles |= {"dependency:" + name for name in parameters["dependency_ids"]}
        references.add(parameters["required_by_check"])
        if parameters["installed_evidence_ref"] is not None:
            references.add(parameters["installed_evidence_ref"])
    elif handler == "inspect_exact_invocation":
        roles |= {"error", "invocation", "route"}
        references |= {parameters["invocation_ref"], parameters["error_evidence_ref"]}
        if "bound_route_ref" in parameters:
            references.add(parameters["bound_route_ref"])
    elif handler == "reconcile_external":
        roles |= {"journal", "operation"}
        references |= {parameters["journal_ref"], parameters["operation_key"]}
    elif handler == "resume_next_action":
        references |= {parameters["next_action_ref"], parameters["evidence_ref"]}
    elif handler == "record_blocker":
        references.add(parameters["evidence_ref"])
    return {k: v for k, v in bindings["input_digests"].items() if k in roles | references}

def selection_verification(selection):
    """Shared serialized recipe/step contract; this never qualifies or executes it."""
    recipe = selection['recipe']
    if recipe is not None:
        _recipe(recipe, True)
        if selection['recipe_id'] != recipe['id']:
            raise ValueError('selection recipe mismatch')
        expected = ['resume_next_action'] if selection['reason'] == 'verified_evidence_reused' else recipe['actions']
        if selection['steps'] != expected:
            raise ValueError('selection steps differ from recipe')
        return copy.deepcopy(recipe['verification'])
    if selection['recipe_id'] is not None:
        raise ValueError('selection missing recipe projection')
    return {'required_facts': ['result:bound'], 'success_next_action': 'resume_next_action',
            'failure_next_action': 'record_blocker'}


def action_plan(selection, diagnosis, bindings, history, parameters):
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    validate_diagnosis(diagnosis)
    validate_bindings(bindings)
    validate_history(history)
    _fields(selection, SELECTION_FIELDS, "v2 selection")
    _signal(selection["selected_signal"])
    if (not isinstance(selection["action"], str) or selection["action"] not in {"apply_recipe", "blocked", "reconcile"}
            or not isinstance(selection["outcome"], str) or selection["outcome"] not in OUTCOMES):
        raise ValueError("invalid selection action/outcome")
    _text(selection["reason"], "selection.reason")
    _tokens(selection["steps"], "selection.steps")
    if not selection["steps"] or set(selection["steps"]) - ACTIONS:
        raise ValueError("invalid selected steps")
    if any(selection["authorizes_" + k] is not False for k in AUTHORITIES):
        raise ValueError("selection cannot grant authority")
    recipe = selection["recipe"]
    if recipe is not None:
        _recipe(recipe, True)
        if selection["recipe_id"] != recipe["id"] or recipe["diagnosis_code"] != diagnosis["code"]:
            raise ValueError("selection recipe mismatch")
    verification = selection_verification(selection)
    handler = selection["steps"][0]
    events = _subject_events(diagnosis, bindings, history)
    unresolved = _unresolved(events)
    if unresolved:
        if handler != "reconcile_external" or selection["action"] != "reconcile":
            raise ValueError("unresolved effects can only reconcile")
        keys = {e["operation_key"] for e in unresolved}
        if keys != {parameters.get("operation_key")} or None in keys:
            raise ValueError("reconciliation must retain known operation identity")
    if selection["action"] == "blocked" and handler != "record_blocker":
        raise ValueError("blocked selection must record blocker")
    _parameters(handler, parameters)
    if "installed_evidence_ref" in parameters and parameters["installed_evidence_ref"] is not None:
        installed = parameters["installed_evidence_ref"]
        if installed not in bindings["input_digests"] and not any(
                e["evidence_ref"] == installed and e["outcome"] == "verified" for e in events):
            raise ValueError("installed dependency proof must be locally bound")
    if handler == "record_blocker" and events and parameters["evidence_ref"] != events[-1]["evidence_ref"]:
        raise ValueError("blocker must preserve original evidence")
    if selection["reason"] == "bounded_diagnostic_required" and handler != "inspect_exact_invocation":
        raise ValueError("diagnostic selection handler mismatch")
    relevant = _read_inputs(handler, parameters, bindings)
    fingerprint = _hash({"subject": _subject(diagnosis, bindings), "handler": handler,
                         "parameters": parameters, "verification": verification, "input_digests": relevant})
    if handler not in {"record_blocker", "resume_next_action", "reconcile_external"} and any(
            e["action_fingerprint"] == fingerprint for e in events):
        # A completed verified correction may legitimately preserve the exact
        # action inputs. Merely loading another chat or a stale selection cannot.
        used = {e["completed_correction_ref"] for e in events if e["completed_correction_ref"] is not None}
        signal = selection["selected_signal"]
        correction = None if signal is None else signal["completed_correction_ref"]
        corrections = [e for e in events if signal is not None
                       and e["state"] == "terminal" and e["outcome"] == "verified"
                       and e["action_fingerprint"] != fingerprint
                       and e["evidence_ref"] == correction and e["evidence_digest"] == signal["digest"]
                       and e["evidence_ref"] not in used]
        if (selection["reason"] != "completed_correction_retry" or not corrections
                or not _effective_signal(signal, bindings, events)):
            raise ValueError("exact recovery action already consumed")
    return {"schema": "recovery-action-plan/v1", "handler": handler, "parameters": copy.deepcopy(parameters),
            "action_fingerprint": fingerprint, "verification": copy.deepcopy(verification),
            "next_on_success": verification["success_next_action"], "next_on_failure": verification["failure_next_action"],
            "authorities": copy.deepcopy(AUTHORITIES)}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("catalog")
    p.add_argument("diagnosis")
    a = p.parse_args(argv)
    try:
        r = select(json.loads(Path(a.catalog).read_text()), json.loads(Path(a.diagnosis).read_text()))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, sort_keys=True))
    return 0 if r["action"] == "apply_recipe" else 1

if __name__ == "__main__":
    raise SystemExit(main())
