"""Tuning — manual voltage, core clocks, VRAM, power, and memory timing.

Sliders configure themselves from the ranges the bridge reports in
tuning.get, so unsupported controls disable and the bounds always match the
hardware. Writes are explicit (Apply button) to avoid firing on every drag.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import theme
from ..widgets import Card, LabeledSlider
from ...adlxenums import MEMORY_TIMINGS
from ...bridgeclient import BridgeError
from .base import Page


class TuningPage(Page):
    title = "Tuning"

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        warn = ctk.CTkLabel(
            self, anchor="w", justify="left", font=(theme.FONT, 11),
            text_color=theme.WARN,
            text="Manual overrides persist until you reset. Test changes with a stress "
                 "run. Use the Reset button (or Adrenalin) to restore defaults.")
        warn.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        # GFX: voltage + clocks.
        gfx = Card(self, title="Core & voltage")
        gfx.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        gbody = gfx.body()
        gbody.grid_columnconfigure(0, weight=1)
        self._voltage = LabeledSlider(gbody, "Voltage offset", -200, 0, 5, "mV")
        self._voltage.grid(row=0, column=0, sticky="ew")
        self._min_clock = LabeledSlider(gbody, "Min clock", 500, 3000, 10, "MHz")
        self._min_clock.grid(row=1, column=0, sticky="ew")
        self._max_clock = LabeledSlider(gbody, "Max clock", 500, 3400, 10, "MHz")
        self._max_clock.grid(row=2, column=0, sticky="ew")
        ctk.CTkButton(gbody, text="Apply core & voltage", fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, command=self._apply_gfx
                      ).grid(row=3, column=0, sticky="e", pady=(6, 0))

        # VRAM.
        vram = Card(self, title="Memory")
        vram.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        vbody = vram.body()
        vbody.grid_columnconfigure(0, weight=1)
        self._vram_clock = LabeledSlider(vbody, "VRAM max clock", 2000, 3000, 2, "MHz")
        self._vram_clock.grid(row=0, column=0, sticky="ew")
        timing_row = ctk.CTkFrame(vbody, fg_color="transparent")
        timing_row.grid(row=1, column=0, sticky="ew", pady=6)
        ctk.CTkLabel(timing_row, text="Memory timing", font=(theme.FONT, 12),
                     text_color=theme.TEXT, width=120, anchor="w").pack(side="left")
        self._timing_menu = ctk.CTkOptionMenu(
            timing_row, values=["Default"], command=self._on_timing_pick,
            fg_color=theme.SURFACE_2, button_color=theme.SURFACE_3,
            button_hover_color=theme.BORDER)
        self._timing_menu.pack(side="left")
        self._timing_options: dict[str, int] = {}
        ctk.CTkButton(vbody, text="Apply memory", fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, command=self._apply_vram
                      ).grid(row=2, column=0, sticky="e", pady=(6, 0))

        # Power.
        power = Card(self, title="Power")
        power.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        pbody = power.body()
        pbody.grid_columnconfigure(0, weight=1)
        self._power_limit = LabeledSlider(pbody, "Power limit", -30, 15, 1, "%")
        self._power_limit.grid(row=0, column=0, sticky="ew")
        self._tdc = LabeledSlider(pbody, "TDC limit", 0, 100, 1, "A")
        self._tdc.grid(row=1, column=0, sticky="ew")
        ctk.CTkButton(pbody, text="Apply power", fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, command=self._apply_power
                      ).grid(row=2, column=0, sticky="e", pady=(6, 0))

        # Reset.
        reset = ctk.CTkButton(self, text="Reset all tuning to factory defaults",
                              fg_color=theme.DANGER, hover_color=theme.DANGER_HOVER,
                              command=self._reset)
        reset.grid(row=4, column=0, sticky="ew")

    def on_show(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        if not self.state.connected:
            return
        try:
            tuning = self.state.bridge.tuning_get()
        except BridgeError as exc:
            self.state.log(f"Tuning read failed: {exc}", "error")
            return

        gfx = tuning.get("gfx", {})
        gfx_ok = "unsupported" not in gfx
        self._voltage.set_supported(gfx_ok)
        self._min_clock.set_supported(gfx_ok and "minFreqRange" in gfx)
        self._max_clock.set_supported(gfx_ok and "maxFreqRange" in gfx)
        if gfx_ok:
            vr = gfx.get("voltageRange", {})
            self._voltage.configure_range(vr.get("min", -200), vr.get("max", 0), 5)
            self._voltage.set(gfx.get("voltageMv", 0))
            if "minFreqRange" in gfx:
                r = gfx["minFreqRange"]
                self._min_clock.configure_range(r.get("min", 500), max(r.get("max", 3000), 501), 10)
                self._min_clock.set(gfx.get("minFreqMhz", r.get("min", 500)))
            if "maxFreqRange" in gfx:
                r = gfx["maxFreqRange"]
                self._max_clock.configure_range(r.get("min", 500), max(r.get("max", 3400), 501), 10)
                self._max_clock.set(gfx.get("maxFreqMhz", r.get("max", 3000)))

        vram = tuning.get("vram", {})
        vram_ok = "unsupported" not in vram
        self._vram_clock.set_supported(vram_ok)
        if vram_ok and "maxFreqRange" in vram:
            r = vram["maxFreqRange"]
            self._vram_clock.configure_range(r.get("min", 2000), max(r.get("max", 3000), r.get("min", 2000) + 1),
                                             max(1, r.get("step", 2)))
            self._vram_clock.set(vram.get("maxFreqMhz", r.get("min", 2000)))
        if vram_ok and vram.get("timingSupported"):
            options = vram.get("timingOptions", [0])
            self._timing_options = {MEMORY_TIMINGS.get(o, f"Timing {o}"): o for o in options}
            names = list(self._timing_options.keys())
            self._timing_menu.configure(values=names, state="normal")
            current = vram.get("timing", 0)
            for name, val in self._timing_options.items():
                if val == current:
                    self._timing_menu.set(name)
                    break
        else:
            self._timing_menu.configure(state="disabled")

        power = tuning.get("power", {})
        power_ok = "unsupported" not in power
        self._power_limit.set_supported(power_ok)
        if power_ok:
            r = power.get("powerLimitRange", {})
            self._power_limit.configure_range(r.get("min", -30), r.get("max", 15), 1)
            self._power_limit.set(power.get("powerLimit", 0))
        tdc_ok = power_ok and power.get("tdcSupported")
        self._tdc.set_supported(bool(tdc_ok))
        if tdc_ok:
            r = power.get("tdcRange", {})
            self._tdc.configure_range(r.get("min", 0), max(r.get("max", 100), 1), 1)
            self._tdc.set(power.get("tdcLimit", 0))

    def _on_timing_pick(self, _name: str) -> None:
        pass  # applied via Apply memory button

    # ── apply actions ────────────────────────────────────────────────────────

    def _apply_gfx(self) -> None:
        try:
            self.state.bridge.set_voltage_offset(self._voltage.get())
            self.state.bridge.set_core_clocks(self._min_clock.get(), self._max_clock.get())
            self.state.log(f"Applied voltage {self._voltage.get():+d} mV, clocks "
                           f"{self._min_clock.get()}–{self._max_clock.get()} MHz", "volt")
        except BridgeError as exc:
            self.state.log(f"Apply failed: {exc}", "error")

    def _apply_vram(self) -> None:
        try:
            self.state.bridge.set_vram_max(self._vram_clock.get())
            name = self._timing_menu.get()
            if name in self._timing_options:
                self.state.bridge.set_memory_timing(self._timing_options[name])
            self.state.log(f"Applied VRAM {self._vram_clock.get()} MHz, timing '{name}'", "volt")
        except BridgeError as exc:
            self.state.log(f"VRAM apply failed: {exc}", "error")

    def _apply_power(self) -> None:
        try:
            self.state.bridge.set_power_limit(self._power_limit.get())
            self.state.log(f"Applied power limit {self._power_limit.get():+d}%", "volt")
        except BridgeError as exc:
            self.state.log(f"Power apply failed: {exc}", "error")

    def _reset(self) -> None:
        try:
            self.state.bridge.tuning_reset()
            self.state.log("Tuning reset to factory defaults", "volt")
            self._refresh()
        except BridgeError as exc:
            self.state.log(f"Reset failed: {exc}", "error")
