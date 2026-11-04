"""The release packaging: manifests filled from templates, and the workflow that builds the exe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIGEST = "ab" * 32

pytestmark = pytest.mark.skipif(not PACKAGING.is_dir(), reason="not a source checkout")


def load_renderer():
    spec = importlib.util.spec_from_file_location(
        "render_manifests", PACKAGING / "render_manifests.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_scoop_manifest_points_at_the_release_asset_and_needs_git(tmp_path):
    load_renderer().render("0.3.0", DIGEST, tmp_path)
    manifest = json.loads((tmp_path / "peek-a-foxy.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.3.0"
    assert manifest["url"].endswith("/releases/download/v0.3.0/peek-a-foxy.exe")
    assert manifest["hash"] == DIGEST
    assert manifest["depends"] == "git"
    assert manifest["bin"] == "peek-a-foxy.exe"
    assert manifest["autoupdate"]["hash"]["url"] == "$url.sha256"


def test_the_winget_files_share_one_identifier_version_and_upper_case_hash(tmp_path):
    load_renderer().render("0.3.0", DIGEST, tmp_path)
    texts = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.glob("*.yaml")}
    assert len(texts) == 3
    for text in texts.values():
        assert "PackageIdentifier: paodelonga.PeekAFoxy" in text
        assert "PackageVersion: 0.3.0" in text
        assert "@VERSION@" not in text
    installer = texts["paodelonga.PeekAFoxy.installer.yaml"]
    assert f"InstallerSha256: {DIGEST.upper()}" in installer
    assert "PackageIdentifier: Git.Git" in installer and "InstallerType: portable" in installer


@pytest.mark.parametrize(
    ("version", "digest"),
    [("v0.3.0", DIGEST), ("0.3", DIGEST), ("0.3.0", "abc"), ("0.3.0", "zz" * 32)],
)
def test_bad_versions_and_hashes_are_refused(tmp_path, version, digest):
    with pytest.raises(ValueError):
        load_renderer().render(version, digest, tmp_path)
    assert not list(tmp_path.iterdir())


def test_no_placeholder_is_left_in_any_output(tmp_path):
    for path in load_renderer().render("1.2.3", DIGEST, tmp_path):
        assert "@VERSION@" not in path.read_text(encoding="utf-8")
        assert "@SHA256" not in path.read_text(encoding="utf-8")


def test_the_installer_script_never_needs_administrator_rights():
    script = (PACKAGING / "install.ps1").read_text(encoding="utf-8")
    assert "Get-FileHash" in script  # the download is checked before anything is installed
    body = script.split("#>", 1)[1]  # the help text mentions `irm | iex`; the code must not
    for forbidden in ("RunAs", "Start-Process", "HKLM", "Machine", "Invoke-Expression", "iex"):
        assert forbidden not in body


def test_the_exe_workflow_only_publishes_on_a_release_and_only_there_writes():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/exe.yml").read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    publish = workflow["jobs"]["publish"]
    assert publish["if"] == "github.event_name == 'release'"
    assert publish["permissions"] == {"contents": "write"}
    assert "permissions" not in workflow["jobs"]["build"]
