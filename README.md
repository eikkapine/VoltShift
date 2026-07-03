<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1017,45:2f81f7,100:19d3a2&height=220&section=header&text=%E2%9A%A1%20VoltShift&fontSize=72&fontColor=e6ecf5&fontAlignY=38&desc=Dynamic%20Voltage%20Control%20%2B%20Full%20Tuning%20Suite%20for%20AMD%20Radeon&descAlignY=58&descSize=18&descColor=8a97ab&animation=fadeIn" width="100%"/>

# ⚡ VoltShift

**Dynamic GPU voltage control and a complete Radeon tuning suite for Windows — built on AMD's official ADLX SDK.**

*Shifts voltage live with core clock, and exposes the tuning, graphics, and display controls Adrenalin buries — through one persistent, capability-aware bridge.*

![Windows](https://img.shields.io/badge/Windows%2010%2F11-0078D6?style=for-the-badge&logo=windows&logoColor=white)
![AMD Radeon](https://img.shields.io/badge/AMD%20Radeon-ED1C24?style=for-the-badge&logo=amd&logoColor=white)
![Python](https://img.shields.io/badge/Python%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![C++17](https://img.shields.io/badge/C%2B%2B%2017-00599C?style=for-the-badge&logo=cplusplus&logoColor=white)
![ADLX](https://img.shields.io/badge/AMD%20ADLX%20SDK-ED1C24?style=for-the-badge&logo=amd&logoColor=white)
![License](https://img.shields.io/badge/MIT-19d3a2?style=for-the-badge)

</div>

---

## 📖 Contents

| | | |
|:---|:---|:---|
| [What is VoltShift?](#-what-is-voltshift) | [Why it exists](#-why-does-this-exist) | [Architecture](#-architecture) |
| [Feature matrix](#-feature-matrix) | [Prerequisites](#-prerequisites) | [Build guide](#-build-guide) |
| [Using the GUI](#-using-the-gui) | [Using the CLI](#-using-the-cli) | [Dynamic voltage engine](#-dynamic-voltage-engine) |
| [Bridge protocol](#-bridge-protocol) | [Crash logger](#-crash-logger) | [Safety](#-safety) |

---

## 🔍 What is VoltShift?

VoltShift is a Windows control suite for AMD Radeon GPUs. Its signature feature is a
**dynamic voltage engine**: it reads the live core clock and applies a *different* voltage
offset for each clock range, adapting in real time with hysteresis to prevent flicker —
something Adrenalin's single static slider can't do.

Around that engine it wraps a full tuning suite over AMD's official **ADLX SDK**: manual
clocks, VRAM, power limit, fan curves, the 3D driver settings (Anti-Lag, Chill, RSR, AFMF,
FSR, image sharpening, FRTC, tessellation, AA/AF…), per-display settings (FreeSync, VSR,
scaling, color depth, custom color), multimedia video processing, profiles, per-app boost,
and a crash flight-recorder.

```
   Core clock          VoltShift applied offset
   ─────────────────────────────────────────────
   >= 3200 MHz  ->   -120 mV   (peak boost — conservative)
   >= 3100 MHz  ->   -160 mV   (high sustained — aggressive)
   >= 3000 MHz  ->   -140 mV   (mid boost — balanced)
   <  3000 MHz  ->   -100 mV   (idle / low load)
```

---

## 💡 Why Does This Exist?

Adrenalin exposes a **single global voltage offset** — set once, applied everywhere. Set it
conservatively and you leave savings on the table at mid clocks; set it aggressively and the
GPU crashes at peak boost when it needs voltage most. There's no per-clock-range middle
ground.

VoltShift fills that gap and then keeps going: everything Adrenalin *does* expose through
ADLX — tuning, fan curves, 3D settings, display settings — is surfaced in one keyboard-and-
mouse app, with a scriptable CLI on the same engine.

> VoltShift began as **ClawVolt** (the dynamic voltage engine) and grew into a full suite.
> Its feature scope is inspired by [dumbie/RadeonTuner](https://github.com/dumbie/RadeonTuner),
> reimplemented from scratch on an original three-layer architecture using **only official
> ADLX** — no undocumented driver registry pokes.

---

## 🏗 Architecture

```
┌───────────────────────────────┐   ┌──────────────────────────┐
│ GUI  (CustomTkinter)          │   │ CLI  (argparse)          │
│ sidebar pages · live graphs   │   │ run/info/tune/gfx/…      │
└──────────────┬────────────────┘   └───────────┬──────────────┘
               └────────────┬───────────────────┘
                   src/voltshift/  (Python 3.12 package)
   engine.py   dynamic clock->voltage state machine (thresholds + hysteresis)
   bridge…     persistent bridge client — thread-safe JSON lines, auto-restart
   runner.py   shared polling loop feeding engine + crash logger
   profiles.py versioned JSON snapshots of every tunable section
   crashlog.py flight recorder + Event Log post-mortem
   appboost.py per-app tuning boost (psutil watcher)
                             │ stdin/stdout, line-delimited JSON
                             ▼
              bridge/  →  voltshift_bridge.exe   (C++17, ONE process, ADLX init once)
   session · metrics · tuning · gfx · display · extras
                             │ amdadlx64.dll (ships with Adrenalin)
                             ▼
                        AMD Radeon GPU
```

**Why a persistent bridge?** ADLX is a native C++ SDK Python can't call directly. The old
approach spawned a process *per command* and re-initialised ADLX every time (~100 s of ms).
VoltShift's bridge holds one ADLX session and answers line-delimited JSON commands in
sub-millisecond time, so high-frequency polling is cheap.

**Why capability-driven?** The bridge reports per-feature `supported` flags. The UI grays out
what your GPU/driver can't do instead of assuming a specific card.

---

## ✨ Feature Matrix

| Area | Details |
|:---|:---|
| ⚡ **Dynamic voltage engine** | N clock/voltage thresholds, hysteresis, live graph with threshold lines |
| 🎛 **Manual tuning** | Voltage offset, core min/max clock, VRAM max clock + memory timing, power limit, TDC |
| 🌀 **Fan control** | 5-point curve editor, ZeroRPM, min/target fan speed |
| 📊 **Live metrics** | Clock, VRAM clock, temp, hotspot, board power, fan RPM, voltage, load |
| 🎮 **3D settings** | Anti-Lag(+Next), Chill, Boost, RIS + desktop sharpening, RSR, AFMF, FSR & frame-gen upgrade, Enhanced Sync, VSync mode, FRTC, tessellation, AA, AF |
| 🖥 **Per-display** | FreeSync, VSR, GPU/integer scaling, scaling mode, color depth, pixel format, custom color (brightness/contrast/saturation/hue/temp), HDCP |
| 🎞 **Multimedia** | Video upscale + sharpness, video super resolution |
| 🧩 **Desktop** | Simple Eyefinity create/destroy, desktop enumeration |
| 🚀 **App boost** | Auto-apply a power/clock boost while chosen games run, restore on exit |
| 💾 **Profiles** | Versioned JSON snapshots of every section; apply skips unsupported settings |
| 🪵 **Crash logger** | Flight recorder + Windows Event Log post-mortem, 7-code classification |

> Out of scope by design: undocumented driver registry hacks, driver install/update, and
> ADL-only features with no ADLX path.

---

## 📋 Prerequisites

| Requirement | Notes |
|:---|:---|
| **Windows 10/11 (64-bit)** | — |
| **AMD Radeon GPU** | RDNA2+ recommended; features gate on what ADLX reports for your card |
| **AMD Adrenalin driver** | Installs `amdadlx64.dll` (the ADLX runtime) automatically |
| **Python 3.12** | 3.14+ breaks PyInstaller exe builds — use 3.12 |
| **Visual Studio 2022 Build Tools** | "Desktop development with C++" workload (to build the bridge) |
| **CMake 3.16+** and **Git** | To build the bridge and fetch the ADLX SDK |
| **Administrator rights** | Required for voltage/tuning writes |

---

## 🔧 Build Guide

### 1 — Build the C++ bridge

From a normal terminal at the repo root:

```
scripts\build_bridge.bat
```

This clones the ADLX SDK into `third_party\ADLX` (headers only — the runtime ships with
Adrenalin) and builds `bridge\build\Release\voltshift_bridge.exe`. Verify (as Administrator):

```
bridge\build\Release\voltshift_bridge.exe info
```

<details>
<summary>Manual build (if you prefer)</summary>

```
git clone --depth 1 https://github.com/GPUOpen-LibrariesAndSDKs/ADLX third_party\ADLX
cd bridge
cmake -B build -A x64
cmake --build build --config Release
```
</details>

### 2 — Install Python dependencies

```
py -3.12 -m pip install -r requirements.txt
```

### 3 — Run VoltShift

> **Run your terminal as Administrator** — tuning writes require elevation.

**GUI (recommended):**
```
py -3.12 src\voltshift_gui.py
```

**CLI:**
```
py -3.12 -m voltshift --help
```
*(run from `src\`, or add `src` to `PYTHONPATH`)*

### Optional — standalone .exe

```
build\build_exe_py312.bat
```

Produces `build\dist\VoltShift\VoltShift.exe` (bridge bundled, UAC-elevated). Right-click →
**Run as Administrator**.

---

## 🖥 Using the GUI

A dark sidebar app with an always-live metrics strip along the top:

- **Dashboard** — stat tiles + scrolling clock/temp/power graphs
- **Dynamic Voltage** — threshold editor, engine start/stop, live graph with threshold lines
- **Tuning** — voltage/clock/VRAM/power sliders, ranges pulled live from the GPU
- **Fans** — curve editor + ZeroRPM
- **Graphics** — every supported 3D driver setting
- **Display** — per-monitor settings
- **App Boost** — watch a list of games and boost while they run
- **Profiles** — save/apply full-state snapshots
- **Logs** — live session log + crash-log access
- **About** — GPU details and safety notes

Unsupported controls are disabled automatically based on the bridge's capability report.

---

## 🚀 Using the CLI

```
py -3.12 -m voltshift info               # GPU + capability summary
py -3.12 -m voltshift metrics -w         # live metrics (watch)
py -3.12 -m voltshift run                # dynamic voltage engine (Ctrl+C = stop + reset)
py -3.12 -m voltshift tune voltage -120  # apply a voltage offset
py -3.12 -m voltshift tune fancurve 30:20 50:35 70:60 85:80 95:100
py -3.12 -m voltshift gfx set chill '{"enabled":true,"minFps":90,"maxFps":144}'
py -3.12 -m voltshift display list
py -3.12 -m voltshift profile save "quiet"
py -3.12 -m voltshift reset              # restore AMD factory tuning
```

---

## 📈 Dynamic Voltage Engine

Thresholds are evaluated **highest clock first**; the first one the reading meets wins. Below
all thresholds the idle offset applies. Hysteresis requires N consecutive polls before a new
offset commits, so a clock hovering on a boundary doesn't cause voltage flicker.

```json
{
  "engine": {
    "poll_interval_sec": 0.5,
    "hysteresis_count": 2,
    "idle_offset_mv": -100,
    "thresholds": [
      { "clock_mhz": 3200, "offset_mv": -120 },
      { "clock_mhz": 3100, "offset_mv": -160 },
      { "clock_mhz": 3000, "offset_mv": -140 }
    ]
  }
}
```

Saved to `voltshift_config.json` next to the app. **Tuning method:** start at -80 mV
everywhere, run a 20-minute stress test, lower one threshold 10 mV and repeat; on a crash,
raise that threshold 20 mV.

---

## 🔌 Bridge Protocol

One JSON object per line, `id` echoed back. Failures are responses, never crashes.

```
→ {"id":1,"cmd":"metrics"}
← {"id":1,"ok":true,"data":{"clockMhz":3142,"tempC":62,"boardPowerW":214,...}}
→ {"id":2,"cmd":"tuning.setVoltageOffset","args":{"mv":-120}}
← {"id":2,"ok":true,"data":{"appliedMv":-120,"interface":"MGT2_1"}}
```

Command groups: `ping/info/caps/metrics`, `tuning.*`, `gfx.*`, `display.*`, `media.*`,
`desktop.*`. A one-shot debug form also works: `voltshift_bridge.exe metrics`.

---

## 🪵 Crash Logger

When a GPU TDR fires, Windows kills every process with a GPU context — including VoltShift —
so no in-process watcher can catch the moment. VoltShift instead writes telemetry to disk
every poll (`voltshift_telemetry.json`) and leaves a heartbeat file. On the next launch a
leftover heartbeat means the last session crashed; VoltShift queries the Windows Event Log
for TDR/crash events and reconstructs a report from the saved telemetry into
`voltshift_crashes.log`, classified into one of seven reason codes with recommendations.

The crash logger is **read-only** — it never writes GPU state.

---

## 🛡 Safety

| Protection | How |
|:---|:---|
| 🚫 **No overvolt** | Positive voltage offsets are rejected in both the engine and the bridge |
| 📐 **Range clamped** | Every write is clamped to the ADLX-reported hardware range |
| 🔄 **Restores on exit** | Stopping the engine, closing the GUI, or Ctrl+C calls `ResetToFactory` |
| 📖 **Read-only crash logger** | Only reads the Event Log and telemetry |
| 🧱 **Daemon never dies on error** | Command failures are error responses, not crashes |

> If a crash leaves settings applied: **Adrenalin → Performance → Tuning → Reset**.

---

## 📄 License

MIT — free to use, modify, and distribute. The [ADLX SDK](https://github.com/GPUOpen-LibrariesAndSDKs/ADLX)
is distributed under AMD's own open-source license.

<div align="center">

*Built on AMD ADLX · Python 3.12 · C++17 · Not affiliated with or endorsed by AMD*

</div>
