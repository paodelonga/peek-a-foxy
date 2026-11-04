"""OS-specific path logic, exercised by faking the platform so it runs everywhere."""

import sys
from pathlib import Path

import pytest
from support import needs_symlinks

from peek_a_foxy import platform


def fake_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


def test_profiles_root_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    fake_home(monkeypatch, tmp_path)
    assert platform.profiles_root() == tmp_path / ".mozilla" / "firefox"


def test_profiles_root_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    fake_home(monkeypatch, tmp_path)
    assert platform.profiles_root() == tmp_path / "Library" / "Application Support" / "Firefox"


@pytest.mark.parametrize("name", ["win32", "cygwin", "freebsd14"])
def test_other_platforms_are_rejected_clearly(monkeypatch, name):
    monkeypatch.setattr(sys, "platform", name)
    with pytest.raises(platform.UnsupportedPlatformError, match="Linux and macOS"):
        platform.system()


def _install(root: Path, *parts: str) -> Path:
    directory = root.joinpath(*parts)
    directory.mkdir(parents=True)
    (directory / "omni.ja").touch()
    return directory


def test_linux_candidates_come_from_path_first_then_known_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    on_path = _install(tmp_path, "opt-ff")
    known = _install(tmp_path, "usr-lib-firefox")
    _install(tmp_path, "no-omni-parent")  # has omni.ja
    (tmp_path / "empty").mkdir()  # no omni.ja: must be ignored
    binary = on_path / "firefox"
    binary.touch()
    monkeypatch.setattr(
        platform.shutil, "which", lambda name: str(binary) if name == "firefox" else None
    )
    monkeypatch.setattr(platform, "LINUX_INSTALL_DIRS", (str(known), str(tmp_path / "empty")))
    assert platform.firefox_dir_candidates() == [on_path, known]


def test_candidates_are_deduplicated(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    directory = _install(tmp_path, "ff")
    (directory / "firefox").touch()
    monkeypatch.setattr(platform.shutil, "which", lambda name: str(directory / "firefox"))
    monkeypatch.setattr(platform, "LINUX_INSTALL_DIRS", (str(directory),))
    assert platform.firefox_dir_candidates() == [directory]


@needs_symlinks
def test_a_symlinked_binary_resolves_to_the_real_install(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    real = _install(tmp_path, "lib", "firefox")
    (real / "firefox").touch()
    link = tmp_path / "bin" / "firefox"
    link.parent.mkdir()
    link.symlink_to(real / "firefox")
    monkeypatch.setattr(platform.shutil, "which", lambda name: str(link))
    monkeypatch.setattr(platform, "LINUX_INSTALL_DIRS", ())
    assert platform.firefox_dir_candidates() == [real.resolve()]


def test_macos_candidates_are_the_app_resources(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    stable = _install(tmp_path, "Firefox.app", "Contents", "Resources")
    (tmp_path / "Nightly.app").mkdir()  # not installed: no omni.ja
    monkeypatch.setattr(
        platform, "MACOS_APPS", (str(tmp_path / "Firefox.app"), str(tmp_path / "Nightly.app"))
    )
    assert platform.firefox_dir_candidates() == [stable]


def test_nothing_found_gives_an_empty_list(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform.shutil, "which", lambda name: None)
    monkeypatch.setattr(platform, "LINUX_INSTALL_DIRS", (str(tmp_path / "nope"),))
    assert platform.firefox_dir_candidates() == []


@pytest.mark.parametrize(
    ("path", "sandboxed"),
    [
        ("/snap/firefox/current/usr/lib/firefox", True),
        ("/var/lib/flatpak/app/org.mozilla.firefox/x86_64", True),
        ("/home/me/.local/share/flatpak/app/org.mozilla.firefox", True),
        ("/usr/lib/firefox", False),
        ("/opt/snapshots/firefox", False),  # "snap" only as part of another word
    ],
)
def test_sandboxed_installs_are_detected(path, sandboxed):
    assert platform.is_sandboxed(Path(path)) is sandboxed
