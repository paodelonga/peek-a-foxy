from pathlib import Path

import pytest

from peek_a_foxy import assets


def test_assets_are_found():
    directory = assets.assets_dir()
    assert (directory / assets.CSS_NAME).is_file()
    assert (directory / "JS" / assets.SCRIPT_NAME).is_file()


def test_falls_back_to_the_checkout_and_fails_clearly_when_nothing_is_there(monkeypatch, tmp_path):
    empty = tmp_path / "pkg"
    empty.mkdir()
    monkeypatch.setattr(assets.resources, "files", lambda name: empty)
    assert (assets.assets_dir() / assets.CSS_NAME).is_file()  # the repo's chrome/ directory
    monkeypatch.setattr(assets, "__file__", str(tmp_path / "a" / "b" / "assets.py"))
    with pytest.raises(FileNotFoundError):
        assets.assets_dir()


def test_installed_files_match_the_repository_sources():
    chrome = Path(__file__).resolve().parents[1] / "chrome"
    assert (chrome / "autohide.css").read_bytes() == (
        assets.assets_dir() / "autohide.css"
    ).read_bytes()
