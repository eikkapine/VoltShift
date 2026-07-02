"""Profile store — versioned JSON snapshots of every tunable section.

A profile captures the dynamic voltage engine config plus manual tuning,
fan, graphics, display, and multimedia settings. Sections are optional so a
profile can carry just the parts the user cares about; apply() skips
anything the GPU/driver rejects and reports what happened.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from . import APP_NAME, __version__, paths
from .bridgeclient import BridgeClient, BridgeError
from .engine import EngineConfig

PROFILE_FORMAT = 2  # format 1 was ClawVolt's flat threshold config


def _capture_gfx(bridge: BridgeClient) -> dict:
    """Reduce gfx.get output to just the writable state (drop ranges/support)."""
    captured = {}
    for feature, state in bridge.gfx_get().items():
        if not state.get("supported"):
            continue
        keep = {k: v for k, v in state.items()
                if k in ("enabled", "sharpness", "minFps", "maxFps", "minResolutionPct",
                         "fps", "mode", "level", "method", "ratio", "searchMode",
                         "performanceMode", "fastMotionResponse", "algorithm")}
        if keep:
            captured[feature] = keep
    return captured


def _capture_displays(bridge: BridgeClient) -> list[dict]:
    captured = []
    for display in bridge.display_list():
        index = display["index"]
        state = bridge.display_get(index)
        entry: dict = {"uniqueId": display.get("uniqueId"), "name": display.get("name")}
        for feature in ("freeSync", "vsr", "gpuScaling", "integerScaling", "variBright", "hdcp"):
            if state.get(feature, {}).get("supported"):
                entry[feature] = {"enabled": state[feature]["enabled"]}
        if state.get("scalingMode", {}).get("supported"):
            entry["scalingMode"] = {"mode": state["scalingMode"]["mode"]}
        if state.get("colorDepth", {}).get("supported"):
            entry["colorDepth"] = {"value": state["colorDepth"]["value"]}
        if state.get("pixelFormat", {}).get("supported"):
            entry["pixelFormat"] = {"value": state["pixelFormat"]["value"]}
        color = {}
        for channel, cstate in state.get("customColor", {}).items():
            if cstate.get("supported"):
                color[channel] = cstate["value"]
        if color:
            entry["customColor"] = color
        captured.append(entry)
    return captured


def capture(bridge: BridgeClient, engine_config: EngineConfig,
            sections: Optional[set[str]] = None) -> dict:
    """Snapshot current state into a profile dict."""
    sections = sections or {"engine", "tuning", "fans", "gfx", "display", "media"}
    profile: dict = {
        "app": APP_NAME,
        "appVersion": __version__,
        "format": PROFILE_FORMAT,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gpu": bridge.info().get("name", "unknown"),
    }

    if "engine" in sections:
        profile["engine"] = engine_config.to_dict()

    if "tuning" in sections:
        tuning = bridge.tuning_get()
        section: dict = {}
        gfx = tuning.get("gfx", {})
        if "unsupported" not in gfx:
            if "voltageMv" in gfx:
                section["voltageMv"] = gfx["voltageMv"]
            if "minFreqMhz" in gfx:
                section["minFreqMhz"] = gfx["minFreqMhz"]
            if "maxFreqMhz" in gfx:
                section["maxFreqMhz"] = gfx["maxFreqMhz"]
        vram = tuning.get("vram", {})
        if "unsupported" not in vram:
            if "maxFreqMhz" in vram:
                section["vramMaxMhz"] = vram["maxFreqMhz"]
            if vram.get("timingSupported"):
                section["memoryTiming"] = vram.get("timing")
        power = tuning.get("power", {})
        if "unsupported" not in power:
            if "powerLimit" in power:
                section["powerLimitPct"] = power["powerLimit"]
            if power.get("tdcSupported"):
                section["tdcAmps"] = power.get("tdcLimit")
        profile["tuning"] = section

    if "fans" in sections:
        try:
            fans = bridge.fans_get()
            section = {"curve": fans.get("curve", [])}
            if fans.get("zeroRpmSupported"):
                section["zeroRpm"] = fans.get("zeroRpm")
            profile["fans"] = section
        except BridgeError:
            pass

    if "gfx" in sections:
        profile["gfx"] = _capture_gfx(bridge)

    if "display" in sections:
        profile["display"] = _capture_displays(bridge)

    if "media" in sections:
        media = bridge.media_get()
        section = {}
        for feature in ("videoUpscale", "videoSuperResolution"):
            state = media.get(feature, {})
            if state.get("supported"):
                keep = {k: v for k, v in state.items() if k in ("enabled", "sharpness")}
                section[feature] = keep
        profile["media"] = section

    return profile


def apply(bridge: BridgeClient, profile: dict) -> list[str]:
    """Apply a profile; returns a log of what was applied or skipped."""
    if profile.get("format") != PROFILE_FORMAT:
        raise ValueError(f"Unsupported profile format: {profile.get('format')!r}")

    log: list[str] = []

    def attempt(label: str, fn, *args, **kwargs) -> None:
        try:
            fn(*args, **kwargs)
            log.append(f"applied: {label}")
        except BridgeError as exc:
            log.append(f"skipped: {label} ({exc})")

    tuning = profile.get("tuning", {})
    if "voltageMv" in tuning:
        attempt("voltage offset", bridge.set_voltage_offset, tuning["voltageMv"])
    if "minFreqMhz" in tuning or "maxFreqMhz" in tuning:
        attempt("core clocks", bridge.set_core_clocks,
                tuning.get("minFreqMhz"), tuning.get("maxFreqMhz"))
    if "vramMaxMhz" in tuning:
        attempt("VRAM max clock", bridge.set_vram_max, tuning["vramMaxMhz"])
    if tuning.get("memoryTiming") is not None:
        attempt("memory timing", bridge.set_memory_timing, tuning["memoryTiming"])
    if "powerLimitPct" in tuning:
        attempt("power limit", bridge.set_power_limit, tuning["powerLimitPct"])
    if tuning.get("tdcAmps") is not None:
        attempt("TDC limit", bridge.set_tdc, tuning["tdcAmps"])

    fans = profile.get("fans", {})
    if fans.get("curve"):
        attempt("fan curve", bridge.set_fan_curve, fans["curve"])
    if fans.get("zeroRpm") is not None:
        attempt("ZeroRPM", bridge.set_zero_rpm, fans["zeroRpm"])

    for feature, state in profile.get("gfx", {}).items():
        attempt(f"gfx {feature}", bridge.gfx_set, feature, **state)

    # Displays are matched by uniqueId so a re-cabled monitor still gets its
    # settings; unmatched saved displays are reported and skipped.
    current = {d.get("uniqueId"): d["index"] for d in bridge.display_list()}
    for saved in profile.get("display", []):
        index = current.get(saved.get("uniqueId"))
        label = saved.get("name", "display")
        if index is None:
            log.append(f"skipped: display '{label}' not connected")
            continue
        for feature in ("freeSync", "vsr", "gpuScaling", "integerScaling", "variBright", "hdcp"):
            if feature in saved:
                attempt(f"{label} {feature}", bridge.display_set, index, feature,
                        enabled=saved[feature]["enabled"])
        if "scalingMode" in saved:
            attempt(f"{label} scaling mode", bridge.display_set, index, "scalingMode",
                    mode=saved["scalingMode"]["mode"])
        if "colorDepth" in saved:
            attempt(f"{label} color depth", bridge.display_set, index, "colorDepth",
                    value=saved["colorDepth"]["value"])
        if "pixelFormat" in saved:
            attempt(f"{label} pixel format", bridge.display_set, index, "pixelFormat",
                    value=saved["pixelFormat"]["value"])
        if saved.get("customColor"):
            attempt(f"{label} custom color", bridge.display_set, index, "customColor",
                    **saved["customColor"])

    for feature, state in profile.get("media", {}).items():
        attempt(f"media {feature}", bridge.media_set, feature, **state)

    return log


# ── file I/O ──────────────────────────────────────────────────────────────────

def save(profile: dict, name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "profile"
    path = os.path.join(paths.profiles_dir(), f"{safe}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    return path


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_profiles() -> list[str]:
    directory = paths.profiles_dir()
    return sorted(
        os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".json")
    )
