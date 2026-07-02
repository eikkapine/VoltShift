"""Human-readable names for the raw ADLX enum ints the bridge passes through.

Values mirror ADLXDefines.h in the ADLX SDK; the bridge does no translation
so these tables are the single place names live.
"""

from __future__ import annotations

VSYNC_MODES = {
    0: "Always off",
    1: "Off, unless app specifies",
    2: "On, unless app specifies",
    3: "Always on",
}

ANTILAG_LEVELS = {
    0: "Anti-Lag",
    1: "Anti-Lag Next",
}

SCALING_MODES = {
    0: "Preserve aspect ratio",
    1: "Full panel",
    2: "Centered",
}

COLOR_DEPTHS = {
    0: "Unknown",
    1: "6 bpc",
    2: "8 bpc",
    3: "10 bpc",
    4: "12 bpc",
    5: "14 bpc",
    6: "16 bpc",
}

PIXEL_FORMATS = {
    0: "Unknown",
    1: "RGB 4:4:4 Full",
    2: "YCbCr 4:4:4",
    3: "YCbCr 4:2:2",
    4: "RGB 4:4:4 Limited",
    5: "YCbCr 4:2:0",
}

MEMORY_TIMINGS = {
    0: "Default",
    1: "Fast timing",
    2: "Fast timing level 2",
    3: "Automatic",
    4: "Timing level 1",
    5: "Timing level 2",
}

TESSELLATION_MODES = {
    0: "AMD optimized",
    1: "Use application settings",
    2: "Override application settings",
}

TESSELLATION_LEVELS = {
    1: "Off",
    2: "2x",
    4: "4x",
    6: "6x",
    8: "8x",
    16: "16x",
    32: "32x",
    64: "64x",
}

ANISOTROPIC_LEVELS = {
    0: "Invalid",
    2: "2x",
    4: "4x",
    8: "8x",
    16: "16x",
}

AA_MODES = {
    0: "Use application settings",
    1: "Enhance application settings",
    2: "Override application settings",
}

AA_METHODS = {
    0: "Multisampling",
    1: "Adaptive multisampling",
    2: "Supersampling",
}

AA_LEVELS = {
    0: "Invalid",
    2: "2x",
    3: "2xEQ",
    4: "4x",
    5: "4xEQ",
    8: "8x",
    9: "8xEQ",
}

DESKTOP_TYPES = {
    0: "Single",
    1: "Duplicate",
    2: "Eyefinity",
}

CONNECTOR_TYPES = {
    0: "Unknown",
    1: "VGA",
    2: "DVI-D",
    3: "DVI-I",
    4: "CV dongle (NTSC)",
    5: "CV dongle (JPN)",
    6: "CV dongle (non-I2C JPN)",
    7: "CV dongle (non-I2C NTSC)",
    8: "Proprietary",
    9: "HDMI Type A",
    10: "HDMI Type B",
    11: "S-Video",
    12: "Composite",
    13: "DisplayPort",
    14: "eDP",
    15: "Wireless display",
}

FFX_FRAME_GEN_RATIOS = {
    0: "Unknown",
    1: "2x",
}


def name(table: dict[int, str], value, default: str = "?") -> str:
    if value is None:
        return default
    return table.get(int(value), f"{default} ({value})")
