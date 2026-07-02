# VoltShift — Overhaul Design (2026-07-02)

## Summary

ClawVolt becomes **VoltShift**: a full AMD Radeon control suite for Windows built around
ClawVolt's unique dynamic clock→voltage engine, expanded to cover every functional area of
dumbie/RadeonTuner — reimplemented from scratch on our own architecture, not ported.

## Why not a 1:1 RadeonTuner port

RadeonTuner is a C++/WinRT XAML monolith (~100 headers compiled into one MainPage) that mixes
official ADLX calls with undocumented AMD driver **registry pokes** (FSR DLL swaps, MFG/NRC/MLD
overrides). Those keys break across driver versions and porting them would be a clone.

VoltShift instead:

- **Official ADLX API only.** Every feature goes through AMD's supported SDK. Anything the
  driver doesn't expose via ADLX is out of scope by design.
- **Three-layer architecture** (bridge daemon / Python core / GUI-CLI) instead of a UI monolith.
- **Capability-driven UI.** The bridge reports per-feature `supported` flags; the UI grays out
  what the GPU/driver can't do instead of assuming an RX 9070 XT.

## Architecture

```
┌───────────────────────────────┐  ┌──────────────────────────┐
│ GUI (CustomTkinter)           │  │ CLI (argparse)           │
│ sidebar pages, live graphs    │  │ run/info/tune/profile    │
└──────────────┬────────────────┘  └───────────┬──────────────┘
               └────────────┬──────────────────┘
                    src/voltshift/  (Python 3.12 package)
   engine.py      dynamic voltage state machine (thresholds + hysteresis)
   bridge.py      persistent bridge client — JSON lines, thread-safe, auto-restart
   profiles.py    versioned JSON profiles (all sections)
   crashlog.py    flight recorder + Event Log post-mortem (ported from ClawVolt)
   appboost.py    per-app tuning boost (psutil process watcher)
                             │ stdin/stdout, line-delimited JSON
                             ▼
              bridge/  →  voltshift_bridge.exe  (C++17, one process, ADLX init once)
   main.cpp      REPL: {"id":N,"cmd":"...","args":{...}} → {"id":N,"ok":true,"data":{...}}
   session.*     ADLX lifetime, GPU + display enumeration
   metrics.*     performance monitoring
   tuning.*      manual GFX voltage / core clocks / VRAM / power / fan curve
   graphics.*    3D settings (Anti-Lag, Chill, Boost, RIS, RSR, AFMF, FRTC, …)
   display.*     per-display settings (FreeSync, VSR, scaling, custom color, …)
   extras.*      multimedia video upscale, simple Eyefinity, shader-cache reset
                             │ amdadlx64.dll (ships with Adrenalin)
                             ▼
                        AMD Radeon GPU
```

Old bridge spawned a process **per call** (full ADLX init/terminate each time, ~100s of ms).
The daemon holds one session: sub-ms command dispatch, high-frequency polling becomes cheap.

## Bridge protocol

One JSON object per line, UTF-8, `id` echoed back:

```
→ {"id":1,"cmd":"metrics"}
← {"id":1,"ok":true,"data":{"clockMhz":3142,"tempC":62,"hotspotC":78,"powerW":214,...}}
→ {"id":2,"cmd":"tuning.setVoltage","args":{"mv":-120}}
← {"id":2,"ok":true,"data":{"appliedMv":-120,"interface":"MGT2_1"}}
← {"id":3,"ok":false,"error":"NOT_SUPPORTED: ..."}   (failures never crash the daemon)
```

Command groups: `ping/info/caps`, `metrics`, `tuning.*`, `gfx.*`, `display.*`, `media.*`,
`desktop.*`, `reset.*`.

## Feature scope (vs RadeonTuner)

| Area | RadeonTuner | VoltShift |
|---|---|---|
| Dynamic clock→voltage engine | — | ✔ (identity feature, kept + unit-tested) |
| Crash flight recorder + post-mortem | — | ✔ (ported) |
| Manual tuning: voltage, core min/max, VRAM max+timing, power limit, TDC | ✔ | ✔ ADLX |
| Fan curve 5-pt + ZeroRPM | ✔ | ✔ ADLX |
| Live metrics | ✔ | ✔ ADLX |
| 3D: Anti-Lag, Chill, Boost, RIS, Enhanced Sync, VSync, FRTC, Tessellation, AA/AF, RSR, AFMF | ✔ (mixed ADLX/registry) | ✔ ADLX-official subset |
| FSR/MFG DLL + registry overrides | ✔ (registry hacks) | ✘ by design |
| Display: FreeSync, VSR, GPU/integer scaling, color depth, pixel format, custom color | ✔ | ✔ ADLX |
| CVDC color-blindness correction | ✔ (ADL) | ✘ (no ADLX path) |
| Multimedia video upscale / VSR video | ✔ | ✔ ADLX (driver ≥ 3.0) |
| Eyefinity | ✔ (ADL) | ✔ ADLX simple Eyefinity |
| Per-app PowerBoost | ✔ | ✔ Python watcher (appboost) |
| Profiles import/export | ✔ | ✔ versioned JSON, all sections |
| Shader cache reset | ✔ | ✔ ADLX |
| Driver updater / installer | ✔ | ✘ out of scope |

## Safety rules (unchanged from ClawVolt, enforced in bridge)

1. Positive voltage offsets rejected.
2. Every write clamped to the ADLX-reported hardware range.
3. Engine stop / GUI close / Ctrl+C → `ResetToFactory`.
4. Crash logger is read-only.
5. Daemon never exits on command failure — errors are responses, not crashes.

## Rename plan

`ClawVolt` → `VoltShift`, `claw_volt_*` → `voltshift_*` (files, classes, window titles, banners,
config keys, log/telemetry/heartbeat filenames, PyInstaller spec, bat, issue templates, README,
GitHub repo via `gh repo rename`). Verification: case-insensitive grep for `claw` must return
zero hits outside `.git/` and this paragraph.

## Testing

- Python unit tests (pytest): engine threshold/hysteresis logic, protocol framing, profile
  round-trip, crash classification.
- Live smoke on this machine (RX 9070 XT): daemon `info/caps/metrics` real values.
- Destructive writes (voltage/fan/power) validated for plumbing + supported-flags; actual
  tuning stress-testing stays with the user.

## Out of scope

Driver registry hacks, driver install/update, ADL-only features (CVDC), Linux.
