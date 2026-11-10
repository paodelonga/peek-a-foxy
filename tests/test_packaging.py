"""The release packaging: manifests filled from templates, and the workflow that builds the exe."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
SOURCE = ROOT / "src" / "peek_a_foxy"
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


# --- what PyInstaller cannot see (PF-24) ---------------------------------------------------------


def exe_workflow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / ".github/workflows/exe.yml").read_text(encoding="utf-8"))


def step(job: dict, name_start: str) -> dict:
    found = [s for s in job["steps"] if str(s.get("name", "")).startswith(name_start)]
    assert len(found) == 1, f"expected exactly one step starting with {name_start!r}"
    return found[0]


def hidden_imports() -> set[str]:
    command = step(exe_workflow()["jobs"]["build"], "Build")["run"]
    return set(re.findall(r"--hidden-import\s+(\S+)", command))


def named_imports() -> tuple[set[str], list[str]]:
    """Modules the package imports by a string (import_module, __import__), and the odd calls."""
    constant: set[str] = set()
    dynamic: list[str] = []
    for path in sorted(SOURCE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.attr
                if isinstance(function, ast.Attribute)
                else getattr(function, "id", "")
            )
            if name not in {"import_module", "__import__"}:
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                constant.add(first.value)
            else:
                dynamic.append(f"{path.name}:{node.lineno}")
    return constant, dynamic


def test_every_module_the_package_imports_by_name_is_a_hidden_import_of_the_build():
    constant, dynamic = named_imports()
    assert "winreg" in constant  # the one that matters: Firefox discovery through the registry
    assert constant <= hidden_imports(), "a module imported by name is invisible to PyInstaller"
    assert not dynamic, f"an import by a computed name cannot be checked: {dynamic}"


def test_the_build_bundles_the_package_metadata_that_the_version_comes_from():
    command = step(exe_workflow()["jobs"]["build"], "Build")["run"]
    assert "--copy-metadata peek-a-foxy" in command
    source = (SOURCE / "__init__.py").read_text(encoding="utf-8")
    assert 'version("peek-a-foxy")' in source  # what makes the metadata necessary


def test_the_smoke_test_proves_registry_discovery_and_the_version_and_cannot_be_ignored():
    job = exe_workflow()["jobs"]["build"]
    names = [s.get("name", "") for s in job["steps"]]
    smoke = step(job, "Smoke test - registry")
    assert names.index(smoke["name"]) > names.index("Build")
    assert names.index(smoke["name"]) < names.index("Checksum")  # before anything is uploaded
    assert not smoke.get("continue-on-error")
    script = smoke["run"]
    for needed in ("doctor --json", "HKCU:", "program.version", "firefox.path", "pyproject.toml"):
        assert needed in script
    # The registration is private to the run and removed even when the check throws.
    assert re.search(r"finally\s*\{[^}]*Remove-Item", script)
