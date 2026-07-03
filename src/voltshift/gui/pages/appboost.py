"""App Boost — apply a tuning boost while chosen apps are running.

List the executable names to watch (one per line), set the boost power
limit and optional max-clock, and start the watcher. When any watched app is
running the boost is applied; when they all close, the previous values are
restored.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import theme
from ..widgets import Card, LabeledSlider
from ...appboost import BoostConfig
from .base import Page


class AppBoostPage(Page):
    title = "App Boost"

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        apps = Card(self, title="Watched applications")
        apps.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        abody = apps.body()
        abody.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(abody, text="One executable name per line, e.g. cyberpunk2077.exe",
                     font=(theme.FONT, 11), text_color=theme.TEXT_FAINT, anchor="w"
                     ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._apps_box = ctk.CTkTextbox(abody, height=120, fg_color=theme.SURFACE_2,
                                        font=(theme.FONT_MONO, 12), border_width=1,
                                        border_color=theme.BORDER)
        self._apps_box.grid(row=1, column=0, sticky="ew")

        boost = Card(self, title="Boost values")
        boost.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        bbody = boost.body()
        bbody.grid_columnconfigure(0, weight=1)
        self._power = LabeledSlider(bbody, "Power limit", -30, 15, 1, "%")
        self._power.grid(row=0, column=0, sticky="ew")
        self._max_clock = LabeledSlider(bbody, "Max clock", 500, 3400, 10, "MHz")
        self._max_clock.grid(row=1, column=0, sticky="ew")
        self._max_clock_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(bbody, text="Also raise max clock while boosted",
                        variable=self._max_clock_var, fg_color=theme.ACCENT,
                        hover_color=theme.ACCENT_HOVER).grid(row=2, column=0, sticky="w", pady=6)

        control = Card(self)
        control.grid(row=2, column=0, sticky="ew")
        cbody = control.body()
        cbody.grid_columnconfigure(1, weight=1)
        self._toggle_btn = ctk.CTkButton(cbody, text="▶  Start watching", width=160, height=40,
                                         fg_color=theme.ACCENT_2, hover_color=theme.ACCENT_2_HOVER,
                                         text_color="#08130f", font=(theme.FONT, 13, "bold"),
                                         command=self._toggle)
        self._toggle_btn.grid(row=0, column=0, padx=(0, 12))
        self._status = ctk.CTkLabel(cbody, text="Idle", font=(theme.FONT, 13),
                                    text_color=theme.TEXT_DIM)
        self._status.grid(row=0, column=1, sticky="w")

        self._load()

    def _load(self) -> None:
        cfg = self.state.boost_config
        self._apps_box.delete("1.0", "end")
        self._apps_box.insert("1.0", "\n".join(cfg.apps))
        self._power.set(cfg.power_limit_pct if cfg.power_limit_pct is not None else 0)
        if cfg.max_clock_mhz is not None:
            self._max_clock.set(cfg.max_clock_mhz)
            self._max_clock_var.set(True)

    def _collect(self) -> BoostConfig:
        apps = [line.strip() for line in self._apps_box.get("1.0", "end").splitlines()
                if line.strip()]
        return BoostConfig(
            apps=apps,
            power_limit_pct=self._power.get(),
            max_clock_mhz=self._max_clock.get() if self._max_clock_var.get() else None,
            poll_interval_sec=self.state.boost_config.poll_interval_sec,
        )

    def _toggle(self) -> None:
        if self.state.appboost_active:
            self.state.stop_appboost()
            self._toggle_btn.configure(text="▶  Start watching", fg_color=theme.ACCENT_2)
            self._status.configure(text="Idle", text_color=theme.TEXT_DIM)
        else:
            if not self.state.connected:
                self.state.log("Cannot start app boost — bridge not connected", "error")
                return
            self.state.boost_config = self._collect()
            self.state.save_settings()
            if not self.state.boost_config.apps:
                self.state.log("Add at least one app to watch", "warn")
                return
            self.state.start_appboost()
            self._toggle_btn.configure(text="■  Stop watching", fg_color=theme.DANGER)
            self._status.configure(text=f"Watching {len(self.state.boost_config.apps)} app(s)",
                                   text_color=theme.GOOD)

    def on_show(self) -> None:
        if self.state.appboost_active:
            self._toggle_btn.configure(text="■  Stop watching", fg_color=theme.DANGER)
            self._status.configure(text="Watching", text_color=theme.GOOD)
