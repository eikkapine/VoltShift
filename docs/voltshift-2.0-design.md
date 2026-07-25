# VoltShift 2.0 — closed-loop auto-tuning

**Status:** implemented
**Date:** 2026-07-26

## Problem

VoltShift 1.x is an open loop. The user writes a clock→voltage threshold table and the engine
obeys it. Three consequences:

1. **The user must already know the numbers.** Finding them means an evening of manual
   bisection, and the result is only valid for the workload it was found under.
2. **Nothing measures whether it helped.** ADLX reports clocks, temperatures and power. It
   cannot report frame rate, so an undervolt that holds clocks while dropping frames looks
   identical to one that works.
3. **Nothing is remembered.** Every crash teaches nothing; every new game starts from zero.

## Goal

One button that finds good settings for whatever is running, proves the result against real
measurements, keeps it per game, and adapts while the user plays — without making the machine
unstable, and without any of it being a black box.

## Design

### 1. Telemetry fusion (`telemetry/`)

One `TelemetryHub` polls the bridge and joins each reading with frame-pacing statistics into a
`Sample`. Everything else subscribes. Frame sources are pluggable:

- `PresentMonSource` — bundled Intel PresentMon (MIT), CSV over stdout. Header-driven column
  mapping so both the 1.x (`msBetweenPresents`) and 2.x (`MsBetweenPresents`) schemas work.
- `RtssFrameSource` — RTSS shared memory, average frametime only.
- `NullFrameSource` — nothing installed; the app degrades to hardware-only reasoning.

`WindowStats` aggregates a measurement window. `paired_delta` compares matched
candidate/baseline windows and reports a mean difference **with its standard error**.

**Why paired.** Game load is non-stationary. Comparing "config A at 10:00" against "config B at
10:02" measures the scenery as much as the settings. Alternating the two and averaging the
*differences* cancels any drift that affects both members of a pair.

### 2. Stability detection (`stability.py`)

Five signatures, because an unstable GPU rarely reports itself:

| Signature | Signal |
|---|---|
| TDR | Windows Event Log 4101 |
| Spike train | Cluster of very long frames time-locked to a settings write |
| Clock cliff | Core clock collapses while utilisation and power stay high |
| Process death | The measured application stops presenting right after a write |
| Hard hang | Nothing at all — caught next boot by the watchdog |

Attribution is bounded on both sides: a sample only belongs to a change if it was taken after
it and within the settle window.

### 3. Optimiser (`optimizer/`)

- **`space.py`** — knobs and bounds read from `tuning.get`, never invented. Records whether
  the card's voltage field is an offset (MGT2_1) or absolute (MGT2).
- **`objective.py`** — four goal presets weighting relative deltas. 1% low is weighted above
  average fps, because average fps can drift upward while the experience degrades. Deltas are
  scaled by confidence, so unrepeatable results contribute almost nothing.
- **`gp.py`** — Gaussian process (Matérn 5/2, grid-searched hyperparameters, per-observation
  noise) with expected-improvement acquisition. ~200 lines of numpy.
- **`safeguard.py`** — bounds, step caps, tabu proximity, learned frontier. The optimiser
  proposes; this disposes. Keeping "what scores well" separate from "what is allowed" keeps
  both auditable.
- **`applier.py`** — the only place that knows ADLX's quirks. Always works in absolute voltage
  and converts on the way out, so re-applying a configuration on MGT2 is idempotent instead of
  walking the voltage down.
- **`session.py`** — the trial state machine: baseline → explore → confirm → apply.

**Why a GP.** Trials are expensive (tens of seconds) and noisy. That is precisely the regime
Bayesian optimisation exists for. It is useful after ~5 samples and reports its own
uncertainty, which is what drives the explore/exploit decision. A neural network would need
thousands of trials to say anything and could not express uncertainty at all.

**Why confirm before commit.** Bayesian optimisation over-selects whatever got lucky, so the
best score of a search is a biased estimate. One extra paired measurement of the winner costs
little and stops a fluke from being written to disk.

### 4. Per-GPU control verification (`gpuprofile.py`)

A range reported by ADLX is not a promise that writing to it does anything. Cards advertise
controls their driver ignores, and which ones varies by architecture, card and driver build.
An optimiser that trusts the advertised range spends trials on an inert knob and may credit it
with another knob's effect.

A hand-maintained table of GPU models was rejected: it is stale as soon as a driver ships and
says nothing about untested cards. Instead each knob is measured — write a small delta in the
conservative direction (down for voltage, clock and power, so a verification pass never
briefly overvolts or overclocks), read it back, restore either way. Knobs that do not read back
are dropped from the search space; results are cached per physical card in the knowledge store.

Because it writes to the GPU it never runs silently at startup: it runs once before the first
tuning session, and on demand via `voltshift verify --force`.

`ARCH_NOTES` covers only what a read-back cannot reveal — semantics rather than support. On
MGT2_1 (RDNA 4) both voltage and max core clock are offsets reading 0 at stock, and
minimum-clock tuning is not exposed at all; on MGT2 voltage is absolute.

### 5. Knowledge (`knowledge.py`)

SQLite, three tiers: per-game bests, down-weighted transfer priors from other games on the
same card, and the **stability frontier** — the least aggressive voltage that ever misbehaved,
per clock band, per physical card. Cards are keyed by device *and* unique id, because silicon
quality varies between samples of the same model.

The frontier is the memory that compounds: workloads change, silicon limits do not.

### 5. Watchdog (`watchdog.py`)

Journal-before-write. A configuration is written to disk as unverified, applied, then promoted
to last-known-good after a probation period. An unverified journal found at startup means the
previous session died with that configuration live: it is marked unsafe and the last-known-good
state is restored.

This is the only mechanism that can survive a hard hang, and it is what makes in-game probing
recoverable.

### 6. Adaptive governor (`adaptive.py`)

Detects the game by which process is presenting frames, loads its learned profile, and ramps
toward it one capped step per tick. Tags workload phase by rule (idle/menu/loading/light/heavy)
— rules rather than a classifier, because the output decides whether to touch voltage and a
rule can be read and audited.

In a steady gameplay phase it may spend a probe from a capped budget: one knob, one step,
journalled, measured against the configuration it replaced, reverted on any fault. One real
fault spends the whole remaining budget.

## Decisions and trade-offs

| Decision | Rationale |
|---|---|
| PresentMon fetched, not vendored | The user pulls the binary from Intel's own release page; the repo redistributes nothing. Recorded with URL and SHA-256. |
| GPU only, official ADLX only | Preserves 1.x's no-hacks rule. Ryzen Curve Optimizer would need an unsigned ring-0 driver and can hard-hang the machine. |
| In-game probing allowed | User's explicit choice. Fenced with step caps, phase gating, journalling, instant revert, and a budget that a single fault exhausts. |
| Rule-based phase tagging | Few obvious categories; auditability matters more than accuracy here. |
| numpy required, fallback provided | The GP needs numpy. A pattern-search fallback means a partial install degrades rather than breaking the headline feature. |

## Testing

132 tests. The optimiser is verified against a simulated card with a known performance peak and
a known stability cliff: it must find the peak and must not fall off the cliff. Stability
detection, the watchdog's crash-recovery protocol, paired statistics, the knowledge store's
frontier logic, and the governor's step limiting are each covered directly.

## Bugs found during implementation

- `PairedDelta.significant` returned False when the standard error was exactly zero, treating
  a perfectly consistent difference as no evidence rather than the strongest available.
- Spike-train attribution had no lower time bound, so a sample older than a change could be
  blamed on it.
- `_last_change_t` used `0.0` as a "never" sentinel, which is ambiguous with a real timestamp
  of zero.
- Measurement windows re-filtered samples against a timestamp taken before the sleep, which
  yields nothing when the platform clock is coarser than the window. The hub already bounds
  history by age, so the second filter was removed.
- The PyInstaller spec excluded numpy — the frozen build would have silently shipped the
  fallback optimiser.
