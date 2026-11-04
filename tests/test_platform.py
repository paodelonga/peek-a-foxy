"""OS-specific path logic, exercised by faking the platform so it runs everywhere."""

import os
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


@pytest.mark.parametrize("name", ["cygwin", "msys", "freebsd14", "sunos5"])
def test_other_platforms_are_rejected_clearly(monkeypatch, name):
    monkeypatch.setattr(sys, "platform", name)
    with pytest.raises(platform.UnsupportedPlatformError, match="Linux, macOS and Windows"):
        platform.system()


def test_windows_is_a_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert platform.system() == "windows"


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


# --- Windows -----------------------------------------------------------------------------------


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pretend to be Windows with empty well-known folders under ``tmp_path``; returns its root."""
    monkeypatch.setattr(sys, "platform", "win32")
    for variable in (
        "ProgramFiles",
        "ProgramW6432",
        "ProgramFiles(x86)",
        "LOCALAPPDATA",
        "APPDATA",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(platform.shutil, "which", lambda name: None)
    monkeypatch.setattr(platform, "_winreg", lambda: FakeWinreg({}))
    return tmp_path


def firefox_install(directory: Path) -> Path:
    directory.mkdir(parents=True)
    (directory / "omni.ja").touch()
    (directory / "firefox.exe").touch()
    return directory


class FakeWinreg:
    """Just enough of ``winreg`` for the registry walk: a dict of key path -> values and subkeys.

    ``tree`` maps ``(hive, view, path)`` to ``{"values": {...}}``; subkeys come from the paths.
    """

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200

    def __init__(self, tree: dict[tuple[str, int, str], dict[str, object]]) -> None:
        self.tree = {(hive, view, path.lower()): data for (hive, view, path), data in tree.items()}
        self.names = {(hive, view, path.lower()): path for (hive, view, path) in tree}

    def _exists(self, hive: str, view: int, path: str) -> bool:
        wanted = path.lower().rstrip("\\")
        return any(
            h == hive and v == view and (p == wanted or p.startswith(wanted + "\\"))
            for h, v, p in self.tree
        )

    def OpenKey(self, hive, path, reserved, access):  # noqa: N802
        view = access & (self.KEY_WOW64_64KEY | self.KEY_WOW64_32KEY)
        if not self._exists(hive, view, path):
            raise FileNotFoundError(2, "not found")
        return (hive, view, path)

    def EnumKey(self, key, index):  # noqa: N802
        hive, view, path = key
        prefix = path.lower().rstrip("\\") + "\\"
        children = []
        for h, v, p in self.tree:
            if h == hive and v == view and p.startswith(prefix):
                name = self.names[(h, v, p)][len(prefix) :].split("\\")[0]
                if name not in children:
                    children.append(name)
        if index >= len(children):
            raise OSError(259, "no more data")
        return children[index]

    def QueryValueEx(self, key, name):  # noqa: N802
        hive, view, path = key
        values = self.tree.get((hive, view, path.lower()), {}).get("values", {})
        if name not in values:
            raise FileNotFoundError(2, "no such value")
        return values[name], 1

    def CloseKey(self, key):  # noqa: N802
        pass


def reg(*entries):
    """``reg(("HKLM", 64, r"SOFTWARE\\x", {"v": "1"}), ...)`` -> a FakeWinreg."""
    sizes = {64: FakeWinreg.KEY_WOW64_64KEY, 32: FakeWinreg.KEY_WOW64_32KEY}
    return FakeWinreg(
        {(hive, sizes[bits], path): {"values": values} for hive, bits, path, values in entries}
    )


MOZ = r"SOFTWARE\Mozilla\Mozilla Firefox\159.0 (x64 en-US)\Main"
APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"


def test_profiles_root_windows_uses_appdata(windows, monkeypatch):
    monkeypatch.setenv("APPDATA", str(windows / "Roaming"))
    assert platform.profiles_root() == windows / "Roaming" / "Mozilla" / "Firefox"


def test_profiles_root_windows_falls_back_to_the_home_folder(windows, monkeypatch):
    fake_home(monkeypatch, windows)
    assert platform.profiles_root() == windows / "AppData" / "Roaming" / "Mozilla" / "Firefox"


def test_the_registry_install_directory_is_found(windows, monkeypatch):
    ff = firefox_install(windows / "pf" / "Mozilla Firefox")
    registry = reg(("HKLM", 64, MOZ, {"Install Directory": str(ff)}))
    monkeypatch.setattr(platform, "_winreg", lambda: registry)
    assert platform.firefox_dir_candidates() == [ff]


def test_path_to_exe_and_app_paths_are_used_too_and_quotes_and_variables_are_cleaned(
    windows, monkeypatch
):
    one = firefox_install(windows / "one")
    two = firefox_install(windows / "two")
    monkeypatch.setenv("FF_ROOT", str(windows))
    registry = reg(
        ("HKLM", 64, MOZ, {"PathToExe": f'"{one / "firefox.exe"}"'}),
        ("HKLM", 32, APP_PATHS, {"": r"%FF_ROOT%" + os.sep + "two" + os.sep + "firefox.exe"}),
    )
    monkeypatch.setattr(platform, "_winreg", lambda: registry)
    assert platform.firefox_dir_candidates() == [one, two]


def test_other_brands_and_the_per_user_hive_are_read(windows, monkeypatch):
    dev = firefox_install(windows / "dev")
    user = firefox_install(windows / "user")
    registry = reg(
        (
            "HKLM",
            64,
            r"SOFTWARE\Mozilla\Firefox Developer Edition\160.0b1\Main",
            {"Install Directory": str(dev)},
        ),
        (
            "HKCU",
            64,
            r"SOFTWARE\Mozilla\Mozilla Firefox\159.0\Main",
            {"Install Directory": str(user)},
        ),
    )
    monkeypatch.setattr(platform, "_winreg", lambda: registry)
    assert platform.firefox_dir_candidates() == [dev, user]


def test_the_32_bit_view_is_read_and_the_same_folder_is_listed_once(windows, monkeypatch):
    ff = firefox_install(windows / "ff")
    registry = reg(
        ("HKLM", 64, MOZ, {"Install Directory": str(ff)}),
        ("HKLM", 32, MOZ, {"Install Directory": str(ff).upper() if os.name == "nt" else str(ff)}),
        ("HKLM", 32, APP_PATHS, {"": str(ff / "firefox.exe")}),
    )
    monkeypatch.setattr(platform, "_winreg", lambda: registry)
    assert platform.firefox_dir_candidates() == [ff]


def test_thunderbird_and_stale_registry_entries_are_ignored(windows, monkeypatch):
    mail = windows / "Mozilla Thunderbird"
    mail.mkdir()
    (mail / "omni.ja").touch()  # same file as Firefox has, but no firefox.exe
    no_omni = windows / "half"
    no_omni.mkdir()
    (no_omni / "firefox.exe").touch()
    registry = reg(
        (
            "HKLM",
            64,
            r"SOFTWARE\Mozilla\Mozilla Thunderbird\140.0\Main",
            {"Install Directory": str(mail)},
        ),
        ("HKLM", 64, MOZ, {"Install Directory": str(no_omni)}),
        ("HKLM", 64, r"SOFTWARE\Mozilla\Gone\1\Main", {"Install Directory": str(windows / "nope")}),
        (
            "HKLM",
            64,
            r"SOFTWARE\Mozilla\Blank\1\Main",
            {"Install Directory": "   ", "PathToExe": 5},
        ),
    )
    monkeypatch.setattr(platform, "_winreg", lambda: registry)
    assert platform.firefox_dir_candidates() == []


def test_well_known_folders_are_used_without_a_registry(windows, monkeypatch):
    program_files = windows / "Program Files"
    release = firefox_install(program_files / "Mozilla Firefox")
    nightly = firefox_install(windows / "Local" / "Firefox Nightly")
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("LOCALAPPDATA", str(windows / "Local"))

    def no_registry():
        raise ImportError("no winreg here")

    monkeypatch.setattr(platform, "_winreg", no_registry)
    assert platform.firefox_dir_candidates() == [release, nightly]


def test_the_registry_comes_first_then_folders_then_path(windows, monkeypatch):
    registered = firefox_install(windows / "registered")
    guessed = firefox_install(windows / "pf" / "Mozilla Firefox")
    portable = firefox_install(windows / "portable")
    monkeypatch.setenv("ProgramFiles", str(windows / "pf"))
    registry = reg(("HKLM", 64, MOZ, {"Install Directory": str(registered)}))
    monkeypatch.setattr(platform, "_winreg", lambda: registry)
    monkeypatch.setattr(platform.shutil, "which", lambda name: str(portable / "firefox.exe"))
    assert platform.firefox_dir_candidates() == [registered, guessed, portable]


def test_a_registry_that_cannot_be_opened_is_not_fatal(windows, monkeypatch):
    class Locked(FakeWinreg):
        def OpenKey(self, *args):  # noqa: N802
            raise PermissionError(5, "access denied")

    ff = firefox_install(windows / "pf" / "Mozilla Firefox")
    monkeypatch.setenv("ProgramFiles", str(windows / "pf"))
    monkeypatch.setattr(platform, "_winreg", lambda: Locked({}))
    assert platform.firefox_dir_candidates() == [ff]


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (
            r"C:\Program Files\WindowsApps\Mozilla.Firefox_159.0.0.0_x64__n80bbvh6b1yt8\VFS",
            "Microsoft",
        ),
        ("C:/Program Files/WINDOWSAPPS/Mozilla.Firefox", "Microsoft"),
        ("C:/Program Files/Mozilla Firefox", None),
        ("C:/Users/me/WindowsApps2/firefox", None),  # only a folder with that exact name counts
    ],
)
def test_microsoft_store_builds_are_recognised(path, kind):
    found = platform.sandbox_kind(Path(path))
    assert (found is None) if kind is None else (found and found.startswith(kind))


def test_each_sandbox_is_named():
    assert platform.sandbox_kind(Path("/snap/firefox/current")) == "Snap"
    assert platform.sandbox_kind(Path("/var/lib/flatpak/app/x")) == "Flatpak"
