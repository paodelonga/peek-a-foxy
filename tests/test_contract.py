"""What the Python side and the Firefox script must agree on, checked against the real files."""

from __future__ import annotations

import re
from pathlib import Path

from peek_a_foxy import cli, errors, report, status, userfiles
from peek_a_foxy.assets import FILES, MODULE_NAME, PREFS_SCRIPT_NAME, SCRIPT_NAME, assets_dir

ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (assets_dir() / name).read_text(encoding="utf-8")


def test_the_pref_names_in_python_are_the_ones_the_script_registers():
    module = source(f"resources/{MODULE_NAME}")
    in_module = set(re.findall(r'name: "(peekafoxy\.[A-Za-z.]+)"', module))
    assert in_module == set(userfiles.OWN_PREFS)


def test_the_scripts_use_no_pref_name_the_module_does_not_know():
    module_names = set(userfiles.OWN_PREFS)
    for name in (f"JS/{SCRIPT_NAME}", f"JS/{PREFS_SCRIPT_NAME}"):
        assert set(re.findall(r'"(peekafoxy\.[A-Za-z.]+)"', source(name))) <= module_names, name


def test_the_legacy_prefs_map_onto_current_names():
    assert set(userfiles.LEGACY_PREFS.values()) <= set(userfiles.OWN_PREFS)


def test_the_default_shortcuts_the_cli_announces_are_the_ones_in_the_module():
    module = source(f"resources/{MODULE_NAME}")
    defaults = re.findall(
        r'name: "peekafoxy\.\w+\.shortcut", type: "string", default: "([^"]+)"', module
    )
    assert sorted(defaults) == sorted([cli.TABS_SHORTCUT, cli.URLBAR_SHORTCUT])


def test_every_installed_file_exists_in_the_sources():
    for name in FILES:
        assert (assets_dir() / name).is_file(), name


def _variables(text: str) -> dict[str, str]:
    return {
        name: " ".join(value.split())
        for name, value in re.findall(r"(--autohide-[a-z-]+):\s*([^;]+);", text)
    }


def test_the_readmes_css_example_shows_the_real_defaults():
    root = ROOT
    css = (assets_dir() / "autohide.css").read_text(encoding="utf-8")
    real = _variables(css.split(":root {")[1].split("}")[0])  # the defaults, not the overrides
    assert len(real) == 8
    for name in ("README.md", "README.pt-BR.md"):
        text = (root / name).read_text(encoding="utf-8")
        blocks = [b for b in text.split("```css")[1:] if "--autohide-strip:" in b.split("```")[0]]
        example = blocks[0].split("```")[0]
        assert _variables(example) == real, name


def _module_constant(name: str) -> str:
    match = re.search(rf'export const {name} = "([^"]*)";', source(f"resources/{MODULE_NAME}"))
    assert match, f"{name} is not exported by the module"
    return match.group(1)


def test_the_script_version_is_the_package_version():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert version
    assert _module_constant("SCRIPT_VERSION") == version.group(1)


def test_the_status_file_the_script_writes_is_the_one_the_doctor_reads():
    assert _module_constant("STATUS_FILE") == status.STATUS_FILE
    module = source(f"resources/{MODULE_NAME}")
    assert f"export const STATUS_SCHEMA = {status.STATUS_SCHEMA};" in module


def test_the_issue_link_and_the_notice_are_the_ones_of_the_doctor_report():
    assert _module_constant("ISSUES_URL") == report.ISSUES_NEW_URL
    assert _module_constant("NOTICE") == report.NOTICE


def test_the_toolbar_buttons_the_health_check_looks_for_are_the_ones_the_script_makes():
    module = source(f"resources/{MODULE_NAME}")
    listed = re.search(r"export const TOOLBAR_BUTTONS = \[([^\]]*)\]", module)
    assert listed
    in_module = re.findall(r'"([^"]+)"', listed.group(1))
    in_script = re.findall(r'id: "([a-z-]+-autohide-button)"', source(f"JS/{SCRIPT_NAME}"))
    assert in_module == in_script and len(in_module) == 2


def test_the_doctor_knows_the_codes_the_script_status_leads_to():
    for code in (
        errors.STATUS_MISSING,
        errors.STATUS_UNUSABLE,
        errors.FIREFOX_REPORTS_PROBLEM,
        errors.FIREFOX_SCRIPT_ERRORS,
    ):
        assert code.code in errors.CODES
