from pathlib import Path

import pytest

from peek_a_foxy import assets, errors
from peek_a_foxy.errors import PlatformError


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
    with pytest.raises(PlatformError) as caught:
        assets.assets_dir()
    assert caught.value.code is errors.FILES_MISSING


def test_installed_files_match_the_repository_sources():
    chrome = Path(__file__).resolve().parents[1] / "chrome"
    assert (chrome / "autohide.css").read_bytes() == (
        assets.assets_dir() / "autohide.css"
    ).read_bytes()


def test_an_installed_package_uses_the_assets_it_carries(monkeypatch, tmp_path):
    packaged = tmp_path / "pkg"
    (packaged / "assets").mkdir(parents=True)
    (packaged / "assets" / assets.CSS_NAME).write_text("/* wheel */")
    monkeypatch.setattr(assets.resources, "files", lambda name: packaged)
    assert assets.assets_dir() == packaged / "assets"


def test_the_version_falls_back_when_the_package_is_not_installed(monkeypatch):
    import importlib
    import importlib.metadata

    import peek_a_foxy

    def not_installed(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", not_installed)
    try:
        importlib.reload(peek_a_foxy)
        assert peek_a_foxy.__version__ == "0.0.0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(peek_a_foxy)
