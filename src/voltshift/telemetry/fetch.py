"""Fetching PresentMon on first run.

Frame-rate aware tuning is the difference between VoltShift knowing whether a
change helped and merely guessing, so requiring the user to go and run a
script first was friction in the wrong place. This module fetches Intel's
PresentMon automatically the first time it is needed.

Automatic does not mean opaque. The fetch:

  * only ever talks to GitHub over HTTPS, and refuses any redirect that
    leaves the allowed hosts;
  * takes the standalone console build from the official
    GameTechDev/PresentMon releases, never an installer or a service;
  * checks the payload really is a Windows executable before keeping it;
  * writes the source URL, release tag and SHA-256 to `source.json` next to
    the binary, so an install can always be audited afterwards;
  * downloads to a temporary file and moves it into place only once it has
    passed, so a half-finished download is never left looking usable.

It runs off the main thread, never blocks startup, and degrades silently to
RTSS or to hardware-only tuning when the machine is offline. Set
`auto_fetch_presentmon` to false in `voltshift_config.json`, or pass
`--no-download` on the CLI, to turn it off entirely.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import paths

RELEASES_API = "https://api.github.com/repos/GameTechDev/PresentMon/releases/latest"
USER_AGENT = "VoltShift"

# Every host the fetch is allowed to touch, including the ones GitHub
# redirects release downloads to. Anything else aborts the download.
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

# The console build, not the installer and not the background service.
ASSET_PATTERN = re.compile(r"^PresentMon.*\.exe$", re.IGNORECASE)
ASSET_REJECT = re.compile(r"setup|installer|service", re.IGNORECASE)

MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_TIMEOUT_SEC = 30.0

# Marker written when a fetch fails, so a machine that is simply offline does
# not retry on every single launch.
ATTEMPT_FILE = "fetch_attempt.json"
RETRY_AFTER_SEC = 24 * 3600


def target_dir() -> str:
    return os.path.join(paths.app_dir(), "third_party", "presentmon")


def target_exe() -> str:
    return os.path.join(target_dir(), "PresentMon.exe")


class FetchError(RuntimeError):
    pass


def _check_host(url: str) -> None:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host.lower() not in ALLOWED_HOSTS:
        raise FetchError(f"refusing to download from unexpected host: {host}")


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validates a redirect target before following it.

    Checking `response.geturl()` after the fact is too late — by then the
    request has already been made to whatever host the redirect pointed at.
    GitHub genuinely does redirect release downloads to its asset CDN, so
    redirects have to be allowed; they just have to stay inside the allowed
    set, and that has to be decided before the connection happens.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        _RestrictedRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
    )


def _open(url: str, timeout: float, accept: str = "application/json"):
    _check_host(url)
    if urllib.parse.urlsplit(url).scheme != "https":
        raise FetchError(f"refusing a non-HTTPS URL: {url}")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    response = _build_opener().open(request, timeout=timeout)
    # Belt and braces: the handler above should have caught anything stray,
    # but the landing URL is cheap to re-check.
    _check_host(response.geturl())
    return response


def _pick_asset(release: dict) -> Optional[dict]:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if ASSET_PATTERN.match(name) and not ASSET_REJECT.search(name):
            return asset
    return None


def _recently_attempted() -> bool:
    path = os.path.join(target_dir(), ATTEMPT_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            last = float(json.load(f).get("ts", 0))
    except (OSError, ValueError, TypeError):
        return False
    import time

    return (time.time() - last) < RETRY_AFTER_SEC


def _record_attempt(error: str) -> None:
    import time

    os.makedirs(target_dir(), exist_ok=True)
    try:
        with open(os.path.join(target_dir(), ATTEMPT_FILE), "w",
                  encoding="utf-8") as f:
            json.dump({"ts": time.time(), "error": error}, f)
    except OSError:
        pass


def download_presentmon(timeout: float = DEFAULT_TIMEOUT_SEC,
                        on_log: Optional[Callable[[str, str], None]] = None) -> str:
    """Fetch the PresentMon console build. Returns the path, or raises."""
    def log(message: str, level: str = "info") -> None:
        if on_log:
            on_log(message, level)

    with _open(RELEASES_API, timeout) as response:
        release = json.loads(response.read().decode("utf-8"))

    asset = _pick_asset(release)
    if asset is None:
        raise FetchError(f"no standalone PresentMon executable in release "
                         f"{release.get('tag_name', '?')}")

    url = asset["browser_download_url"]
    size = int(asset.get("size", 0))
    if size > MAX_DOWNLOAD_BYTES:
        raise FetchError(f"asset is unexpectedly large ({size} bytes)")

    log(f"fetching {asset['name']} ({size / 1e6:.1f} MB) from "
        f"{release.get('tag_name', '?')} for frame-rate aware tuning")

    os.makedirs(target_dir(), exist_ok=True)
    digest = hashlib.sha256()
    written = 0

    handle, tmp_path = tempfile.mkstemp(dir=target_dir(), suffix=".part")
    try:
        with os.fdopen(handle, "wb") as out, _open(
                url, timeout, accept="application/octet-stream") as response:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_DOWNLOAD_BYTES:
                    raise FetchError("download exceeded the size limit")
                digest.update(chunk)
                out.write(chunk)

        # A truncated download or an error page saved as .exe would otherwise
        # sit there looking like a working install.
        with open(tmp_path, "rb") as check:
            if check.read(2) != b"MZ":
                raise FetchError("downloaded file is not a Windows executable")
        if written == 0:
            raise FetchError("downloaded file was empty")

        os.replace(tmp_path, target_exe())
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    with open(os.path.join(target_dir(), "source.json"), "w", encoding="utf-8") as f:
        json.dump({
            "tag": release.get("tag_name"),
            "asset": asset["name"],
            "url": url,
            "sha256": digest.hexdigest(),
            "bytes": written,
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, f, indent=2)

    log(f"PresentMon ready — sha256 {digest.hexdigest()[:16]}…", "volt")
    return target_exe()


def ensure_presentmon(on_log: Optional[Callable[[str, str], None]] = None,
                      allow_download: bool = True,
                      timeout: float = DEFAULT_TIMEOUT_SEC) -> Optional[str]:
    """Return a usable PresentMon path, fetching it once if necessary."""
    from .frames import find_presentmon

    existing = find_presentmon()
    if existing:
        return existing
    if not allow_download:
        return None
    if _recently_attempted():
        return None

    try:
        return download_presentmon(timeout=timeout, on_log=on_log)
    except (FetchError, urllib.error.URLError, OSError, ValueError) as exc:
        _record_attempt(str(exc))
        if on_log:
            on_log(f"could not fetch PresentMon ({exc}); tuning will use power, "
                   f"clocks and thermals only", "warn")
        return None


def ensure_in_background(hub, on_log: Optional[Callable[[str, str], None]] = None,
                         allow_download: bool = True) -> threading.Thread:
    """Fetch PresentMon off the main thread and upgrade a live hub to it.

    Startup must never wait on the network, and a session that begins without
    frame data should start using it the moment it becomes available rather
    than requiring a restart.
    """
    def work() -> None:
        path = ensure_presentmon(on_log, allow_download)
        if not path:
            return
        current = hub.frame_source
        if current is not None and current.name == "presentmon":
            return
        from .frames import PresentMonSource

        source = PresentMonSource(path)
        if not source.available:
            return
        hub.use_frame_source(source)
        if on_log:
            on_log(f"frame telemetry enabled — {source.status}", "volt")

    thread = threading.Thread(target=work, name="voltshift-fetch", daemon=True)
    thread.start()
    return thread
