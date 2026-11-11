"""Refresh the fx-autoconfig files that ship with Peek-a-Foxy, or check that they are still genuine.

    python packaging/update_loader.py COMMIT      fetch the files at COMMIT into fx-autoconfig/
    python packaging/update_loader.py --check     compare fx-autoconfig/ with its commit upstream

The files are the ones the installer copies (see FILES) and the licence they come with. The script
also writes fx-autoconfig/manifest.json (the commit and the SHA-256 of every file). After an update,
put the same commit in DEFAULT_COMMIT (src/peek_a_foxy/loader.py) and the SHA-256 of the two files
that go into Firefox's folder in PINNED_SHA256 (src/peek_a_foxy/elevate.py): a test compares all
three with the manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

REPOSITORY = "MrOtherGuy/fx-autoconfig"
ROOT = Path(__file__).resolve().parents[1] / "fx-autoconfig"
# What the installer reads: two files for Firefox's folder and the folder profile/chrome/utils.
FILES = (
    "program/config.js",
    "program/defaults/pref/config-prefs.js",
    "profile/chrome/utils/boot.sys.mjs",
    "profile/chrome/utils/chrome.manifest",
    "profile/chrome/utils/fs.sys.mjs",
    "profile/chrome/utils/module_loader.mjs",
    "profile/chrome/utils/uc_api.sys.mjs",
    "profile/chrome/utils/utils.sys.mjs",
    "LICENSE",
)
MAX_BYTES = 1024 * 1024  # the real files are far smaller


def fetch(commit: str, path: str) -> bytes:
    """One file of the repository at ``commit``, with LF line endings."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"{commit!r} is not a full lowercase commit hash")
    url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{path}"
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 (a fixed https address)
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SystemExit(f"{url} is larger than {MAX_BYTES} bytes")
    return data.replace(b"\r\n", b"\n")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(root: Path = ROOT) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def update(commit: str, root: Path = ROOT) -> dict:
    """Write the files of ``commit`` and the manifest into ``root``; return the manifest."""
    files = {}
    for path in FILES:
        data = fetch(commit, path)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[path] = digest(data)
    result = {"repository": f"https://github.com/{REPOSITORY}", "commit": commit, "files": files}
    (root / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def check(root: Path = ROOT) -> list[str]:
    """What differs between ``root`` and its manifest's commit upstream (empty when nothing)."""
    wanted = manifest(root)
    problems = []
    for path in FILES:
        upstream = digest(fetch(wanted["commit"], path))
        if wanted["files"].get(path) != upstream:
            problems.append(f"{path}: the manifest does not match upstream")
        local = root / path
        if not local.is_file() or digest(local.read_bytes().replace(b"\r\n", b"\n")) != upstream:
            problems.append(f"{path}: the file does not match upstream")
    return problems


def main(argv: list[str]) -> int:
    if argv == ["--check"]:
        problems = check()
        for problem in problems:
            print(problem)
        print("genuine" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if len(argv) == 1 and re.fullmatch(r"[0-9a-f]{40}", argv[0]):
        result = update(argv[0])
        print(f"fx-autoconfig/ now holds {len(result['files'])} files of {argv[0]}")
        for path, value in result["files"].items():
            print(f"  {value}  {path}")
        print(
            "Now set DEFAULT_COMMIT in src/peek_a_foxy/loader.py and PINNED_SHA256 in elevate.py."
        )
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
