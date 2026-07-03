"""Graphics — AMD 3D driver settings via ADLX.

Each feature the bridge reports gets a toggle; features with extra
parameters (sharpness, FPS bounds, modes) also expose a slider or choice.
Unsupported features are shown disabled so the page reflects the real
capabilities of the installed driver, not an assumed feature set.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import theme
from ..widgets import Card, ChoiceRow, LabeledSlider, ToggleRow
from ...adlxenums import (
    AA_LEVELS,
    AA_METHODS,
    AA_MODES,
    ANISOTROPIC_LEVELS,
    ANTILAG_LEVELS,
    FFX_FRAME_GEN_RATIOS,
    TESSELLATION_LEVELS,
    TESSELLATION_MODES,
    VSYNC_MODES,
)
from ...bridgeclient import BridgeError
from .base import Page


class GraphicsPage(Page):
    title = "Graphics"

    # Simple on/off features: (json key, label, description).
    _TOGGLES = [
        ("enhancedSync", "Enhanced Sync", "Tear-free without added latency"),
        ("morphologicalAA", "Morphological AA", "Post-process anti-aliasing"),
        ("imageSharpenDesktop", "Desktop sharpening", "Sharpen the whole desktop"),
        ("fsrUpgrade", "FSR upgrade", "Auto-upgrade FSR where supported"),
    ]

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self._rows: dict[str, object] = {}

        upscale = Card(self, title="Upscaling & frame generation")
        upscale.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ub = upscale.body()
        ub.grid_columnconfigure(0, weight=1)
        self._rows["rsr"] = ToggleRow(ub, "Radeon Super Resolution",
                                      lambda v: self._set("rsr", enabled=v),
                                      "Driver-level upscaling for fullscreen games")
        self._rows["rsr"].grid(row=0, column=0, sticky="ew")
        self._rows["rsr_sharp"] = LabeledSlider(ub, "RSR sharpness", 0, 100, 1, "%",
                                                lambda v: self._set("rsr", sharpness=v))
        self._rows["rsr_sharp"].grid(row=1, column=0, sticky="ew")
        self._rows["imageSharpening"] = ToggleRow(
            ub, "Radeon Image Sharpening", lambda v: self._set("imageSharpening", enabled=v),
            "Contrast-adaptive sharpening in games")
        self._rows["imageSharpening"].grid(row=2, column=0, sticky="ew")
        self._rows["ris_sharp"] = LabeledSlider(ub, "RIS sharpness", 0, 100, 1, "%",
                                                lambda v: self._set("imageSharpening", sharpness=v))
        self._rows["ris_sharp"].grid(row=3, column=0, sticky="ew")
        self._rows["afmf"] = ToggleRow(ub, "AMD Fluid Motion Frames",
                                       lambda v: self._set("afmf", enabled=v),
                                       "Driver-level frame generation")
        self._rows["afmf"].grid(row=4, column=0, sticky="ew")
        self._rows["frameGenUpgrade"] = ToggleRow(
            ub, "Frame-gen upgrade", lambda v: self._set("frameGenUpgrade", enabled=v),
            "Auto-upgrade in-game frame generation")
        self._rows["frameGenUpgrade"].grid(row=5, column=0, sticky="ew")
        self._rows["framegen_ratio"] = ChoiceRow(
            ub, "Frame-gen ratio", FFX_FRAME_GEN_RATIOS,
            lambda v: self._set("frameGenUpgrade", ratio=v))
        self._rows["framegen_ratio"].grid(row=6, column=0, sticky="ew")

        latency = Card(self, title="Latency & frame pacing")
        latency.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        lb = latency.body()
        lb.grid_columnconfigure(0, weight=1)
        self._rows["antiLag"] = ToggleRow(lb, "Anti-Lag",
                                          lambda v: self._set("antiLag", enabled=v),
                                          "Reduce input-to-display latency")
        self._rows["antiLag"].grid(row=0, column=0, sticky="ew")
        self._rows["antilag_level"] = ChoiceRow(lb, "Anti-Lag level", ANTILAG_LEVELS,
                                                lambda v: self._set("antiLag", level=v))
        self._rows["antilag_level"].grid(row=1, column=0, sticky="ew")
        self._rows["chill"] = ToggleRow(lb, "Radeon Chill",
                                        lambda v: self._set("chill", enabled=v),
                                        "Dynamic FPS to cut power when idle-ish")
        self._rows["chill"].grid(row=2, column=0, sticky="ew")
        self._rows["chill_min"] = LabeledSlider(lb, "Chill min FPS", 30, 300, 1, "fps",
                                                lambda v: self._set("chill", minFps=v))
        self._rows["chill_min"].grid(row=3, column=0, sticky="ew")
        self._rows["chill_max"] = LabeledSlider(lb, "Chill max FPS", 30, 300, 1, "fps",
                                                lambda v: self._set("chill", maxFps=v))
        self._rows["chill_max"].grid(row=4, column=0, sticky="ew")
        self._rows["frtc"] = ToggleRow(lb, "Frame Rate Target Control",
                                       lambda v: self._set("frtc", enabled=v),
                                       "Cap the frame rate to save power/heat")
        self._rows["frtc"].grid(row=5, column=0, sticky="ew")
        self._rows["frtc_fps"] = LabeledSlider(lb, "FRTC target", 30, 300, 1, "fps",
                                               lambda v: self._set("frtc", fps=v))
        self._rows["frtc_fps"].grid(row=6, column=0, sticky="ew")
        self._rows["boost"] = ToggleRow(lb, "Radeon Boost",
                                        lambda v: self._set("boost", enabled=v),
                                        "Dynamic resolution during motion")
        self._rows["boost"].grid(row=7, column=0, sticky="ew")
        self._rows["vsync"] = ChoiceRow(lb, "Wait for VSync", VSYNC_MODES,
                                        lambda v: self._set("vsync", mode=v))
        self._rows["vsync"].grid(row=8, column=0, sticky="ew")

        quality = Card(self, title="Image quality")
        quality.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        qb = quality.body()
        qb.grid_columnconfigure(0, weight=1)
        self._rows["aa_mode"] = ChoiceRow(qb, "Anti-aliasing", AA_MODES,
                                          lambda v: self._set("antiAliasing", mode=v))
        self._rows["aa_mode"].grid(row=0, column=0, sticky="ew")
        self._rows["aa_level"] = ChoiceRow(qb, "AA level", AA_LEVELS,
                                           lambda v: self._set("antiAliasing", level=v))
        self._rows["aa_level"].grid(row=1, column=0, sticky="ew")
        self._rows["aa_method"] = ChoiceRow(qb, "AA method", AA_METHODS,
                                            lambda v: self._set("antiAliasing", method=v))
        self._rows["aa_method"].grid(row=2, column=0, sticky="ew")
        self._rows["anisotropicFiltering"] = ToggleRow(
            qb, "Anisotropic filtering", lambda v: self._set("anisotropicFiltering", enabled=v))
        self._rows["anisotropicFiltering"].grid(row=3, column=0, sticky="ew")
        self._rows["af_level"] = ChoiceRow(qb, "AF level", ANISOTROPIC_LEVELS,
                                           lambda v: self._set("anisotropicFiltering", level=v))
        self._rows["af_level"].grid(row=4, column=0, sticky="ew")
        self._rows["tess_mode"] = ChoiceRow(qb, "Tessellation", TESSELLATION_MODES,
                                            lambda v: self._set("tessellation", mode=v))
        self._rows["tess_mode"].grid(row=5, column=0, sticky="ew")
        self._rows["tess_level"] = ChoiceRow(qb, "Tess level", TESSELLATION_LEVELS,
                                             lambda v: self._set("tessellation", level=v))
        self._rows["tess_level"].grid(row=6, column=0, sticky="ew")

        misc = Card(self, title="Other")
        misc.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        mb = misc.body()
        mb.grid_columnconfigure(0, weight=1)
        for i, (key, label, desc) in enumerate(self._TOGGLES):
            row = ToggleRow(mb, label, lambda v, k=key: self._set(k, enabled=v), desc)
            row.grid(row=i, column=0, sticky="ew")
            self._rows[key] = row
        ctk.CTkButton(mb, text="Reset shader cache", fg_color=theme.SURFACE_2,
                      hover_color=theme.SURFACE_3, command=self._reset_shader
                      ).grid(row=len(self._TOGGLES), column=0, sticky="w", pady=(8, 0))

    def on_show(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        if not self.state.connected:
            return
        try:
            gfx = self.state.bridge.gfx_get()
        except BridgeError as exc:
            self.state.log(f"Graphics read failed: {exc}", "error")
            return
        self._applying = True  # suppress command callbacks during load
        try:
            self._apply_state(gfx)
        finally:
            self._applying = False

    def _apply_state(self, gfx: dict) -> None:
        def toggle(key: str, feature: str) -> None:
            state = gfx.get(feature, {})
            self._rows[key].set_state(state.get("enabled", False), state.get("supported", False))

        toggle("rsr", "rsr")
        toggle("imageSharpening", "imageSharpening")
        toggle("afmf", "afmf")
        toggle("frameGenUpgrade", "frameGenUpgrade")
        toggle("antiLag", "antiLag")
        toggle("chill", "chill")
        toggle("frtc", "frtc")
        toggle("boost", "boost")
        toggle("anisotropicFiltering", "anisotropicFiltering")
        for key, _label, _desc in self._TOGGLES:
            toggle(key, key)

        def slider(key: str, feature: str, field: str, range_field: str | None = None) -> None:
            state = gfx.get(feature, {})
            supported = state.get("supported", False)
            self._rows[key].set_supported(supported)
            if supported:
                if range_field and range_field in state:
                    r = state[range_field]
                    self._rows[key].configure_range(r.get("min", 0), max(r.get("max", 100), 1),
                                                    max(1, r.get("step", 1)))
                if field in state:
                    self._rows[key].set(state[field])

        slider("rsr_sharp", "rsr", "sharpness", "sharpnessRange")
        slider("ris_sharp", "imageSharpening", "sharpness", "sharpnessRange")
        slider("chill_min", "chill", "minFps", "fpsRange")
        slider("chill_max", "chill", "maxFps", "fpsRange")
        slider("frtc_fps", "frtc", "fps", "fpsRange")

        def choice(key: str, feature: str, field: str) -> None:
            state = gfx.get(feature, {})
            supported = state.get("supported", False)
            self._rows[key].set_supported(supported)
            if supported and field in state:
                self._rows[key].set_value(state[field])

        choice("antilag_level", "antiLag", "level")
        choice("framegen_ratio", "frameGenUpgrade", "ratio")
        choice("vsync", "vsync", "mode")
        choice("aa_mode", "antiAliasing", "mode")
        choice("aa_level", "antiAliasing", "level")
        choice("aa_method", "antiAliasing", "method")
        choice("af_level", "anisotropicFiltering", "level")
        choice("tess_mode", "tessellation", "mode")
        choice("tess_level", "tessellation", "level")

    def _set(self, feature: str, **kwargs) -> None:
        if getattr(self, "_applying", False):
            return
        try:
            self.state.bridge.gfx_set(feature, **kwargs)
            detail = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            self.state.log(f"{feature}: {detail}", "volt")
        except BridgeError as exc:
            self.state.log(f"{feature} failed: {exc}", "error")

    def _reset_shader(self) -> None:
        try:
            self.state.bridge.reset_shader_cache()
            self.state.log("Shader cache reset", "volt")
        except BridgeError as exc:
            self.state.log(f"Shader cache reset failed: {exc}", "error")
