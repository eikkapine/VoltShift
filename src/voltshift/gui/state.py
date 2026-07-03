"""Shared application state for the GUI.

Owns the single BridgeClient, the discovered capabilities, the dynamic
voltage engine runner, the crash logger, and the app-boost watcher. Pages
read and mutate through here so there is one source of truth and one daemon.

Thread marshalling: the engine/crash/boost callbacks fire on worker threads;
`post` hops them onto the Tk main loop via `after` so pages can update
widgets safely.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

from .. import paths
from ..appboost import AppBoostWatcher, BoostConfig
from ..bridgeclient import BridgeClient, BridgeError
from ..crashlog import CrashLogger
from ..engine import EngineConfig
from ..runner import EngineRunner


class AppState:
    def __init__(self, tk_root):
        self._root = tk_root
        self._closing = False
        self.bridge = BridgeClient()
        self.info: dict = {}
        self.caps: dict = {}
        self.connected = False
        self.connect_error: Optional[str] = None

        self.engine_config = EngineConfig()
        self.boost_config = BoostConfig()
        self.runner: Optional[EngineRunner] = None
        self.crash_logger: Optional[CrashLogger] = None
        self.appboost: Optional[AppBoostWatcher] = None

        # Subscribers (all invoked on the Tk main thread).
        self.log_sinks: list[Callable[[str, str], None]] = []
        self.sample_sinks: list[Callable[[dict], None]] = []

        self._load_settings()

    # ── thread marshalling ───────────────────────────────────────────────────

    def post(self, fn: Callable, *args) -> None:
        """Run fn(*args) on the Tk main loop."""
        if self._closing:
            return
        try:
            self._root.after(0, lambda: fn(*args))
        except RuntimeError:
            pass  # window torn down

    def log(self, msg: str, level: str = "info") -> None:
        def deliver() -> None:
            for sink in self.log_sinks:
                sink(msg, level)
        self.post(deliver)

    # ── connection ───────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self.bridge.start()
            self.info = self.bridge.info()
            self.caps = self.bridge.caps()
            self.connected = True
            self.connect_error = None
            self.crash_logger = CrashLogger(self.engine_config.to_dict())
            self.crash_logger.on_log_entry = self.log
            self.crash_logger.check_previous_session()
            return True
        except BridgeError as exc:
            self.connected = False
            self.connect_error = str(exc)
            return False

    def gpu_name(self) -> str:
        return self.info.get("name", "No GPU")

    # ── dynamic voltage engine ───────────────────────────────────────────────

    def start_engine(self) -> None:
        if self.runner and self.runner.running:
            return
        if self.crash_logger:
            self.crash_logger.update_config(self.engine_config.to_dict())
            self.crash_logger.start()
            self.crash_logger.write_session_header(self.gpu_name(),
                                                   self.engine_config.to_dict())
        self.runner = EngineRunner(self.bridge, self.engine_config, self.crash_logger)
        self.runner.on_log_entry = lambda m, lvl: self.log(m, lvl)
        self.runner.on_sample = self._dispatch_sample
        self.runner.on_error = lambda m: self.log(m, "error")
        self.runner.start()

    def stop_engine(self) -> None:
        if self.runner:
            self.runner.stop(reset_gpu=True)
        if self.crash_logger:
            self.crash_logger.stop()
            self.crash_logger.write_session_footer(self.crash_logger.crash_count)

    @property
    def engine_running(self) -> bool:
        return self.runner is not None and self.runner.running

    def _dispatch_sample(self, sample: dict) -> None:
        def deliver() -> None:
            for sink in self.sample_sinks:
                sink(sample)
        self.post(deliver)

    # ── app boost ────────────────────────────────────────────────────────────

    def start_appboost(self) -> None:
        if self.appboost and self.appboost.active:
            return
        self.appboost = AppBoostWatcher(self.bridge, self.boost_config)
        self.appboost.on_log_entry = self.log
        self.appboost.start()

    def stop_appboost(self) -> None:
        if self.appboost:
            self.appboost.stop()

    @property
    def appboost_active(self) -> bool:
        return self.appboost is not None and self.appboost.active

    # ── settings persistence ─────────────────────────────────────────────────

    def _load_settings(self) -> None:
        try:
            with open(paths.config_path(), encoding="utf-8") as f:
                data = json.load(f)
            if "engine" in data:
                self.engine_config = EngineConfig.from_dict(data["engine"])
            if "boost" in data:
                self.boost_config = BoostConfig.from_dict(data["boost"])
        except (OSError, ValueError):
            pass

    def save_settings(self) -> None:
        data = {"engine": self.engine_config.to_dict(),
                "boost": self.boost_config.to_dict()}
        tmp = paths.config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, paths.config_path())

    # ── teardown ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._closing = True
        try:
            self.stop_engine()
        except Exception:
            pass
        try:
            self.stop_appboost()
        except Exception:
            pass
        self.bridge.stop()
