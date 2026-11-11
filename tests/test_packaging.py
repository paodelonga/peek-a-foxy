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


def test_the_scoop_manifest_points_at_the_release_asset_and_needs_nothing_else(tmp_path):
    load_renderer().render("0.3.0", DIGEST, tmp_path)
    manifest = json.loads((tmp_path / "peek-a-foxy.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.3.0"
    assert manifest["url"].endswith("/releases/download/v0.3.0/peek-a-foxy.exe")
    assert manifest["hash"] == DIGEST
    assert "depends" not in manifest
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
    assert "Dependencies" not in installer and "InstallerType: portable" in installer


@pytest.mark.parametrize(
    ("version", "digest"),
    [("v0.3.0", DIGEST), ("0.3", DIGEST), ("0.3.0", "abc"), ("0.3.0", "zz" * 32)],
)
def test_bad_versions_and_hashes_are_refused(tmp_path, version, digest):
    with pytest.raises(ValueError):
        load_renderer().render(version, digest, tmp_path)
    assert not list(tmp_path.iterdir())


def test_the_filled_in_winget_files_are_yaml_with_the_values_as_text(tmp_path):
    """The templates are left out of the YAML check (``@VERSION@`` cannot start a value), so the
    files they become are checked here, with the types winget reads."""
    yaml = pytest.importorskip("yaml")
    load_renderer().render("0.3.0", DIGEST, tmp_path)
    for path in tmp_path.glob("*.yaml"):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert manifest["PackageVersion"] == "0.3.0", path.name
        assert manifest["PackageIdentifier"] == "paodelonga.PeekAFoxy"
    installer = yaml.safe_load(
        (tmp_path / "paodelonga.PeekAFoxy.installer.yaml").read_text(encoding="utf-8")
    )
    assert installer["Installers"][0]["InstallerSha256"] == DIGEST.upper()


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


def test_the_build_provenance_is_signed_by_a_job_of_its_own_on_a_release_only():
    workflow = exe_workflow()
    jobs = workflow["jobs"]
    attest = jobs["attest"]
    assert attest["if"] == "github.event_name == 'release'"
    assert attest["needs"] == "build"
    # The signing token exists in this job and nowhere else; the build job runs third-party code.
    assert attest["permissions"] == {
        "id-token": "write",
        "attestations": "write",
        "contents": "read",
    }
    others = [name for name in jobs if name != "attest"]
    for name in others:
        granted = jobs[name].get("permissions", {})
        assert "id-token" not in granted and "attestations" not in granted, name
    assert (
        "id-token" not in workflow["permissions"] and "attestations" not in workflow["permissions"]
    )
    # Nothing is published unless the attestation succeeded.
    assert set(jobs["publish"]["needs"]) == {"build", "attest"}
    action = [
        s for s in attest["steps"] if str(s.get("uses", "")).startswith("actions/attest-build")
    ]
    assert len(action) == 1
    assert action[0]["with"] == {"subject-path": "dist/peek-a-foxy.exe"}
    # ...and the file it signs is the one the build job uploaded.
    download = [s for s in attest["steps"] if "download-artifact" in str(s.get("uses", ""))]
    upload = [s for s in jobs["build"]["steps"] if "upload-artifact" in str(s.get("uses", ""))]
    assert download[0]["with"]["name"] == upload[0]["with"]["name"]
    assert download[0]["with"]["path"] == "dist"


def test_every_job_that_checks_out_keeps_the_token_out_of_the_git_configuration():
    for name, job in exe_workflow()["jobs"].items():
        for item in job["steps"]:
            if str(item.get("uses", "")).startswith("actions/checkout@"):
                assert item["with"]["persist-credentials"] is False, name


# --- the lock of the build tools (PF-19) ---------------------------------------------------------

LOCK = PACKAGING / "requirements-build.txt"
LOCK_INPUT = PACKAGING / "requirements-build.in"
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[0-9][^\s;\\]*)")
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def lock_entries() -> dict[str, tuple[str, list[str], str]]:
    """Name to (version, hashes, the whole entry) for every requirement of the lock."""
    entries: dict[str, tuple[str, list[str], str]] = {}
    block: list[str] = []

    def close() -> None:
        if not block:
            return
        text = "\n".join(block)
        match = REQUIREMENT.match(block[0])
        assert match, f"not a pinned requirement: {block[0]!r}"
        name = re.sub(r"[-_.]+", "-", match["name"]).lower()
        assert name not in entries, f"{name} is locked twice"
        entries[name] = (match["version"], HASH.findall(text), text)
        block.clear()

    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t":
            close()
        block.append(line)
    close()
    return entries


def test_every_requirement_of_the_lock_is_pinned_exactly_and_has_hashes():
    entries = lock_entries()
    assert len(entries) > 10  # PyInstaller, its helpers, Typer, Rich and what they need
    for name, (version, hashes, text) in entries.items():
        assert hashes, f"{name} has no hash, so pip --require-hashes would refuse the file"
        assert len(set(hashes)) == len(hashes), name
        assert not re.search(r"\bhttps?://|git\+|\s@\s|--index-url|--find-links|^-e\b", text), name
        assert "==" in text.split("\n", 1)[0] and not re.search(r"[<>~!]=?", version), name


def test_the_lock_has_no_line_that_pip_would_read_as_something_else_than_a_hashed_pin():
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert stripped.startswith("--hash=sha256:") or REQUIREMENT.match(stripped), line


def test_the_lock_holds_the_tools_the_build_names_and_the_runtime_dependencies():
    entries = lock_entries()
    wanted = re.findall(r"^pyinstaller==(\S+)$", LOCK_INPUT.read_text(encoding="utf-8"), re.M)
    assert wanted and entries["pyinstaller"][0] == wanted[0]
    assert "hatchling" in entries  # --no-build-isolation: the backend must come from the lock
    from packaging.requirements import Requirement

    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    runtime = project.split("dependencies = [", 1)[1].split("]", 1)[0]
    declared = [Requirement(text) for text in re.findall(r'^\s*"([^"]+)",?', runtime, re.M)]
    assert {r.name for r in declared} == {"typer", "rich"}
    for requirement in declared:
        locked = entries[requirement.name][0]
        assert requirement.specifier.contains(locked), (
            f"{requirement.name} {locked} is outside what pyproject.toml allows: "
            "regenerate the lock (command in its header)"
        )


def test_the_lock_says_how_to_regenerate_it_and_the_build_installs_only_from_it():
    header = "\n".join(LOCK.read_text(encoding="utf-8").splitlines()[:3])
    assert "uv pip compile" in header and "--generate-hashes" in header
    assert "pyproject.toml packaging/requirements-build.in" in header
    assert "uv pip compile" in LOCK_INPUT.read_text(encoding="utf-8")
    install = step(exe_workflow()["jobs"]["build"], "Install")["run"]
    assert "pip install --require-hashes --no-deps -r packaging/requirements-build.txt" in install
    # The project is built from the checkout, with nothing fetched by pip.
    assert "--no-deps --no-build-isolation --no-index ." in install
    assert "pyinstaller==" not in install  # the version lives in one place: the lock


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
