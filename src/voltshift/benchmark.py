"""Reading 3DMark results, so a benchmark score can be the objective.

Tuning for a benchmark is a different problem from tuning for gameplay, and
the difference is not cosmetic.

Gameplay is an open-ended, drifting workload, so VoltShift interleaves
candidate and baseline in short windows and compares the paired differences.
Applying that method inside a benchmark run is actively wrong: consecutive
windows land in different scenes — Time Spy's Graphics Test 1 and Graphics
Test 2 have very different loads — so the "difference" measures the scene
change, the standard error explodes, and every result is correctly dismissed
as noise. That is why gameplay-mode tuning reports that nothing beat the
baseline on a benchmark.

A benchmark instead gives something gameplay never does: a single, precise,
repeatable number at the end of a fixed workload. So the unit of measurement
becomes one whole run, and the objective becomes the score itself.

3DMark autosaves every run to Documents\\3DMark as a `.3dmark-result` file,
which is a ZIP containing `Result.xml`. That works on every edition — no
Professional licence and no command-line automation required. The score is
also in the filename, which is used as a fallback.

Runs that fail are not ignored. A benchmark that crashes or is aborted right
after a settings change is a stability signal as real as a TDR.
"""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional

RESULT_SUFFIX = ".3dmark-result"

# 3DMark-TimeSpy-27178-20260417234130.3dmark-result
# 3DMark-TimeSpy-FAILED-20260726013449.3dmark-result
FILENAME_RE = re.compile(
    r"^3DMark-(?P<test>.+?)-(?P<score>FAILED|[\d,]+)-(?P<stamp>\d{14})"
    + re.escape(RESULT_SUFFIX) + r"$", re.IGNORECASE)

# Element names vary per benchmark (TimeSpyPerformanceGraphicsScore,
# SteelNomadGraphicsScore, ...), so they are matched by suffix.
GRAPHICS_SUFFIX = "graphicsscore"
OVERALL_SUFFIXES = ("3dmarkscore", "overallscore")
CPU_SUFFIX = "cpuscore"


def results_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents", "3DMark")


@dataclass(frozen=True)
class BenchmarkResult:
    test: str
    path: str
    modified: float
    failed: bool
    overall: Optional[float] = None
    graphics: Optional[float] = None
    cpu: Optional[float] = None

    @property
    def objective(self) -> Optional[float]:
        """The number to maximise.

        Graphics score when available: it isolates the GPU, while the overall
        score mixes in a CPU score VoltShift cannot influence and which only
        adds run-to-run noise.
        """
        return self.graphics if self.graphics is not None else self.overall

    def describe(self) -> str:
        if self.failed:
            return f"{self.test}: FAILED"
        parts = []
        if self.graphics is not None:
            parts.append(f"graphics {self.graphics:.0f}")
        if self.overall is not None:
            parts.append(f"overall {self.overall:.0f}")
        return f"{self.test}: " + ", ".join(parts) if parts else f"{self.test}: no score"


def _scores_from_xml(data: str) -> dict[str, float]:
    """Pull every score element out of Result.xml, keyed by lowered tag."""
    found: dict[str, float] = {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return found
    for element in root.iter():
        tag = element.tag.split("}")[-1].lower()
        if "score" not in tag or element.text is None:
            continue
        # "...ForPass" entries duplicate the totals per pass; the plain names
        # are the run's final figures.
        if tag.endswith("forpass"):
            continue
        try:
            found[tag] = float(element.text.strip())
        except ValueError:
            continue
    return found


def parse_result(path: str) -> Optional[BenchmarkResult]:
    """Read one .3dmark-result file. Falls back to the filename if needed."""
    name = os.path.basename(path)
    match = FILENAME_RE.match(name)
    test = match.group("test") if match else os.path.splitext(name)[0]
    failed = bool(match) and match.group("score").upper() == "FAILED"

    try:
        modified = os.path.getmtime(path)
    except OSError:
        return None

    overall = graphics = cpu = None
    try:
        with zipfile.ZipFile(path) as archive:
            if "Result.xml" in archive.namelist():
                scores = _scores_from_xml(
                    archive.read("Result.xml").decode("utf-8", "replace"))
                for tag, value in scores.items():
                    if tag.endswith(GRAPHICS_SUFFIX):
                        graphics = value
                    elif tag.endswith(CPU_SUFFIX):
                        cpu = value
                    elif any(tag.endswith(s) for s in OVERALL_SUFFIXES):
                        overall = value
    except (zipfile.BadZipFile, OSError, KeyError):
        pass

    if overall is None and match and not failed:
        try:
            overall = float(match.group("score").replace(",", ""))
        except ValueError:
            pass

    # A run with no score at all did not complete, whatever the name says.
    if not failed and overall is None and graphics is None:
        failed = True

    return BenchmarkResult(test=test, path=path, modified=modified, failed=failed,
                           overall=overall, graphics=graphics, cpu=cpu)


def latest_result(directory: Optional[str] = None) -> Optional[BenchmarkResult]:
    directory = directory or results_dir()
    try:
        entries = [os.path.join(directory, f) for f in os.listdir(directory)
                   if f.lower().endswith(RESULT_SUFFIX)]
    except OSError:
        return None
    if not entries:
        return None
    return parse_result(max(entries, key=os.path.getmtime))


def history(directory: Optional[str] = None, test: Optional[str] = None
            ) -> list[BenchmarkResult]:
    """Every parseable past result, oldest first."""
    directory = directory or results_dir()
    try:
        names = [f for f in os.listdir(directory)
                 if f.lower().endswith(RESULT_SUFFIX)]
    except OSError:
        return []
    out = []
    for name in names:
        result = parse_result(os.path.join(directory, name))
        if result is None:
            continue
        if test and result.test.lower() != test.lower():
            continue
        out.append(result)
    return sorted(out, key=lambda r: r.modified)


class ResultWatcher:
    """Waits for 3DMark to write a new result file.

    Everything present when the watcher starts is treated as already seen, so
    a trial is only ever scored against a run that happened after its
    configuration was applied.
    """

    def __init__(self, directory: Optional[str] = None,
                 test: Optional[str] = None, poll_sec: float = 2.0):
        self.directory = directory or results_dir()
        self.test = test
        self.poll_sec = poll_sec
        self._seen: set[str] = set()
        self._started = time.time()
        self.rescan()

    def _current(self) -> set[str]:
        try:
            return {f for f in os.listdir(self.directory)
                    if f.lower().endswith(RESULT_SUFFIX)}
        except OSError:
            return set()

    def rescan(self) -> None:
        self._seen = self._current()
        self._started = time.time()

    def poll(self) -> Optional[BenchmarkResult]:
        """Return a new result if one has appeared, else None."""
        for name in sorted(self._current() - self._seen):
            self._seen.add(name)
            result = parse_result(os.path.join(self.directory, name))
            if result is None:
                continue
            if self.test and result.test.lower() != self.test.lower():
                continue
            return result
        return None

    def wait(self, timeout: float,
             should_stop: Optional[Callable[[], bool]] = None
             ) -> Optional[BenchmarkResult]:
        """Block until a new matching result appears, or the timeout passes."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if should_stop is not None and should_stop():
                return None
            result = self.poll()
            if result is not None:
                # 3DMark writes the file before it has finished flushing it;
                # a short settle avoids reading a truncated archive.
                time.sleep(1.0)
                reread = parse_result(result.path)
                return reread or result
            time.sleep(self.poll_sec)
        return None


def detect_running_benchmark() -> Optional[str]:
    """Name of a benchmark process currently running, if any."""
    import psutil

    known = {"3dmark.exe": "3DMark", "3dmarkcmd.exe": "3DMark",
             "superposition.exe": "Superposition", "unigine_heaven.exe": "Heaven",
             "furmark.exe": "FurMark"}
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in known:
            return known[name]
    return None
