"""The fx-autoconfig files that come with the program: checked before use, never downloaded.

Every way the folder can be wrong (a changed byte, a missing or swapped file, a link, an extra
file in the folder that is copied whole, a manifest that is broken or for another commit) must be a
coded error before anything is changed, never a traceback and never a half-done install.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from doctor_support import make_context
from support import needs_symlinks
from typer.testing import CliRunner

from peek_a_foxy import doctor, elevate, errors, loader
from peek_a_foxy.cli import app
from peek_a_foxy.loader import LoaderError

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "fx-autoconfig"


def load_updater():
    spec = importlib.util.spec_from_file_location(
        "update_loader", ROOT / "packaging" / "update_loader.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["update_loader"] = module
    spec.loader.exec_module(module)
    return module


updater = load_updater()
FILES = sorted(json.loads((REAL / "manifest.json").read_text())["files"])


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private copy of the real folder, which is what the loader looks at."""
    copy = tmp_path / "fx-autoconfig"
    shutil.copytree(REAL, copy)
    monkeypatch.setattr(loader, "bundled_dir", lambda: copy)
    return copy


def rewrite_manifest(bundle: Path, change) -> None:
    path = bundle / "manifest.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


# --- the real folder ----------------------------------------------------------------------------


def test_the_real_bundle_verifies():
    assert loader.verified_bundle() == REAL


def test_the_manifest_the_pins_and_the_script_agree():
    manifest = json.loads((REAL / "manifest.json").read_text())
    assert manifest["commit"] == loader.DEFAULT_COMMIT
    assert sorted(manifest["files"]) == sorted(updater.FILES)
    for name, digest in elevate.PINNED_SHA256.items():
        assert manifest["files"][f"program/{name}"] == digest
    assert manifest["repository"] == "https://github.com/MrOtherGuy/fx-autoconfig"


def test_the_licence_that_comes_with_the_files_is_there_and_is_the_mpl():
    text = (REAL / "LICENSE").read_text(encoding="utf-8")
    assert "Mozilla Public License" in text and "2.0" in text


def test_the_files_are_kept_with_lf_endings():
    """Adversarial: a CRLF copy of config.js (a Git for Windows setting) would reach Firefox."""
    for relative in FILES:
        assert b"\r" not in (REAL / relative).read_bytes(), relative
    attributes = (ROOT / ".gitattributes").read_text()
    assert "eol=lf" in attributes


def test_the_packaging_ships_the_folder():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert '"fx-autoconfig" = "peek_a_foxy/fx-autoconfig"' in pyproject
    workflow = (ROOT / ".github" / "workflows" / "exe.yml").read_text()
    assert "fx-autoconfig;peek_a_foxy/fx-autoconfig" in workflow


# --- a damaged folder ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative", FILES)
def test_a_changed_byte_in_any_file_is_refused(bundle: Path, relative: str):
    path = bundle / relative
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(LoaderError) as caught:
        loader.verified_bundle()
    assert caught.value.code is errors.CHECKOUT_MISMATCH and relative in caught.value.message


@pytest.mark.parametrize("relative", FILES)
def test_a_crlf_copy_of_any_file_is_refused(bundle: Path, relative: str):
    path = bundle / relative
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(LoaderError):
        loader.verified_bundle()


@pytest.mark.parametrize("relative", FILES)
def test_a_missing_empty_or_truncated_file_is_refused(bundle: Path, relative: str):
    path = bundle / relative
    original = path.read_bytes()
    for damaged in (None, b"", original[:-1], original + b"\n", b"\x00" * len(original)):
        if damaged is None:
            path.unlink()
        else:
            path.write_bytes(damaged)
        with pytest.raises(LoaderError):
            loader.verified_bundle()
    path.write_bytes(original)
    assert loader.verified_bundle() == bundle


def test_a_file_that_is_a_directory_is_refused(bundle: Path):
    target = bundle / "program" / "config.js"
    target.unlink()
    target.mkdir()
    with pytest.raises(LoaderError, match="not a plain file"):
        loader.verified_bundle()


def test_a_file_that_is_too_large_is_refused(bundle: Path):
    target = bundle / "profile" / "chrome" / "utils" / "boot.sys.mjs"
    target.write_bytes(target.read_bytes() + b"x" * (loader.MAX_LOADER_FILE + 1))
    with pytest.raises(LoaderError, match="too large"):
        loader.verified_bundle()


@needs_symlinks
@pytest.mark.parametrize("relative", FILES)
def test_a_link_in_place_of_a_file_is_refused(bundle: Path, tmp_path: Path, relative: str):
    outside = tmp_path / "outside"
    outside.write_bytes((bundle / relative).read_bytes())  # the same bytes: only the link is wrong
    (bundle / relative).unlink()
    (bundle / relative).symlink_to(outside)
    with pytest.raises(LoaderError, match="is a link"):
        loader.verified_bundle()


@pytest.mark.parametrize("kind", ["file", "directory", "empty file"])
def test_something_extra_in_the_folder_that_is_copied_whole_is_refused(bundle: Path, kind: str):
    """Adversarial: utils is copied as a whole, so a file nobody listed would be installed."""
    extra = bundle / "profile" / "chrome" / "utils" / "extra"
    if kind == "directory":
        extra.mkdir()
    else:
        extra.write_bytes(b"" if kind == "empty file" else b"evil();\n")
    with pytest.raises(LoaderError, match="does not name"):
        loader.verified_bundle()


@needs_symlinks
def test_a_link_inside_the_copied_folder_is_refused(bundle: Path, tmp_path: Path):
    (bundle / "profile" / "chrome" / "utils" / "link").symlink_to(tmp_path)
    with pytest.raises(LoaderError):
        loader.verified_bundle()


def test_an_extra_file_elsewhere_is_not_installed_and_does_not_matter(bundle: Path):
    """Only utils is copied whole; program/ files are copied by name."""
    (bundle / "program" / "note.txt").write_text("not installed")
    assert loader.verified_bundle() == bundle


# --- a broken manifest ----------------------------------------------------------------------------


def test_a_missing_manifest_means_no_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    monkeypatch.setattr(loader.Path, "resolve", lambda self, strict=False: self)
    monkeypatch.setattr(loader.resources, "files", lambda name: empty)
    monkeypatch.setattr(loader, "__file__", str(empty / "a" / "b" / "loader.py"))
    with pytest.raises(LoaderError, match="missing"):
        loader.bundled_dir()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "null",
        '{"commit": 1}',
        '{"files": []}',
        '{"files": {}}',
        "\x00",
        "{" * 5000,
    ],
    ids=["empty", "text", "list", "null", "no-files", "files-list", "no-commit", "nul", "deep"],
)
def test_a_broken_manifest_is_a_coded_error_not_a_crash(bundle: Path, text: str):
    (bundle / "manifest.json").write_text(text)
    with pytest.raises(LoaderError) as caught:
        loader.verified_bundle()
    assert caught.value.code is errors.CHECKOUT_MISMATCH


def test_a_manifest_that_is_not_utf8_is_a_coded_error(bundle: Path):
    (bundle / "manifest.json").write_bytes(b"\xff\xfe{")
    with pytest.raises(LoaderError):
        loader.verified_bundle()


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(commit="0" * 40),
        lambda d: d.update(commit=None),
        lambda d: d["files"].update({"program/config.js": "0" * 64}),
        lambda d: d["files"].update({"program/config.js": 5}),
        lambda d: d["files"].pop("program/config.js"),
        lambda d: d["files"].update({"../outside": "0" * 64}),
        lambda d: d["files"].update({"/etc/passwd": "0" * 64}),
        lambda d: d["files"].update({"profile/chrome/utils/../../../x": "0" * 64}),
        lambda d: d["files"].update({"nothing/here": "0" * 64}),
    ],
    ids=[
        "other-commit",
        "no-commit",
        "wrong-hash",
        "hash-not-text",
        "config-missing",
        "dot-dot",
        "absolute",
        "dot-dot-inside",
        "unknown-file",
    ],
)
def test_a_manifest_that_lies_is_refused(bundle: Path, change):
    rewrite_manifest(bundle, change)
    with pytest.raises(LoaderError) as caught:
        loader.verified_bundle()
    assert caught.value.code is errors.CHECKOUT_MISMATCH


def test_a_manifest_naming_a_file_that_is_listed_but_not_on_disk_is_refused(bundle: Path):
    rewrite_manifest(
        bundle, lambda d: d["files"].update({"profile/chrome/utils/ghost.mjs": "0" * 64})
    )
    with pytest.raises(LoaderError):
        loader.verified_bundle()


# --- using it -------------------------------------------------------------------------------------


def test_the_loader_files_are_the_verified_bundle_without_overrides_and_without_git(monkeypatch):
    monkeypatch.setattr(loader.shutil, "which", lambda name: None)  # no git on this machine
    with loader.loader_files() as folder:
        assert folder == REAL


def test_the_overrides_still_fetch_with_git(fxac_repo: Path):
    with loader.loader_files() as folder:
        assert (folder / "program" / "config.js").read_bytes() == b"// loader\n"
        assert folder != REAL


def test_an_override_with_a_bad_commit_is_still_refused(monkeypatch):
    monkeypatch.setenv("FXAC_COMMIT", "main")
    with pytest.raises(LoaderError, match="40"), loader.loader_files():
        pass


def test_a_damaged_bundle_stops_the_context_before_anything_is_yielded(bundle: Path):
    (bundle / "program" / "config.js").write_bytes(b"evil\n")
    entered = False
    with pytest.raises(LoaderError), loader.loader_files():
        entered = True
    assert not entered


# --- the update script ----------------------------------------------------------------------------

FAKE_COMMIT = "a" * 40


def fake_fetch(commit: str, path: str) -> bytes:
    return f"{commit}:{path}\n".encode()


def test_updating_writes_the_files_the_manifest_and_the_hashes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(updater, "fetch", fake_fetch)
    result = updater.update(FAKE_COMMIT, tmp_path)
    assert sorted(result["files"]) == sorted(updater.FILES) and result["commit"] == FAKE_COMMIT
    for relative in updater.FILES:
        data = (tmp_path / relative).read_bytes()
        assert data == fake_fetch(FAKE_COMMIT, relative)
        assert result["files"][relative] == updater.digest(data)
    assert json.loads((tmp_path / "manifest.json").read_text()) == result


def test_checking_finds_every_kind_of_difference(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(updater, "fetch", fake_fetch)
    updater.update(FAKE_COMMIT, tmp_path)
    assert updater.check(tmp_path) == []
    (tmp_path / "program" / "config.js").write_bytes(b"changed\n")
    (tmp_path / "LICENSE").unlink()
    data = json.loads((tmp_path / "manifest.json").read_text())
    data["files"]["profile/chrome/utils/fs.sys.mjs"] = "0" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(data))
    problems = "\\n".join(updater.check(tmp_path))
    assert "program/config.js: the file does not match" in problems
    assert "LICENSE: the file does not match" in problems
    assert "fs.sys.mjs: the manifest does not match" in problems


@pytest.mark.parametrize(
    "commit", ["main", "v1.0", "abc", "A" * 40, "a" * 39, "a" * 41, "-" * 40, "", "a" * 40 + "\\n"]
)
def test_the_script_refuses_anything_but_a_full_lowercase_hash(commit: str):
    with pytest.raises(SystemExit):
        updater.fetch(commit, "LICENSE")
    assert updater.main([commit]) == 2


def test_the_script_without_arguments_says_how_to_use_it(capsys):
    assert updater.main([]) == 2
    assert "update_loader.py COMMIT" in capsys.readouterr().out


def test_a_file_that_is_too_large_upstream_is_refused(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b"x" * limit

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda url, timeout: Response())
    with pytest.raises(SystemExit, match="larger"):
        updater.fetch(FAKE_COMMIT, "LICENSE")


def test_crlf_from_upstream_is_stored_as_lf(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b"a\r\nb\r\n"

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda url, timeout: Response())
    assert updater.fetch(FAKE_COMMIT, "LICENSE") == b"a\nb\n"


def test_the_doctor_passes_the_real_files(tmp_path: Path):
    """The doctor's own test module pins fake hashes, so the real check lives here."""
    check = doctor._loader_files_check(make_context(tmp_path, loader_files=loader.verified_bundle))
    assert check.status == "ok" and loader.DEFAULT_COMMIT[:10] in check.value


runner = CliRunner()


def test_a_full_install_needs_no_git_and_copies_the_bundled_files(
    profile: Path, firefox_dir: Path, monkeypatch
):
    """Default path: no overrides and no git on the machine; every file reaches its place intact."""
    monkeypatch.setattr(loader.shutil, "which", lambda name: None)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert result.exit_code == 0, result.output
    for name in loader.LOADER_FILES:
        assert (firefox_dir / name).read_bytes() == (REAL / "program" / name).read_bytes()
    utils = REAL / "profile" / "chrome" / "utils"
    copied = profile / "chrome" / "utils"
    assert sorted(path.name for path in copied.iterdir()) == sorted(
        path.name for path in utils.iterdir()
    )
    for path in utils.iterdir():
        assert (copied / path.name).read_bytes() == path.read_bytes()


def test_a_damaged_bundle_stops_the_install_before_anything_changes(
    bundle: Path, profile: Path, firefox_dir: Path
):
    """Adversarial: the first step fails, so the profile and Firefox's folder are untouched."""
    (bundle / "program" / "config.js").write_bytes(b"evil();\n")
    before = sorted(path.relative_to(profile).as_posix() for path in profile.rglob("*"))
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert result.exit_code == 1 and "PAF-204" in result.output
    assert sorted(path.relative_to(profile).as_posix() for path in profile.rglob("*")) == before
    assert not (firefox_dir / "config.js").exists()
