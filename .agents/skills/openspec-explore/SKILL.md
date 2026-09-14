---
name: openspec-explore
description: Explore ideas, problems, and requirements in an OpenSpec-aware read-only mode before implementation.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires OpenSpec CLI 1.13.0 for this repository.
metadata:
  author: openspec
  version: "1.13.0"
---

Enter an OpenSpec-aware exploration mode.

## Rules

- Exploration is for thinking and investigation, not implementation.
- Read the repository, tests, docs, current OpenSpec specs, and active changes before asking factual questions that can be answered from the project.
- Start with `openspec list --json` and `openspec list --specs --json` when relevant.
- Read `openspec/config.yaml` and treat its context and rules as project constraints.
- Never edit runtime code in this workflow.
- Only create or revise OpenSpec artifacts after the user explicitly authorizes that write scope.
- Surface conflicts between implementation, existing specs, and proposed behavior rather than silently choosing one.
- When the idea is sufficiently clear, recommend `openspec-propose`; do not start implementation.
