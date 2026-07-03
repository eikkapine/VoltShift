"""Fans — 5-point fan curve editor and ZeroRPM toggle.

Each curve point is a temperature/speed pair of sliders; the point count is
fixed by the driver (the empty-state list length). A small text preview
sketches the curve. ZeroRPM lets the fans stop under a low thermal load.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import theme
from ..widgets import Card, LabeledSlider, ToggleRow
from ...bridgeclient import BridgeError
from .base import Page


class FansPage(Page):
    title = "Fans"

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self._point_sliders: list[tuple[LabeledSlider, LabeledSlider]] = []

        self._card = Card(self, title="Fan curve")
        self._card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._body = self._card.body()
        self._body.grid_columnconfigure(0, weight=1)

        self._points_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        self._points_frame.grid(row=0, column=0, sticky="ew")
        self._points_frame.grid_columnconfigure(0, weight=1)

        self._zero_rpm = ToggleRow(self._body, "ZeroRPM (fans stop when cool)",
                                   self._on_zero_rpm)
        self._zero_rpm.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        buttons = ctk.CTkFrame(self._body, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkButton(buttons, text="Apply curve", fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, command=self._apply
                      ).pack(side="right")
        ctk.CTkButton(buttons, text="Reload", fg_color=theme.SURFACE_2,
                      hover_color=theme.SURFACE_3, command=self._refresh
                      ).pack(side="right", padx=(0, 8))

        self._notice = ctk.CTkLabel(self._body, text="", font=(theme.FONT, 12),
                                    text_color=theme.TEXT_FAINT)

    def on_show(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        for slider_pair in self._point_sliders:
            slider_pair[0].destroy()
            slider_pair[1].destroy()
        self._point_sliders.clear()
        self._notice.grid_forget()

        if not self.state.connected:
            return
        if not self.state.caps.get("tuning", {}).get("manualFan"):
            self._notice.configure(text="Manual fan tuning is not supported on this GPU.")
            self._notice.grid(row=0, column=0, sticky="w")
            return

        try:
            fans = self.state.bridge.fans_get()
        except BridgeError as exc:
            self._notice.configure(text=f"Fan read failed: {exc}")
            self._notice.grid(row=0, column=0, sticky="w")
            return

        speed_range = fans.get("speedRange", {"min": 0, "max": 100})
        temp_range = fans.get("tempRange", {"min": 0, "max": 100})
        curve = fans.get("curve", [])

        for i, point in enumerate(curve):
            frame = ctk.CTkFrame(self._points_frame, fg_color=theme.SURFACE_2,
                                 corner_radius=8)
            frame.grid(row=i, column=0, sticky="ew", pady=4)
            frame.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(frame, text=f"Point {i + 1}", font=(theme.FONT, 11, "bold"),
                         text_color=theme.TEXT_DIM).grid(row=0, column=0, sticky="w",
                                                         padx=12, pady=(8, 0))
            temp = LabeledSlider(frame, "Temp", temp_range.get("min", 0),
                                 temp_range.get("max", 100), 1, "°C")
            temp.grid(row=1, column=0, sticky="ew", padx=12)
            temp.set(point.get("tempC", 0))
            speed = LabeledSlider(frame, "Speed", speed_range.get("min", 0),
                                  speed_range.get("max", 100), 1, "%")
            speed.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
            speed.set(point.get("speedPct", 0))
            self._point_sliders.append((temp, speed))

        zero_supported = fans.get("zeroRpmSupported", False)
        self._zero_rpm.set_state(fans.get("zeroRpm", False), zero_supported)

    def _on_zero_rpm(self, enabled: bool) -> None:
        try:
            self.state.bridge.set_zero_rpm(enabled)
            self.state.log(f"ZeroRPM {'on' if enabled else 'off'}", "volt")
        except BridgeError as exc:
            self.state.log(f"ZeroRPM failed: {exc}", "error")

    def _apply(self) -> None:
        curve = [{"tempC": temp.get(), "speedPct": speed.get()}
                 for temp, speed in self._point_sliders]
        if not curve:
            return
        try:
            self.state.bridge.set_fan_curve(curve)
            self.state.log(f"Fan curve applied ({len(curve)} points)", "volt")
        except BridgeError as exc:
            self.state.log(f"Fan curve failed: {exc}", "error")
