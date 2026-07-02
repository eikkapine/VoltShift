"""VoltShift command-line interface.

    voltshift run                 run the dynamic voltage engine (Ctrl+C stops + resets)
    voltshift info                GPU + capability summary
    voltshift metrics [-w]        one-shot or watch live metrics
    voltshift tune ...            manual tuning (voltage/clocks/vram/power/fans)
    voltshift gfx ...             3D driver settings
    voltshift display ...         per-display settings
    voltshift profile ...         save / load / list profiles
    voltshift reset               restore AMD factory tuning
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time

from . import APP_NAME, __version__, paths
from .bridgeclient import BridgeClient, BridgeError
from .crashlog import CrashLogger
from .engine import EngineConfig
from .runner import EngineRunner
from . import profiles as profile_store


class C:
    RESET = "\033[0m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"


_LEVEL_COLOR = {"info": C.DIM, "volt": C.GREEN, "warn": C.YELLOW, "error": C.RED}


def _log(msg: str, level: str = "info") -> None:
    ts = time.strftime("%H:%M:%S")
    color = _LEVEL_COLOR.get(level, "")
    label = {"volt": "VOLT", "warn": "WARN", "error": "ERR "}.get(level, "INFO")
    print(f"{C.DIM}[{ts}]{C.RESET} {color}{label}  {msg}{C.RESET}")


def _banner(subtitle: str) -> None:
    print(f"\n{C.CYAN}  {APP_NAME} {__version__}{C.RESET} — {subtitle}\n")


def _load_engine_config(path: str | None) -> EngineConfig:
    if not path:
        try:
            with open(paths.config_path(), encoding="utf-8") as f:
                return EngineConfig.from_dict(json.load(f).get("engine", {}))
        except (OSError, ValueError):
            return EngineConfig()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return EngineConfig.from_dict(data.get("engine", data))


# ── subcommands ───────────────────────────────────────────────────────────────

def cmd_run(args) -> int:
    config = _load_engine_config(args.config)
    _banner("dynamic voltage engine")
    print("  Thresholds:")
    for t in sorted(config.thresholds, key=lambda t: t.clock_mhz, reverse=True):
        print(f"    ≥ {t.clock_mhz:>5} MHz  →  {t.offset_mv:>+5} mV")
    print(f"    below        →  {config.idle_offset_mv:>+5} mV  (idle)")
    print(f"  Poll {config.poll_interval_sec}s · hysteresis {config.hysteresis_count}\n")

    with BridgeClient() as bridge:
        gpu_name = bridge.info().get("name", "unknown")
        _log(f"GPU: {gpu_name}")

        crash_logger = CrashLogger(config.to_dict())
        crash_logger.on_log_entry = _log
        crash_logger.check_previous_session()
        crash_logger.start()
        crash_logger.write_session_header(gpu_name, config.to_dict())

        runner = EngineRunner(bridge, config, crash_logger)
        runner.on_log_entry = _log
        if not args.quiet:
            runner.on_sample = lambda s: print(
                f"{C.DIM}  {s.get('clockMhz', '?'):>5} MHz  "
                f"{(s.get('appliedOffsetMv') if s.get('appliedOffsetMv') is not None else 0):>+5} mV  "
                f"{s.get('tempC', 0):>3.0f}°C  {s.get('boardPowerW', 0):>4.0f} W{C.RESET}",
                end="\r")

        stop_requested = []

        def handle_sigint(_sig, _frame):
            stop_requested.append(True)

        signal.signal(signal.SIGINT, handle_sigint)
        runner.start()
        _log("Engine running — Ctrl+C stops and restores factory tuning")

        while runner.running and not stop_requested:
            time.sleep(0.2)

        print()
        runner.stop(reset_gpu=True)
        crash_logger.stop()
        crash_logger.write_session_footer(crash_logger.crash_count)
        _log("Stopped cleanly")
    return 0


def cmd_info(args) -> int:
    with BridgeClient() as bridge:
        info = bridge.info()
        caps = bridge.caps()
        _banner("GPU information")
        print(f"  GPU        : {info.get('name')}")
        print(f"  VRAM       : {info.get('vramMb')} MB {info.get('vramType')}")
        print(f"  Device ID  : {info.get('deviceId')} rev {info.get('revisionId')}")
        bios = info.get("bios", {})
        print(f"  BIOS       : {bios.get('version')} ({bios.get('date')})")
        tuning = caps.get("tuning", {})
        gfx_ifc = tuning.get("gfxInterface", {})
        ifc_name = "MGT2_1" if gfx_ifc.get("mgt2_1") else \
                   "MGT2" if gfx_ifc.get("mgt2") else \
                   "MGT1" if gfx_ifc.get("mgt1") else "none"
        print(f"  Tuning     : gfx={tuning.get('manualGfx')} ({ifc_name}) "
              f"vram={tuning.get('manualVram')} fan={tuning.get('manualFan')} "
              f"power={tuning.get('manualPower')}")
        print(f"  At factory : {tuning.get('atFactory')}")
        print(f"  Displays   : {caps.get('displayCount')} · Eyefinity: {caps.get('eyefinity')}")
        print(f"  Bridge     : v{bridge.version}\n")
        if args.json:
            print(json.dumps({"info": info, "caps": caps}, indent=2))
    return 0


def cmd_metrics(args) -> int:
    with BridgeClient() as bridge:
        def show() -> None:
            m = bridge.metrics()
            if args.json:
                print(json.dumps(m))
                return
            print(f"  clock {m.get('clockMhz', '?'):>5} MHz · "
                  f"vram {m.get('vramClockMhz', '?'):>5} MHz · "
                  f"{m.get('tempC', 0):>3.0f}°C (hotspot {m.get('hotspotC', 0):.0f}°C) · "
                  f"{m.get('boardPowerW', m.get('powerW', 0)):>4.0f} W · "
                  f"fan {m.get('fanRpm', '?')} rpm · "
                  f"load {m.get('usagePct', 0):.0f}%", end="\r" if args.watch else "\n")

        if args.watch:
            try:
                while True:
                    show()
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                print()
        else:
            show()
    return 0


def cmd_tune(args) -> int:
    with BridgeClient() as bridge:
        if args.tune_cmd == "get":
            print(json.dumps(bridge.tuning_get(), indent=2))
        elif args.tune_cmd == "voltage":
            result = bridge.set_voltage_offset(args.mv)
            _log(f"Voltage offset {result.get('appliedMv'):+d} mV "
                 f"({result.get('interface')})", "volt")
        elif args.tune_cmd == "clocks":
            result = bridge.set_core_clocks(args.min, args.max)
            _log(f"Core clocks applied: {result}", "volt")
        elif args.tune_cmd == "vram":
            result = bridge.set_vram_max(args.mhz)
            _log(f"VRAM max {result.get('appliedMhz')} MHz", "volt")
        elif args.tune_cmd == "timing":
            bridge.set_memory_timing(args.value)
            _log(f"Memory timing {args.value}", "volt")
        elif args.tune_cmd == "power":
            result = bridge.set_power_limit(args.pct)
            _log(f"Power limit {result.get('applied'):+d}%", "volt")
        elif args.tune_cmd == "fans":
            print(json.dumps(bridge.fans_get(), indent=2))
        elif args.tune_cmd == "fancurve":
            points = []
            for pair in args.points:
                temp, speed = pair.split(":")
                points.append({"tempC": int(temp), "speedPct": int(speed)})
            result = bridge.set_fan_curve(points)
            _log(f"Fan curve applied: {result['curve']}", "volt")
        elif args.tune_cmd == "zerorpm":
            bridge.set_zero_rpm(args.state == "on")
            _log(f"ZeroRPM {args.state}", "volt")
    return 0


def cmd_gfx(args) -> int:
    with BridgeClient() as bridge:
        if args.gfx_cmd == "get":
            print(json.dumps(bridge.gfx_get(), indent=2))
        elif args.gfx_cmd == "set":
            kwargs = json.loads(args.values)
            result = bridge.gfx_set(args.feature, **kwargs)
            _log(f"gfx {result.get('feature')} applied", "volt")
        elif args.gfx_cmd == "reset-shader-cache":
            bridge.reset_shader_cache()
            _log("Shader cache reset", "volt")
    return 0


def cmd_display(args) -> int:
    with BridgeClient() as bridge:
        if args.display_cmd == "list":
            for d in bridge.display_list():
                print(f"  [{d['index']}] {d['name']}  {d['width']}x{d['height']} "
                      f"@ {d['refreshHz']:.0f} Hz")
        elif args.display_cmd == "get":
            print(json.dumps(bridge.display_get(args.index), indent=2))
        elif args.display_cmd == "set":
            kwargs = json.loads(args.values)
            bridge.display_set(args.index, args.feature, **kwargs)
            _log(f"display[{args.index}] {args.feature} applied", "volt")
    return 0


def cmd_profile(args) -> int:
    with BridgeClient() as bridge:
        if args.profile_cmd == "list":
            entries = profile_store.list_profiles()
            if not entries:
                print("  No profiles saved yet.")
            for path in entries:
                print(f"  {path}")
        elif args.profile_cmd == "save":
            engine_config = _load_engine_config(None)
            profile = profile_store.capture(bridge, engine_config)
            path = profile_store.save(profile, args.name)
            _log(f"Profile saved → {path}")
        elif args.profile_cmd == "load":
            profile = profile_store.load(args.path)
            for line in profile_store.apply(bridge, profile):
                _log(line)
    return 0


def cmd_reset(_args) -> int:
    with BridgeClient() as bridge:
        bridge.tuning_reset()
        _log("GPU restored to AMD factory tuning", "volt")
    return 0


# ── parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voltshift", description=f"{APP_NAME} — AMD Radeon tuning suite")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the dynamic voltage engine")
    run.add_argument("--config", help="engine config JSON path")
    run.add_argument("--quiet", action="store_true", help="suppress per-poll output")
    run.set_defaults(fn=cmd_run)

    info = sub.add_parser("info", help="GPU and capability summary")
    info.add_argument("--json", action="store_true")
    info.set_defaults(fn=cmd_info)

    metrics = sub.add_parser("metrics", help="live metrics")
    metrics.add_argument("-w", "--watch", action="store_true")
    metrics.add_argument("--interval", type=float, default=0.5)
    metrics.add_argument("--json", action="store_true")
    metrics.set_defaults(fn=cmd_metrics)

    tune = sub.add_parser("tune", help="manual tuning")
    tune_sub = tune.add_subparsers(dest="tune_cmd", required=True)
    tune_sub.add_parser("get", help="dump tuning state")
    p = tune_sub.add_parser("voltage", help="set voltage offset")
    p.add_argument("mv", type=int, help="offset in mV (e.g. -120)")
    p = tune_sub.add_parser("clocks", help="set core clock limits")
    p.add_argument("--min", type=int)
    p.add_argument("--max", type=int)
    p = tune_sub.add_parser("vram", help="set VRAM max clock")
    p.add_argument("mhz", type=int)
    p = tune_sub.add_parser("timing", help="set memory timing preset")
    p.add_argument("value", type=int)
    p = tune_sub.add_parser("power", help="set power limit %")
    p.add_argument("pct", type=int)
    tune_sub.add_parser("fans", help="dump fan state")
    p = tune_sub.add_parser("fancurve", help="set fan curve")
    p.add_argument("points", nargs="+", metavar="TEMP:SPEED",
                   help="e.g. 30:20 50:35 70:60 85:80 95:100")
    p = tune_sub.add_parser("zerorpm", help="toggle ZeroRPM")
    p.add_argument("state", choices=["on", "off"])
    tune.set_defaults(fn=cmd_tune)

    gfx = sub.add_parser("gfx", help="3D driver settings")
    gfx_sub = gfx.add_subparsers(dest="gfx_cmd", required=True)
    gfx_sub.add_parser("get", help="dump all 3D settings")
    p = gfx_sub.add_parser("set", help="set a feature")
    p.add_argument("feature")
    p.add_argument("values", help='JSON args, e.g. \'{"enabled":true}\'')
    gfx_sub.add_parser("reset-shader-cache", help="reset the shader cache")
    gfx.set_defaults(fn=cmd_gfx)

    display = sub.add_parser("display", help="per-display settings")
    display_sub = display.add_subparsers(dest="display_cmd", required=True)
    display_sub.add_parser("list", help="list displays")
    p = display_sub.add_parser("get", help="dump one display's settings")
    p.add_argument("index", type=int, nargs="?", default=0)
    p = display_sub.add_parser("set", help="set a display feature")
    p.add_argument("index", type=int)
    p.add_argument("feature")
    p.add_argument("values", help='JSON args, e.g. \'{"enabled":true}\'')
    display.set_defaults(fn=cmd_display)

    profile = sub.add_parser("profile", help="profiles")
    profile_sub = profile.add_subparsers(dest="profile_cmd", required=True)
    profile_sub.add_parser("list", help="list saved profiles")
    p = profile_sub.add_parser("save", help="capture current state")
    p.add_argument("name")
    p = profile_sub.add_parser("load", help="apply a profile file")
    p.add_argument("path")
    profile.set_defaults(fn=cmd_profile)

    reset = sub.add_parser("reset", help="restore AMD factory tuning")
    reset.set_defaults(fn=cmd_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except BridgeError as exc:
        _log(str(exc), "error")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
