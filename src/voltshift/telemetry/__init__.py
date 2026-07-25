"""Telemetry: one fused stream of GPU counters and frame-pacing statistics."""

from .frames import (FrameSource, NullFrameSource, PresentMonSource,
                     RtssFrameSource, detect_frame_source, find_presentmon)
from .hub import TelemetryHub
from .sample import FrameStats, Sample
from .window import PairedDelta, WindowStats, paired_delta, relative_paired_delta

__all__ = [
    "FrameSource", "NullFrameSource", "PresentMonSource", "RtssFrameSource",
    "detect_frame_source", "find_presentmon",
    "TelemetryHub", "FrameStats", "Sample",
    "WindowStats", "PairedDelta", "paired_delta", "relative_paired_delta",
]
