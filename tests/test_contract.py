"""What the Python side and the Firefox script must agree on, checked against the real files."""

from __future__ import annotations

import re
from pathlib import Path

from peek_a_foxy import cli, userfiles
from peek_a_foxy.assets import SCRIPT_NAME, assets_dir

# Set by the script itself and never written to user.js, so the installer has nothing to remove.
SCRIPT_ONLY_PREFS = {"peekafoxy.welcomed"}


def script() -> str:
    return (assets_dir() / "JS" / SCRIPT_NAME).read_text(encoding="utf-8")


def test_the_pref_names_in_python_are_the_ones_the_script_registers():
    in_script = set(re.findall(r'"(peekafoxy\.[A-Za-z.]+)"', script()))
    assert in_script == set(userfiles.OWN_PREFS) | SCRIPT_ONLY_PREFS


def test_the_legacy_prefs_map_onto_current_names():
    assert set(userfiles.LEGACY_PREFS.values()) == set(userfiles.OWN_PREFS)


def test_the_shortcuts_the_cli_announces_are_the_ones_the_script_listens_for():
    codes = re.findall(r'code: "Key([A-Z])"', script())
    announced = {cli.TABS_SHORTCUT, cli.URLBAR_SHORTCUT}
    assert {f"Ctrl+Alt+{code}" for code in codes} == announced


def _variables(text: str) -> dict[str, str]:
    return {
        name: " ".join(value.split())
        for name, value in re.findall(r"(--autohide-[a-z-]+):\s*([^;]+);", text)
    }


def test_the_readmes_css_example_shows_the_real_defaults():
    root = Path(__file__).resolve().parents[1]
    css = (assets_dir() / "autohide.css").read_text(encoding="utf-8")
    real = _variables(css.split(":root {")[1].split("}")[0])  # the defaults, not the overrides
    assert len(real) == 6
    for name in ("README.md", "README.pt-BR.md"):
        text = (root / name).read_text(encoding="utf-8")
        blocks = [b for b in text.split("```css")[1:] if "--autohide-strip:" in b.split("```")[0]]
        example = blocks[0].split("```")[0]
        assert _variables(example) == real, name
