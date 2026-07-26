<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1017,45:2f81f7,100:19d3a2&height=220&section=header&text=%E2%9A%A1%20VoltShift&fontSize=72&fontColor=e6ecf5&fontAlignY=38&desc=Self-Tuning%20Undervolt%20%2B%20Full%20Tuning%20Suite%20for%20AMD%20Radeon&descAlignY=58&descSize=18&descColor=8a97ab&animation=fadeIn" width="100%"/>

# ⚡ VoltShift

**A Radeon tuner that measures, learns, and tunes itself — built on AMD's official ADLX SDK.**

*Press one button and VoltShift finds the undervolt your card actually wants, proves it against real frame data, remembers it per game, and keeps adapting while you play.*

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
| [Auto-Tune](#-auto-tune--the-one-click-loop) | [Adaptive governor](#-adaptive-governor--tuning-while-you-play) | [How the optimiser works](#-how-the-optimiser-works) |
| [Benchmark mode](#-benchmark-mode--tuning-for-maximum-score) | [Per-GPU verification](#-per-gpu-control-verification) | [What it remembers](#-what-it-remembers) |
| [Frame data setup](#-frame-data-setup) | | |
| [Feature matrix](#-feature-matrix) | | |
| [Prerequisites](#-prerequisites) | [Build guide](#-build-guide) | [Using the GUI](#-using-the-gui) |
| [Using the CLI](#-using-the-cli) | [Dynamic voltage engine](#-dynamic-voltage-engine) | [Bridge protocol](#-bridge-protocol) |
| [Crash logger](#-crash-logger) | [Safety](#-safety) | [License](#-license) |

---

## 🔍 What is VoltShift?

Most undervolting is a manual ritual: pick an offset, run a benchmark, crash, back off, repeat
for an evening, then never touch it again. VoltShift closes that loop.

**Press Auto-Tune.** It measures what your card is doing right now — including real frame rate
and 1% lows, not just clocks and watts — proposes a configuration, applies it, measures again
against the previous settings, and keeps whichever won. After a dozen trials it commits the
best result and remembers it for that game.

**Turn on the Adaptive governor** and it does that continuously: recognises the game you
launched, applies what it learned, and spends a small, capped budget of experiments while you
play — reverting instantly at the first sign of instability.

Around that loop sits the full tuning suite from 1.x: manual clocks, VRAM, power limit, fan
curves, the 3D driver settings (Anti-Lag, Chill, RSR, AFMF, FSR, sharpening, FRTC…),
per-display settings, multimedia, profiles, per-app boost, and a crash flight-recorder.

```
   Trial 4    voltage_mv=-95   power_limit_pct=+6   →  +0.041   fps 1% low +3.8%, efficiency +5.1%
   Trial 5    voltage_mv=-140  power_limit_pct=+6   →  -10.00   rejected — 3 frametime spikes after the change
   Trial 6    voltage_mv=-110  power_limit_pct=+9   →  +0.067   fps 1% low +5.2%, efficiency +6.4%   ← best
```

---

## 💡 Why Does This Exist?

Adrenalin exposes a **single global voltage offset**, set once and applied everywhere, with no
feedback about whether it helped. You cannot see your 1% lows in it. It does not know which
game you are running. It has never heard of your specific card's silicon quality, and it
forgets everything the moment a driver update resets your profile.

VoltShift's answer:

- **Measure what matters.** Frame rate, 1% lows and stutter, joined to clocks, power and
  thermals — because an undervolt that holds clocks while dropping frames is a loss that no
  hardware counter will show you.
- **Prove every change.** Candidate and baseline settings are interleaved in short paired
  windows and compared as *differences*, so a game getting heavier mid-session cancels out
  instead of masquerading as a result.
- **Never forget a failure.** Anything that destabilises the card is recorded against that
  card permanently and constrains every future search, in every game.

> VoltShift began as **ClawVolt** (the dynamic voltage engine) and grew into a full suite.
> Its manual-tuning scope is inspired by [dumbie/RadeonTuner](https://github.com/dumbie/RadeonTuner),
> reimplemented from scratch on an original architecture using **only official ADLX** — no
> undocumented driver registry pokes.

---

## 🏗 Architecture

```
┌───────────────────────────────┐   ┌──────────────────────────┐
│ GUI  (CustomTkinter)          │   │ CLI  (argparse)          │
│ Auto-Tune · Adaptive · pages  │   │ autotune/adaptive/…      │
└──────────────┬────────────────┘   └───────────┬──────────────┘
               └────────────┬───────────────────┘
                   src/voltshift/  (Python 3.12 package)

   ── the closed loop ────────────────────────────────────────────────
   telemetry/    one poller: bridge counters + PresentMon/RTSS frames,
                 fused into a Sample stream with paired-window statistics
   optimizer/    search space from live ADLX ranges · goal presets ·
                 Gaussian-process + expected improvement · safeguard ·
                 the paired-trial session state machine
   stability.py  five fault signatures: TDR, spike train, clock cliff,
                 process death, hard hang
   watchdog.py   journal-before-write, last-known-good, boot recovery
   knowledge.py  SQLite: per-game bests, transfer priors, and the
                 per-silicon stability frontier
   adaptive.py   live governor: game detection, phase tagging, budgeted
                 in-game probes

   ── the suite ──────────────────────────────────────────────────────
   engine.py     dynamic clock->voltage state machine (thresholds + hysteresis)
   profiles.py   versioned JSON snapshots of every tunable section
   crashlog.py   flight recorder + Event Log post-mortem
   appboost.py   per-app tuning boost
                             │ stdin/stdout, line-delimited JSON
                             ▼
              bridge/  →  voltshift_bridge.exe   (C++17, ONE process, ADLX init once)
                             │ amdadlx64.dll (ships with Adrenalin)
                             ▼
                        AMD Radeon GPU
```

**Why a persistent bridge?** ADLX is a native C++ SDK Python can't call directly. Spawning a
process per command re-initialises ADLX every time (~100s of ms). VoltShift's bridge holds one
session and answers JSON lines in sub-millisecond time, so 2 Hz polling is free.

**Why one poller?** Telemetry is read once for the whole application and fanned out to the
dashboard, the voltage engine, the optimiser and the stability monitor. Nothing polls twice.

**Why capability-driven?** Every range in the search space comes from `tuning.get`, so the
optimiser physically cannot propose a value the driver would reject, on any card.

---

## 🎯 Auto-Tune — the one-click loop

Start your game, leave it on a normal scene, open **Auto-Tune**, pick a goal, press the button.

| Goal | Optimises for |
|:---|:---|
| **Max FPS** | Frame rate, especially 1% lows. Accepts the power and heat it costs. |
| **Balanced** | Frame rate first, without paying much power or heat for it. |
| **Efficiency** | Most frames per watt. Small frame-rate losses are acceptable. |
| **Silent & Cool** | Lowest heat and fan speed that keeps frame pacing intact. |

What happens per trial:

1. The optimiser proposes a configuration; the **safeguard** checks it against hardware
   bounds, per-step movement caps, the tabu set, and this card's learned stability frontier.
2. The configuration is **journalled to disk** before it is written, so a hang is attributed
   to it on the next launch rather than silently retried.
3. Candidate and baseline are measured in **alternating paired windows**.
4. The paired differences are scored under the chosen goal, weighted by how repeatable they
   were — a one-off 5% gain contributes almost nothing.
5. Any stability signal aborts the trial, reverts immediately, and records the failure.

At the end the winner is **re-measured before being committed**, because the best score of a
search is always an optimistic estimate. If it does not hold up, the baseline is restored and
VoltShift says so.

```
py -3.12 -m voltshift autotune --goal efficiency
py -3.12 -m voltshift autotune --goal max_fps --trials 20 --window 10
```

---

## 🏁 Benchmark mode — tuning for maximum score

```
py -3.12 -m voltshift benchtune --test TimeSpy
```

**Gameplay mode is the wrong tool for a benchmark, and will tell you the card is already
well tuned.** That is not a bug in the tuning — it is the measurement method refusing to lie.
Gameplay trials interleave candidate and baseline in short windows, which works when the load
drifts unpredictably. Inside a Time Spy run, consecutive windows land in *different scenes* —
Graphics Test 1 and Graphics Test 2 have very different loads — so the paired difference
measures the scene change, the standard error explodes, and every result is correctly
discarded as noise.

A benchmark offers something gameplay never does: one precise, repeatable number over a fixed
workload. So benchmark mode changes the unit of measurement to **one whole run**, and the
objective to **the score itself**.

- **Graphics score, not overall.** The overall score mixes in a CPU score VoltShift cannot
  influence and which only adds noise — measured on one machine's history, the CPU subscore
  varied by 3.7% run to run.
- **No significance shrinkage.** A benchmark score is a measurement, not an estimate from a
  drifting window, so the optimiser maximises it directly.
- **A real noise floor instead.** Back-to-back Time Spy runs on the same settings differ by
  about 0.18% (worst observed 1.17%), so a gain must clear `--min-gain` (default 0.4%) to be
  believed, and the winner is re-run to confirm.
- **The opening moves are not random.** Maximum score has well-understood directions: power
  limit first, then an undervolt to buy sustained boost inside that power budget, then clock
  and memory offsets. Random sampling would waste runs that each cost minutes. Pass
  `--no-seed` to search from scratch anyway.
- **A failed run is a stability signal.** 3DMark crashing or aborting right after a settings
  change marks that configuration unsafe, exactly like a driver reset would.

Results are read from `Documents\3DMark\*.3dmark-result` — a ZIP containing `Result.xml`. This
works on **every 3DMark edition**; no Professional licence and no command-line automation
needed. VoltShift applies a configuration, waits for you to run the benchmark, reads the score,
and proposes the next one.

---

## 🎮 Adaptive governor — tuning while you play

```
py -3.12 -m voltshift adaptive --goal balanced --probes 8
py -3.12 -m voltshift adaptive --probes 0        # apply learned profiles, never experiment
```

The governor detects the foreground game (by which process is *presenting frames* — no
guessing), loads what was learned for it, and ramps toward it **one capped step per tick** so
a wrong profile is caught partway there rather than all at once.

It then tags the workload — idle, menu, loading, light, heavy — and, in a steady gameplay
phase, may spend part of its **probe budget** on one small experiment.

> **On in-game probing.** This is the riskiest thing VoltShift does, and it is opt-out by a
> single slider. Every probe: moves **one knob by at most one capped step**; runs only in a
> phase that has already held steady; is journalled before it is written; is measured against
> the exact configuration it replaced; and is reverted the instant any stability signal fires.
> **One real fault spends the entire remaining budget** and marks that configuration unsafe
> forever. Set the budget to 0 and the governor still applies learned profiles — it just never
> experiments.

---

## 🧠 How the optimiser works

The "light local AI" is a **Gaussian process with expected-improvement acquisition** — about
200 lines of numpy. No model download, no GPU, no network, nothing phones home.

That is the right family of model for this problem, not a fashionable one. Tuning trials are
*expensive* (tens of seconds each) and *noisy* (the workload moves under you). A neural
network needs thousands of samples to say anything; a GP says something useful after five —
and, critically, says **how sure it is**, which is what the acquisition function uses to
decide between refining the best result so far and exploring somewhere unknown.

- **Kernel:** Matérn 5/2. Smooth, but without the implausible infinite smoothness of a
  squared-exponential kernel — hardware response curves have kinks.
- **Hyperparameters:** chosen by maximising the log marginal likelihood over a small grid.
  A grid is cheap at these sizes and cannot diverge.
- **Noise:** per-observation, so borrowed observations from other games are included at
  reduced weight rather than trusted equally.
- **Fallback:** if numpy is missing, a pattern-search optimiser takes over so the feature
  degrades instead of breaking.

The GP only ever *proposes*. It has no concept of a card that stops responding, and it should
not — mixing "what scores well" with "what is allowed" makes both harder to reason about. The
safeguard layer disposes.

---

## 🔬 Per-GPU control verification

**A range reported by ADLX is not a promise that writing to it does anything.** Some cards
advertise controls the driver quietly ignores, and which ones vary by architecture, by card,
and by driver build. An optimiser that trusts the advertised range wastes trials moving a dead
knob — and worse, credits it with another knob's effect.

VoltShift does not ship a hand-maintained table of GPU models to work around this; that would
be stale the week a driver shipped and useless for cards nobody tested. It asks the hardware
instead:

```
py -3.12 -m voltshift verify
```

For each knob it writes a small delta **in the conservative direction** (down for voltage,
clock and power — a verification pass never briefly overvolts or overclocks your card), reads
the value back, and restores the original either way. A knob that does not read back is dropped
from the search space, and the result is cached per physical card so the GPU is written to once
rather than at every launch.

```
  ✓ voltage_mv        verified (0 → -5 → restored)
  ✗ max_clock_mhz     driver ignored the write (asked -1, still 0)
  ✓ vram_max_mhz      verified (2518 → 2520 → restored)
  ✓ power_limit_pct   verified (0 → -1 → restored)

  advertised by ADLX : voltage_mv, max_clock_mhz, vram_max_mhz, power_limit_pct
  actually usable    : voltage_mv, vram_max_mhz, power_limit_pct
```

Verification runs automatically before your first Auto-Tune or governor session. Re-run it with
`--force` after a driver update.

**Known architecture semantics** (things a read-back cannot reveal — meaning, not support):

| Interface | Cards | Semantics |
|:---|:---|:---|
| `MGT2_1` | RDNA 4 — RX 9000 series | Voltage **and** max core clock are *offsets from stock*, both reading 0 at defaults (voltage range −200…0 mV, clock −500…+1000 MHz). **Minimum-clock tuning is not exposed at all.** |
| `MGT2` | RDNA 2/3 | Voltage is an *absolute* value. VoltShift converts absolute targets into the deltas this interface expects, so re-applying a configuration is idempotent. |
| `MGT1` | Legacy | Voltage is applied by shifting every point on the VF curve. |

---

## 💾 What it remembers

`voltshift_knowledge.db` (SQLite, next to the app) holds three tiers:

| Tier | Scope | Why it matters |
|:---|:---|:---|
| **Per game** | best configuration per `(card, exe, goal)` | Reapplied instantly next launch |
| **Transfer priors** | observations from your other games on this card | A new game starts from an educated guess, not from scratch |
| **Stability frontier** | the least aggressive voltage that has ever misbehaved, per clock band, per **physical card** | Games come and go; silicon limits do not. This is the memory that compounds. |

Cards are identified by device **and** unique id, so two identical GPUs in one machine keep
separate frontiers — silicon quality varies between samples, which is the entire reason
undervolting is a per-card exercise.

```
py -3.12 -m voltshift knowledge stats     # summary + the learned frontier
py -3.12 -m voltshift knowledge games     # best configuration per game
py -3.12 -m voltshift knowledge forget cyberpunk2077.exe
py -3.12 -m voltshift knowledge reset-frontier    # relearn this card's limits
py -3.12 -m voltshift knowledge export    # everything, as JSON
```

---

## 📽 Frame data setup

**Nothing to do — this sets itself up.** Frame data is what separates measuring a change from
guessing at it, so it is not opt-in.

On first run, if no frame source is present, VoltShift fetches Intel's **PresentMon** by
itself. It happens on a background thread, so startup never waits on the network, and the
telemetry hub is upgraded in place the moment the download lands — no restart.

Automatic does not mean opaque. The fetch:

- only talks to GitHub over HTTPS, and **validates every redirect target before following it**
  (checking where you landed afterwards is too late — the request already happened);
- takes the standalone console build from the official `GameTechDev/PresentMon` releases,
  never an installer and never the background service;
- verifies the payload really is a Windows executable before keeping it, so a rate-limit HTML
  page cannot end up sitting there named `PresentMon.exe`;
- downloads to a temporary file and moves it into place only after it passes, so a partial
  download never looks usable;
- writes the release tag, source URL and SHA-256 to `third_party\presentmon\source.json` so an
  install can be audited later.

It is fetched rather than vendored so the binary you run comes from upstream and this
repository redistributes nothing. PresentMon is MIT-licensed and needs administrator rights
for ETW tracing — which VoltShift already requires.

**To turn it off:** pass `--no-download` to `autotune` or `adaptive`, or set
`telemetry.auto_fetch_presentmon` to `false` in `voltshift_config.json`. A machine that is
offline simply carries on and retries at most once a day, rather than stalling every launch.

`scripts\fetch_presentmon.ps1` still exists if you would rather do it by hand.

**RivaTuner (RTSS)** — used automatically if it is already running, and preferred over
downloading anything. Gives average frametime only, so percentile lows are approximate.

**Neither available?** Everything still works. Auto-Tune falls back to power, clocks and
thermals, says so in the log, and marks its results as measured blind.

---

## ✨ Feature Matrix

| Area | Details |
|:---|:---|
| 🎯 **Auto-Tune** | One click. Paired-trial search over voltage, clocks, VRAM and power against four goal presets, with confirmation before commit |
| 🏁 **Benchmark mode** | Tunes for maximum 3DMark score: one run per trial, graphics score as the objective, measured noise floor, seeded opening moves |
| 🎮 **Adaptive governor** | Per-game profiles, workload phase tagging, budgeted in-game probes, instant revert |
| 🧠 **Bayesian optimiser** | numpy Gaussian process + expected improvement, transfer priors, pattern-search fallback |
| 🔬 **Control verification** | Measures which knobs the driver actually honours instead of trusting advertised ranges; cached per card |
| 🛡 **Stability detection** | TDR, frametime spike trains, clock cliffs, process death, hard hang |
| 💾 **Learned memory** | Per-game bests, cross-game transfer, per-silicon stability frontier |
| 🔒 **Crash survival** | Journal-before-write, last-known-good restore, boot-time recovery |
| 📽 **Frame telemetry** | Self-installing: fetches PresentMon on first run (verified, provenance recorded), or uses RTSS if already running |
| ⚡ **Dynamic voltage engine** | N clock/voltage thresholds, hysteresis, live graph with threshold lines |
| 🎛 **Manual tuning** | Voltage offset, core min/max clock, VRAM max clock + memory timing, power limit, TDC |
| 🌀 **Fan control** | 5-point curve editor, ZeroRPM, min/target fan speed |
| 📊 **Live metrics** | Clock, VRAM clock, temp, hotspot, board power, fan RPM, voltage, load |
| 🎮 **3D settings** | Anti-Lag(+Next), Chill, Boost, RIS + desktop sharpening, RSR, AFMF, FSR & frame-gen, Enhanced Sync, VSync mode, FRTC, tessellation, AA, AF |
| 🖥 **Per-display** | FreeSync, VSR, GPU/integer scaling, scaling mode, color depth, pixel format, custom color, HDCP |
| 🎞 **Multimedia** | Video upscale + sharpness, video super resolution |
| 🧩 **Desktop** | Simple Eyefinity create/destroy, desktop enumeration |
| 🚀 **App boost** | Auto-apply a power/clock boost while chosen games run, restore on exit |
| 💾 **Profiles** | Versioned JSON snapshots of every section; apply skips unsupported settings |
| 🪵 **Crash logger** | Flight recorder + Windows Event Log post-mortem, 7-code classification |

> Out of scope by design: undocumented driver registry hacks, CPU/SMU writes, driver
> install/update, and ADL-only features with no ADLX path.

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
| **Administrator rights** | Required for tuning writes and for PresentMon's ETW tracing |
| *Intel PresentMon* | *Fetched automatically on first run; no action needed* |

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

Frame telemetry installs itself on first run — see [Frame data setup](#-frame-data-setup).
Nothing to do here.

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

Produces `build\dist\VoltShift\VoltShift.exe` (bridge and PresentMon bundled, UAC-elevated).
Right-click → **Run as Administrator**.

---

## 🖥 Using the GUI

A dark sidebar app with an always-live metrics strip along the top:

- **Dashboard** — stat tiles including fps, 1% lows and fps-per-watt, plus scrolling
  clock / frametime / temp / power graphs
- **Auto-Tune** — goal picker, one button, live trial list, and what it applied
- **Adaptive** — governor switch, probe budget sliders, per-game memory and the learned
  stability frontier for your card
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
py -3.12 -m voltshift autotune --goal balanced   # one-shot closed-loop tune
py -3.12 -m voltshift benchtune --test TimeSpy   # tune for maximum benchmark score
py -3.12 -m voltshift adaptive --probes 8        # live governor (Ctrl+C = stop + restore)
py -3.12 -m voltshift verify                     # which controls this GPU really honours
py -3.12 -m voltshift knowledge stats            # what this card has taught VoltShift
py -3.12 -m voltshift info                       # GPU + capability summary
py -3.12 -m voltshift metrics -w                 # live metrics (watch)
py -3.12 -m voltshift run                        # dynamic voltage engine
py -3.12 -m voltshift tune voltage -120          # apply a voltage offset
py -3.12 -m voltshift tune fancurve 30:20 50:35 70:60 85:80 95:100
py -3.12 -m voltshift gfx set chill '{"enabled":true,"minFps":90,"maxFps":144}'
py -3.12 -m voltshift display list
py -3.12 -m voltshift profile save "quiet"
py -3.12 -m voltshift reset                      # restore AMD factory tuning
```

---

## 📈 Dynamic Voltage Engine

The 1.x feature, still here and still useful when you want an explicit hand-written curve
rather than a searched one. Thresholds are evaluated **highest clock first**; the first one
the reading meets wins. Below all thresholds the idle offset applies. Hysteresis requires N
consecutive polls before a new offset commits, so a clock hovering on a boundary doesn't cause
voltage flicker.

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

Saved to `voltshift_config.json` next to the app.

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

> **Interface note.** On MGT2_1 (RDNA 4) the voltage value *is* the offset. On MGT2 the bridge
> adds the argument to the current voltage. VoltShift's applier always works in absolute terms
> and converts on the way out, so a closed loop cannot walk the voltage downward on older
> cards by re-applying "the same" configuration.

---

## 🪵 Crash Logger

When a GPU TDR fires, Windows kills every process with a GPU context — including VoltShift —
so no in-process watcher can catch the moment. VoltShift instead writes telemetry to disk
every poll and leaves a heartbeat file. On the next launch a leftover heartbeat means the last
session crashed; VoltShift queries the Windows Event Log for TDR/crash events and reconstructs
a report from the saved telemetry into `voltshift_crashes.log`, classified into one of seven
reason codes with recommendations.

The crash logger is **read-only** — it never writes GPU state.

---

## 🛡 Safety

| Protection | How |
|:---|:---|
| 🚫 **No overvolt** | Positive voltage offsets are rejected in both the engine and the bridge |
| 📐 **Range clamped** | Every write is clamped to the ADLX-reported hardware range |
| 🔬 **Controls verified** | Knobs the driver ignores are dropped, so the optimiser never credits a dead control with another's effect |
| 🐾 **Step limited** | No knob moves more than its per-application cap in one write |
| 🚧 **Tabu set** | Configurations near a past failure are never proposed again |
| 📉 **Stability frontier** | A learned per-card voltage floor, with a safety margin held back |
| 📓 **Journal before write** | Risky changes hit disk *before* the GPU, so a hang is diagnosed next boot |
| ♻️ **Last-known-good** | Startup recovery restores the last configuration proven to survive |
| ✅ **Confirm before commit** | The winning configuration is re-measured before it is kept |
| 🔄 **Restores on exit** | Stopping anything, closing the GUI, or Ctrl+C restores factory tuning |
| 🌡 **Thermal guard** | Trials are rejected outright above a hard hotspot limit |
| 📖 **Read-only crash logger** | Only reads the Event Log and telemetry |
| 🧱 **Daemon never dies on error** | Command failures are error responses, not crashes |

> **Undervolting can destabilise a system.** VoltShift is built to fail safe and to learn from
> every fault, but no software can make experimenting with hardware limits risk-free. In-game
> probing is capped and opt-out; set the probe budget to 0 if you would rather it only applied
> what it already knows.
>
> If a crash leaves settings applied: **Adrenalin → Performance → Tuning → Reset**.

---

## 📄 License

MIT — free to use, modify, and distribute. The [ADLX SDK](https://github.com/GPUOpen-LibrariesAndSDKs/ADLX)
is distributed under AMD's own open-source license.
[PresentMon](https://github.com/GameTechDev/PresentMon) is MIT-licensed and fetched from
Intel's release page at your request; it is not redistributed here.

<div align="center">

*Built on AMD ADLX · Python 3.12 · C++17 · Not affiliated with or endorsed by AMD or Intel*

</div>
