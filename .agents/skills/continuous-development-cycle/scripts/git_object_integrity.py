#!/usr/bin/env python3
"""Environment for Git identity, provenance, and control-store subprocesses only."""
from __future__ import annotations

import os


def git_object_environment(**overrides):
    """Read genuine objects/parents even when a checkout has local overlays.

    Replacement refs can substitute bytes beneath a genuine SHA; legacy grafts
    can fabricate ancestry even when replacements are disabled. These are never
    authority for control/provenance decisions. Do not apply this environment to
    arbitrary user validation commands or change the parent process environment.
    """
    return {**os.environ, **overrides, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_GRAFT_FILE": os.devnull}
