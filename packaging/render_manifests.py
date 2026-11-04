"""Fill the Scoop and winget manifests for one release of the standalone program.

    python packaging/render_manifests.py <version> <sha256> <output folder>

The hash is the SHA-256 of ``peek-a-foxy.exe`` as attached to the release ``v<version>``. The
release workflow runs this and attaches the result, so ``scoop install <url of peek-a-foxy.json>``
works without a bucket, and the winget files are ready to submit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
OUTPUT_NAMES = {
    "scoop.json": "peek-a-foxy.json",
    "winget.yaml": "paodelonga.PeekAFoxy.yaml",
    "winget.installer.yaml": "paodelonga.PeekAFoxy.installer.yaml",
    "winget.locale.yaml": "paodelonga.PeekAFoxy.locale.en-US.yaml",
}


def render(version: str, sha256: str, output: Path) -> list[Path]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"version must look like 1.2.3, not {version!r}")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("sha256 must be 64 hexadecimal digits")
    values = {"@VERSION@": version, "@SHA256@": sha256.lower(), "@SHA256_UPPER@": sha256.upper()}
    output.mkdir(parents=True, exist_ok=True)
    written = []
    for template, name in OUTPUT_NAMES.items():
        text = (TEMPLATES / template).read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace(key, value)
        target = output / name
        target.write_text(text, encoding="utf-8", newline="\n")
        written.append(target)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    for path in render(argv[0], argv[1], Path(argv[2])):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
