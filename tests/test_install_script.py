"""packaging/install.ps1 run for real by PowerShell: the hash it reads and the PATH it writes.

The functions are lifted out of the script (its own text, parsed, not a copy) and run in a real
PowerShell: ``pwsh`` and, on Windows, Windows PowerShell 5.1 too, whichever are installed. Without
any the tests are skipped; ``PEEK_A_FOXY_PWSH`` points at a ``pwsh`` that is not on ``PATH``.
Nothing here downloads from the internet or touches the real user PATH.
"""

from __future__ import annotations

import base64
import http.server
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "install.ps1"
DIGEST = "ab" * 32


def powershell_hosts() -> list[str]:
    found: list[str] = []
    for candidate in (
        os.environ.get("PEEK_A_FOXY_PWSH"),
        shutil.which("pwsh"),
        shutil.which("powershell"),
    ):
        if candidate and candidate not in found and Path(candidate).is_file():
            found.append(candidate)
    return found


HOSTS = powershell_hosts()
pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or not HOSTS, reason="needs packaging/install.ps1 and a PowerShell"
)

# Defines every function of install.ps1 here and nothing else of it: the rest of the script
# downloads and installs.
LOAD = rf"""
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$ast = [Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$null, [ref]$null)
$kind = [Management.Automation.Language.FunctionDefinitionAst]
$all = $ast.FindAll({{ param($node) $node -is $kind }}, $false)
foreach ($function in $all) {{ . ([scriptblock]::Create($function.Extent.Text)) }}
"""


@pytest.fixture(params=[pytest.param(host, id=Path(host).stem) for host in HOSTS] or [None])
def host(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def run_ps(host: str, body: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` after the functions of install.ps1; text in, text out, UTF-8 everywhere."""
    command = LOAD + "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + body
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    environment = dict(os.environ, POWERSHELL_TELEMETRY_OPTOUT="1", NO_PROXY="127.0.0.1,localhost")
    environment.update(env)
    return subprocess.run(
        [host, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=environment,
        check=False,
    )


# --- PF-02: the published hash ------------------------------------------------------------------

GOOD_FILES = {
    "the format the release workflow writes": f"{DIGEST}  peek-a-foxy.exe\n".encode(),
    "sha256sum binary mode and CRLF": f"{DIGEST} *peek-a-foxy.exe\r\n".encode(),
    "the bare hash, no newline": DIGEST.encode(),
    "a byte order mark": b"\xef\xbb\xbf" + f"{DIGEST}  peek-a-foxy.exe\n".encode(),
    "blank lines and tabs first": f"\r\n\n \t{DIGEST}\tpeek-a-foxy.exe\n\n".encode(),
    "upper case": DIGEST.upper().encode() + b"\n",
    "a second line is ignored": f"{DIGEST}  a\n{'cd' * 32}  b\n".encode(),
}


@pytest.mark.parametrize("content", GOOD_FILES.values(), ids=GOOD_FILES.keys())
def test_the_hash_is_the_first_word_of_the_file(host, tmp_path, content):
    path = tmp_path / "peek-a-foxy.exe.sha256"
    path.write_bytes(content)
    done = run_ps(
        host, "[Console]::Out.Write((Read-PublishedHash $env:PAF_FILE))", PAF_FILE=str(path)
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == DIGEST or done.stdout == DIGEST.upper()


BAD_FILES = {
    "empty": b"",
    "only white space": b" \r\n\t\n",
    "63 digits": b"a" * 63,
    "65 digits": b"a" * 65,
    "a digit that is not hexadecimal": b"g" + b"a" * 63,
    "an HTML error page": b"<!DOCTYPE html><html><body>Not Found</body></html>",
    "the bytes of a hash as decimal numbers": b" ".join(str(b).encode() for b in DIGEST.encode()),
    "text before the hash": b"sha256: " + DIGEST.encode(),
    "NUL bytes": b"\x00" * 64,
    "bytes that are not UTF-8": b"\xff\xfe\xfd" * 30,
    "the hash glued to more text": DIGEST.encode() + b"peek-a-foxy.exe",
}


@pytest.mark.parametrize("content", BAD_FILES.values(), ids=BAD_FILES.keys())
def test_anything_else_is_refused_with_the_hash_message(host, tmp_path, content):
    path = tmp_path / "peek-a-foxy.exe.sha256"
    path.write_bytes(content)
    done = run_ps(host, "Read-PublishedHash $env:PAF_FILE", PAF_FILE=str(path))
    assert done.returncode != 0
    assert "not a SHA-256 value" in done.stderr


def test_a_large_file_is_refused_before_it_is_read(host, tmp_path):
    path = tmp_path / "peek-a-foxy.exe.sha256"
    path.write_bytes(f"{DIGEST}\n".encode() + b"x" * 5000)
    done = run_ps(host, "Read-PublishedHash $env:PAF_FILE", PAF_FILE=str(path))
    assert done.returncode != 0 and "too large" in done.stderr


def test_a_file_that_is_missing_is_an_error_not_a_hash(host, tmp_path):
    done = run_ps(host, "Read-PublishedHash $env:PAF_FILE", PAF_FILE=str(tmp_path / "nope"))
    assert done.returncode != 0


def test_a_path_with_wildcards_is_taken_literally(host, tmp_path):
    path = tmp_path / "[a]*?.sha256"
    path.write_text(f"{DIGEST}\n", encoding="utf-8")
    done = run_ps(
        host, "[Console]::Out.Write((Read-PublishedHash $env:PAF_FILE))", PAF_FILE=str(path)
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == DIGEST


class Release(http.server.BaseHTTPRequestHandler):
    """Serves the hash file the way GitHub serves release assets: as application/octet-stream."""

    body = f"{DIGEST}  peek-a-foxy.exe\n".encode()
    content_type = "application/octet-stream"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def release_url() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Release)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/peek-a-foxy.exe.sha256"
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


DOWNLOAD = r"""
$bytes = (Invoke-WebRequest -UseBasicParsing -Uri $env:PAF_URL).Content
"content: " + $bytes.GetType().Name
"old reading: " + ([string]$bytes).Trim().Split()[0]
$file = Join-Path $env:PAF_DIR 'peek-a-foxy.exe.sha256'
Invoke-WebRequest -UseBasicParsing -Uri $env:PAF_URL -OutFile $file
"new reading: " + (Read-PublishedHash $file)
"""


def test_a_hash_served_as_octet_stream_is_read_through_a_file(host, tmp_path, release_url):
    """The reason for the file: .Content of this response is bytes, and the old reading broke."""
    done = run_ps(host, DOWNLOAD, PAF_URL=release_url, PAF_DIR=str(tmp_path))
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == "content: Byte[]"
    assert lines[1] != f"old reading: {DIGEST}"  # the former code took the first byte, "97"
    assert lines[2] == f"new reading: {DIGEST}"


def test_the_script_no_longer_reads_the_hash_from_the_response_body():
    script = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert ").Content" not in code
    assert "-OutFile $hashFile" in script and "Read-PublishedHash $hashFile" in script
