"""Filesystem locations for VoltShift runtime artifacts.

Everything lives next to the executable (frozen build) or the repo root
(running from source), so a portable install keeps its config, profiles,
and crash logs together.
"""

from __future__ import annotations

import os
import sys


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # src/voltshift/paths.py -> repo root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def bridge_path() -> str:
    """Locate voltshift_bridge.exe: next to the app first, then the dev build."""
    candidates = [
        os.path.join(app_dir(), "voltshift_bridge.exe"),
        os.path.join(app_dir(), "bridge", "build", "Release", "voltshift_bridge.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


def config_path() -> str:
    return os.path.join(app_dir(), "voltshift_config.json")


def profiles_dir() -> str:
    path = os.path.join(app_dir(), "profiles")
    os.makedirs(path, exist_ok=True)
    return path


def crash_log_path() -> str:
    return os.path.join(app_dir(), "voltshift_crashes.log")
