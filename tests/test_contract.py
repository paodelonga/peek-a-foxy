"""What the Python side and the Firefox script must agree on, checked against the real files."""

from __future__ import annotations

import re
from pathlib import Path

from peek_a_foxy import cli, userfiles
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
