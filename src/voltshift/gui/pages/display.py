"""Display — per-display settings, one selectable display at a time.

A dropdown picks the display; the panel below reflects that display's
FreeSync, VSR, scaling, color depth, pixel format, and custom color, with
unsupported controls disabled.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import theme
from ..widgets import Card, ChoiceRow, LabeledSlider, ToggleRow
from ...adlxenums import COLOR_DEPTHS, PIXEL_FORMATS, SCALING_MODES
from ...bridgeclient import BridgeError
from .base import Page


class DisplayPage(Page):
    title = "Display"

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self._displays: list[dict] = []
        self._index = 0

        picker = Card(self, title="Display")
        picker.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        pbody = picker.body()
        pbody.grid_columnconfigure(0, weight=1)
        self._menu = ctk.CTkOptionMenu(pbody, values=["—"], command=self._on_pick,
                                       fg_color=theme.SURFACE_2, button_color=theme.SURFACE_3,
                                       button_hover_color=theme.BORDER)
        self._menu.grid(row=0, column=0, sticky="w")

        toggles = Card(self, title="Adaptive sync & scaling")
        toggles.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        tb = toggles.body()
        tb.grid_columnconfigure(0, weight=1)
        self._rows: dict[str, object] = {}
        self._rows["freeSync"] = ToggleRow(tb, "FreeSync",
                                           lambda v: self._set("freeSync", enabled=v),
                                           "Variable refresh rate")
        self._rows["freeSync"].grid(row=0, column=0, sticky="ew")
        self._rows["vsr"] = ToggleRow(tb, "Virtual Super Resolution",
                                      lambda v: self._set("vsr", enabled=v),
                                      "Render above native and downscale")
        self._rows["vsr"].grid(row=1, column=0, sticky="ew")
        self._rows["gpuScaling"] = ToggleRow(tb, "GPU scaling",
                                             lambda v: self._set("gpuScaling", enabled=v))
        self._rows["gpuScaling"].grid(row=2, column=0, sticky="ew")
        self._rows["integerScaling"] = ToggleRow(tb, "Integer scaling",
                                                 lambda v: self._set("integerScaling", enabled=v),
                                                 "Sharp pixel-doubled upscaling")
        self._rows["integerScaling"].grid(row=3, column=0, sticky="ew")
        self._rows["scalingMode"] = ChoiceRow(tb, "Scaling mode", SCALING_MODES,
                                              lambda v: self._set("scalingMode", mode=v))
        self._rows["scalingMode"].grid(row=4, column=0, sticky="ew")

        signal = Card(self, title="Signal")
        signal.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        sb = signal.body()
        sb.grid_columnconfigure(0, weight=1)
        self._rows["colorDepth"] = ChoiceRow(sb, "Color depth", COLOR_DEPTHS,
                                             lambda v: self._set("colorDepth", value=v))
        self._rows["colorDepth"].grid(row=0, column=0, sticky="ew")
        self._rows["pixelFormat"] = ChoiceRow(sb, "Pixel format", PIXEL_FORMATS,
                                              lambda v: self._set("pixelFormat", value=v))
        self._rows["pixelFormat"].grid(row=1, column=0, sticky="ew")
        self._rows["hdcp"] = ToggleRow(sb, "HDCP", lambda v: self._set("hdcp", enabled=v))
        self._rows["hdcp"].grid(row=2, column=0, sticky="ew")

        color = Card(self, title="Custom color")
        color.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        cb = color.body()
        cb.grid_columnconfigure(0, weight=1)
        for i, channel in enumerate(("brightness", "contrast", "saturation", "hue", "temperature")):
            unit = "K" if channel == "temperature" else ""
            slider = LabeledSlider(cb, channel.capitalize(), -100, 100, 1, unit,
                                   lambda v, ch=channel: self._set_color(ch, v))
            slider.grid(row=i, column=0, sticky="ew")
            self._rows[f"color_{channel}"] = slider

    def on_show(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        if not self.state.connected:
            return
        try:
            self._displays = self.state.bridge.display_list()
        except BridgeError as exc:
            self.state.log(f"Display list failed: {exc}", "error")
            return
        names = [f"{d['index']}: {d['name']}" for d in self._displays] or ["—"]
        self._menu.configure(values=names)
        if self._displays:
            self._menu.set(names[min(self._index, len(names) - 1)])
            self._load(self._displays[min(self._index, len(self._displays) - 1)]["index"])

    def _on_pick(self, name: str) -> None:
        try:
            self._index = int(name.split(":")[0])
        except ValueError:
            return
        self._load(self._index)

    def _load(self, index: int) -> None:
        try:
            state = self.state.bridge.display_get(index)
        except BridgeError as exc:
            self.state.log(f"Display read failed: {exc}", "error")
            return
        self._applying = True
        try:
            for key in ("freeSync", "vsr", "gpuScaling", "integerScaling", "hdcp"):
                s = state.get(key, {})
                self._rows[key].set_state(s.get("enabled", False), s.get("supported", False))
            sm = state.get("scalingMode", {})
            self._rows["scalingMode"].set_supported(sm.get("supported", False))
            if sm.get("supported"):
                self._rows["scalingMode"].set_value(sm.get("mode", 0))
            cd = state.get("colorDepth", {})
            self._rows["colorDepth"].set_supported(cd.get("supported", False))
            if cd.get("supported"):
                self._rows["colorDepth"].set_value(cd.get("value", 0))
            pf = state.get("pixelFormat", {})
            self._rows["pixelFormat"].set_supported(pf.get("supported", False))
            if pf.get("supported"):
                self._rows["pixelFormat"].set_value(pf.get("value", 0))
            for channel in ("brightness", "contrast", "saturation", "hue", "temperature"):
                cstate = state.get("customColor", {}).get(channel, {})
                supported = cstate.get("supported", False)
                widget = self._rows[f"color_{channel}"]
                widget.set_supported(supported)
                if supported:
                    r = cstate.get("range", {})
                    widget.configure_range(r.get("min", -100), max(r.get("max", 100), r.get("min", -100) + 1),
                                           max(1, r.get("step", 1)))
                    widget.set(cstate.get("value", 0))
        finally:
            self._applying = False

    def _set(self, feature: str, **kwargs) -> None:
        if getattr(self, "_applying", False):
            return
        try:
            self.state.bridge.display_set(self._index, feature, **kwargs)
            self.state.log(f"display[{self._index}] {feature}: "
                           f"{', '.join(f'{k}={v}' for k, v in kwargs.items())}", "volt")
        except BridgeError as exc:
            self.state.log(f"{feature} failed: {exc}", "error")

    def _set_color(self, channel: str, value: int) -> None:
        self._set("customColor", **{channel: value})
