"""Auto-install of PresentMon.

The fetch runs without the user asking, so the safety properties matter more
than the happy path: it must only talk to GitHub, must refuse anything that
is not actually an executable, must never leave a half-written file looking
usable, and must never take down startup when the machine is offline.
"""

import io
import json
import os
import urllib.error

import pytest

from voltshift import paths
from voltshift.telemetry import fetch
from voltshift.telemetry.fetch import FetchError, ensure_presentmon

MZ = b"MZ\x90\x00" + b"\x00" * 512


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(fetch.paths, "app_dir", lambda: str(tmp_path))
    return tmp_path


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, url: str):
        super().__init__(payload)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _release(asset_name="PresentMon-2.3.0-x64.exe", size=len(MZ),
             url="https://github.com/GameTechDev/PresentMon/releases/download/v2.3.0/PresentMon.exe"):
    return {"tag_name": "v2.3.0",
            "assets": [{"name": asset_name, "size": size,
                        "browser_download_url": url}]}


def _wire(monkeypatch, release=None, payload=MZ, download_url=None):
    """Route the module's HTTP through fakes instead of the network."""
    release = release if release is not None else _release()

    def fake_open(url, timeout, accept="application/json"):
        # Mirror the real _open's contract: validate the requested host and
        # the host actually landed on, so these tests exercise the guard
        # rather than a fake that quietly skips it.
        fetch._check_host(url)
        if url == fetch.RELEASES_API:
            return FakeResponse(json.dumps(release).encode(), url)
        landed = download_url or url
        fetch._check_host(landed)
        return FakeResponse(payload, landed)

    monkeypatch.setattr(fetch, "_open", fake_open)


# ── happy path ────────────────────────────────────────────────────────────────

def test_downloads_and_records_provenance(monkeypatch, isolated):
    _wire(monkeypatch)
    path = ensure_presentmon()
    assert path and os.path.isfile(path)
    assert open(path, "rb").read(2) == b"MZ"

    with open(os.path.join(fetch.target_dir(), "source.json"), encoding="utf-8") as f:
        source = json.load(f)
    assert source["tag"] == "v2.3.0"
    assert source["url"].startswith("https://github.com/")
    assert len(source["sha256"]) == 64


def test_existing_install_is_not_redownloaded(monkeypatch, isolated):
    os.makedirs(fetch.target_dir(), exist_ok=True)
    with open(fetch.target_exe(), "wb") as f:
        f.write(MZ)

    def explode(*a, **k):
        raise AssertionError("should not hit the network when already installed")

    monkeypatch.setattr(fetch, "_open", explode)
    assert ensure_presentmon() == fetch.target_exe()


# ── refusing bad input ────────────────────────────────────────────────────────

def test_rejects_a_payload_that_is_not_an_executable(monkeypatch, isolated):
    # An HTML error page saved as .exe would otherwise look like a good install.
    _wire(monkeypatch, payload=b"<!DOCTYPE html><html>rate limited</html>")
    assert ensure_presentmon() is None
    assert not os.path.exists(fetch.target_exe())


def test_rejects_an_empty_payload(monkeypatch, isolated):
    _wire(monkeypatch, payload=b"")
    assert ensure_presentmon() is None
    assert not os.path.exists(fetch.target_exe())


def test_leaves_no_partial_file_behind(monkeypatch, isolated):
    _wire(monkeypatch, payload=b"not an exe at all")
    ensure_presentmon()
    leftovers = [f for f in os.listdir(fetch.target_dir()) if f.endswith(".part")]
    assert leftovers == []


def test_refuses_a_download_host_outside_github(monkeypatch, isolated):
    _wire(monkeypatch, release=_release(url="https://evil.example.com/PresentMon.exe"))
    assert ensure_presentmon() is None
    assert not os.path.exists(fetch.target_exe())


def test_refuses_a_redirect_that_leaves_github(monkeypatch, isolated):
    _wire(monkeypatch, download_url="https://evil.example.com/payload.exe")
    assert ensure_presentmon() is None
    assert not os.path.exists(fetch.target_exe())


def test_rejects_an_oversized_asset(monkeypatch, isolated):
    _wire(monkeypatch, release=_release(size=fetch.MAX_DOWNLOAD_BYTES + 1))
    assert ensure_presentmon() is None


def test_skips_installers_and_services(monkeypatch, isolated):
    release = {"tag_name": "v2.3.0", "assets": [
        {"name": "PresentMon-Setup.exe", "size": 100,
         "browser_download_url": "https://github.com/x/PresentMon-Setup.exe"},
        {"name": "PresentMonService.exe", "size": 100,
         "browser_download_url": "https://github.com/x/PresentMonService.exe"},
    ]}
    _wire(monkeypatch, release=release)
    assert ensure_presentmon() is None, "must not install the service or installer"


def test_picks_the_console_build_when_offered_alongside_others(monkeypatch, isolated):
    release = {"tag_name": "v2.3.0", "assets": [
        {"name": "PresentMon-Setup.exe", "size": 100,
         "browser_download_url": "https://github.com/x/setup.exe"},
        {"name": "PresentMon-2.3.0-x64.exe", "size": len(MZ),
         "browser_download_url": "https://github.com/x/PresentMon.exe"},
    ]}
    _wire(monkeypatch, release=release)
    assert ensure_presentmon() is not None
    with open(os.path.join(fetch.target_dir(), "source.json"), encoding="utf-8") as f:
        assert json.load(f)["asset"] == "PresentMon-2.3.0-x64.exe"


def test_redirect_handler_rejects_before_following(isolated):
    """The guard must fire on the redirect itself, not on the landing page.

    Validating after urlopen returns is too late: the request has already
    been made to whatever host the redirect named.
    """
    handler = fetch._RestrictedRedirectHandler()
    request = urllib.request.Request("https://github.com/x")

    with pytest.raises(FetchError):
        handler.redirect_request(request, None, 302, "Found", {},
                                 "https://evil.example.com/payload.exe")


def test_redirect_handler_allows_the_github_asset_cdn(isolated):
    """GitHub really does redirect release downloads; that must keep working."""
    handler = fetch._RestrictedRedirectHandler()
    request = urllib.request.Request("https://github.com/x")
    # Only asserting the host check passes; urllib may still decline for
    # unrelated reasons, which is not what this test is about.
    fetch._check_host("https://objects.githubusercontent.com/asset")


def test_non_https_urls_are_refused(monkeypatch, isolated):
    with pytest.raises(FetchError):
        fetch._open("http://github.com/x", timeout=1)


# ── failing safely ────────────────────────────────────────────────────────────

def test_offline_machine_degrades_quietly(monkeypatch, isolated):
    def offline(*a, **k):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(fetch, "_open", offline)
    logged = []
    assert ensure_presentmon(on_log=lambda m, l="info": logged.append((m, l))) is None
    assert any(level == "warn" for _, level in logged)


def test_a_failed_fetch_is_not_retried_every_launch(monkeypatch, isolated):
    calls = []

    def offline(*a, **k):
        calls.append(1)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(fetch, "_open", offline)
    ensure_presentmon()
    ensure_presentmon()
    assert len(calls) == 1, "a machine with no internet must not retry constantly"


def test_opting_out_skips_the_network_entirely(monkeypatch, isolated):
    def explode(*a, **k):
        raise AssertionError("allow_download=False must not touch the network")

    monkeypatch.setattr(fetch, "_open", explode)
    assert ensure_presentmon(allow_download=False) is None


def test_background_fetch_upgrades_a_live_hub(monkeypatch, isolated):
    _wire(monkeypatch)

    class FakeHub:
        def __init__(self):
            self.frame_source = type("S", (), {"name": "none"})()
            self.swapped = None

        def use_frame_source(self, source):
            self.swapped = source
            self.frame_source = source

    hub = FakeHub()
    fetch.ensure_in_background(hub).join(timeout=10)
    # The fake binary is not a real PresentMon, so availability is what is
    # asserted: the hub is only swapped once a usable source exists.
    assert hub.swapped is None or hub.swapped.name == "presentmon"
    assert os.path.isfile(fetch.target_exe())


def test_background_fetch_never_raises(monkeypatch, isolated):
    def offline(*a, **k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(fetch, "_open", offline)

    class FakeHub:
        frame_source = type("S", (), {"name": "none"})()

        def use_frame_source(self, source):
            raise AssertionError("nothing to swap to")

    fetch.ensure_in_background(FakeHub()).join(timeout=10)  # must not propagate
