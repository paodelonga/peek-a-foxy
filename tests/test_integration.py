"""Checks against the real fx-autoconfig repository. Opt-in: ``pytest -m network``."""

import json
import subprocess

import pytest

from peek_a_foxy import loader

pytestmark = pytest.mark.network


def test_the_pinned_commit_exists_upstream_and_has_the_files_we_install(monkeypatch):
    # Guards against the upstream repository being rewritten or reorganized.
    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)
    with loader.fetch_loader() as checkout:
        for name in loader.LOADER_FILES:
            assert (checkout / "program" / name).is_file()
        assert (checkout / "profile" / "chrome" / "utils" / "boot.sys.mjs").is_file()
        assert "userchromejs" in (checkout / "program" / "config.js").read_text()


def test_github_serves_the_pinned_commit_without_its_history(monkeypatch):
    # If this fails, the shallow fetch by hash no longer works and the loader silently falls back to
    # cloning the whole history: still correct, but slow.
    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)
    with loader.fetch_loader() as checkout:
        count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    assert count == "1"


def test_the_pinned_hashes_of_the_administrator_copy_match_the_real_files(monkeypatch):
    # Bump elevate.PINNED_SHA256 together with loader.DEFAULT_COMMIT; line endings must be LF.
    import hashlib

    from peek_a_foxy import elevate

    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)
    with loader.fetch_loader() as checkout:
        for name, digest in elevate.PINNED_SHA256.items():
            data = (checkout / "program" / name).read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest, name


def test_the_files_that_come_with_the_program_are_the_ones_upstream_at_the_pinned_commit(
    monkeypatch,
):
    # The bundled folder is a copy of these files: if upstream was rewritten, or the copy was
    # edited, this says so (packaging/update_loader.py --check does the same without git).
    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)
    root = loader.bundled_dir()
    with loader.fetch_loader() as checkout:
        for relative in json.loads((root / "manifest.json").read_text())["files"]:
            assert (root / relative).read_bytes() == (checkout / relative).read_bytes(), relative


def test_the_update_script_agrees_that_the_bundled_files_are_genuine():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "packaging" / "update_loader.py"
    spec = importlib.util.spec_from_file_location("update_loader_network", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check() == []
