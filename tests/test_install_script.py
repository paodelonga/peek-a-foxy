"""packaging/install.ps1 run for real by PowerShell: the hash it reads and the PATH it writes.

The functions are lifted out of the script (its own text, parsed, not a copy) and run in a real
PowerShell: ``pwsh`` and, on Windows, Windows PowerShell 5.1 too, whichever are installed. Without
any the tests are skipped; ``PEEK_A_FOXY_PWSH`` points at a ``pwsh`` that is not on ``PATH``.
Nothing here downloads from the internet or touches the real user PATH.
"""

from __future__ import annotations

import base64
import contextlib
import http.server
import os
import shutil
import subprocess
import sys
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
    # "[a]" is a PowerShell wildcard that only matches "a", so read as a pattern this name finds
    # nothing. Windows refuses "*" and "?" in a file name; elsewhere they are tried as well.
    name = "[a]x.sha256" if sys.platform == "win32" else "[a]*?.sha256"
    path = tmp_path / name
    path.write_bytes(f"{DIGEST}\n".encode())
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


# --- PF-23: the user PATH ------------------------------------------------------------------------

FOLDER = r"C:\Users\someone\AppData\Local\Programs\peek-a-foxy"
PRESENT = "<already there>"


def with_entry(host: str, raw: str, directory: str = FOLDER, **env: str) -> str:
    body = (
        "$result = Get-PathWithEntry $env:PAF_RAW $env:PAF_DIR\n"
        f"if ($null -eq $result) {{ [Console]::Out.Write('{PRESENT}') }} "
        "else { [Console]::Out.Write($result) }"
    )
    done = run_ps(host, body, PAF_RAW=raw, PAF_DIR=directory, **env)
    assert done.returncode == 0, done.stderr
    return done.stdout


ADDED = {
    "no PATH yet": ("", FOLDER),
    "only white space": ("  \t ", FOLDER),
    "only separators": (";;;", FOLDER),
    "one entry": (r"C:\a", rf"C:\a;{FOLDER}"),
    "a trailing semicolon is not doubled": (r"C:\a;", rf"C:\a;{FOLDER}"),
    "several trailing semicolons": (r"C:\a;;;", rf"C:\a;{FOLDER}"),
    "an empty entry in the middle stays as it was": (r"C:\a;;C:\b", rf"C:\a;;C:\b;{FOLDER}"),
    "a variable stays a variable": (
        r"%USERPROFILE%\bin;C:\a;%SystemRoot%\system32",
        rf"%USERPROFILE%\bin;C:\a;%SystemRoot%\system32;{FOLDER}",
    ),
    "a semicolon inside quotes does not split an entry": (
        r'"C:\a;b";C:\c',
        rf'"C:\a;b";C:\c;{FOLDER}',
    ),
    "a quote that never closes": (r'"C:\a;C:\b', rf'"C:\a;C:\b;{FOLDER}'),
    "a sub-folder of the folder is another entry": (
        rf"{FOLDER}\bin",
        rf"{FOLDER}\bin;{FOLDER}",
    ),
    "a longer name that starts like the folder": (
        FOLDER + "-old",
        rf"{FOLDER}-old;{FOLDER}",
    ),
}


@pytest.mark.parametrize(("raw", "expected"), ADDED.values(), ids=ADDED.keys())
def test_the_folder_goes_at_the_end_and_nothing_else_changes(host, raw, expected):
    assert with_entry(host, raw) == expected


def test_the_half_of_a_quoted_entry_is_not_mistaken_for_the_folder(host):
    """In "C:\\a;b" the text before the semicolon is not a folder called C:\\a."""
    raw = r'"C:\a;b";C:\c'
    assert with_entry(host, raw, r"C:\a") == rf"{raw};C:\a"
    assert with_entry(host, raw, r"C:\c") == PRESENT


ALREADY = {
    "the same text": FOLDER,
    "in the middle": rf"C:\a;{FOLDER};C:\b",
    "another case": FOLDER.upper(),
    "with a trailing backslash": FOLDER + "\\",
    "with a trailing slash": FOLDER + "/",
    "in quotes": f'"{FOLDER}"',
    "with spaces around it": f"C:\\a; {FOLDER} ;C:\\b",
    "after empty entries": f";;{FOLDER};;",
}


@pytest.mark.parametrize("raw", ALREADY.values(), ids=ALREADY.keys())
def test_a_folder_that_is_already_there_is_not_added_again(host, raw):
    assert with_entry(host, raw) == PRESENT


def test_the_folder_is_not_added_twice_when_the_given_one_has_a_trailing_backslash(host):
    assert with_entry(host, FOLDER, FOLDER + "\\") == PRESENT


def test_an_entry_written_with_a_variable_counts_as_the_folder_it_stands_for(host):
    raw = r"C:\a;%PAF_BASE%\Programs\peek-a-foxy"
    assert with_entry(host, raw, r"C:\Base\Programs\peek-a-foxy", PAF_BASE=r"C:\Base") == PRESENT
    assert with_entry(host, raw, r"C:\Other\peek-a-foxy", PAF_BASE=r"C:\Base").endswith(
        r";C:\Other\peek-a-foxy"
    )


def test_a_variable_that_is_not_defined_is_kept_as_text_and_never_matches(host):
    raw = r"%PAF_NOT_DEFINED%\x"
    assert with_entry(host, raw) == rf"{raw};{FOLDER}"


def test_a_very_long_path_is_handled_in_linear_time(host):
    raw = ";".join(rf"C:\folder{n}" for n in range(3000))
    assert with_entry(host, raw) == f"{raw};{FOLDER}"


def test_the_script_does_not_flatten_the_path_through_the_environment_class():
    script = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert 'GetEnvironmentVariable("Path"' not in code
    assert 'SetEnvironmentVariable("Path"' not in code
    assert "DoNotExpandEnvironmentNames" in code


@pytest.mark.parametrize("directory", ["C:\\100%\\x", "C:\\a;b", 'C:\\a"b'])
def test_a_folder_that_cannot_go_in_the_path_stops_the_installer_before_any_download(
    host, directory
):
    """Run the real script: its refusal comes before the first download, so no network is used."""
    # As a script block, not as a file, so that an execution policy of Restricted cannot stop it.
    command = (
        f"& ([scriptblock]::Create([IO.File]::ReadAllText('{SCRIPT}'))) -InstallDir $env:PAF_DIR"
    )
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    done = subprocess.run(
        [host, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=dict(os.environ, PAF_DIR=directory, POWERSHELL_TELEMETRY_OPTOUT="1"),
        check=False,
    )
    assert done.returncode != 0
    assert "cannot go in the PATH safely" in done.stderr
    assert "This will:" not in done.stdout


# --- the registry part, on a private key (Windows only) ---------------------------------------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows registry")


@pytest.fixture
def private_key() -> Iterator[str]:
    """A throwaway key under HKCU: never the real Environment key."""
    import winreg

    name = rf"Software\peek-a-foxy-tests\{os.getpid()}"
    yield name
    for path in (name, r"Software\peek-a-foxy-tests"):
        with contextlib.suppress(OSError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def read_path(subkey: str) -> tuple[str, int] | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            return winreg.QueryValueEx(key, "Path")  # type: ignore[no-any-return]
    except OSError:
        return None


def write_path(subkey: str, value: str | int, kind: int) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey) as key:
        winreg.SetValueEx(key, "Path", 0, kind, value)


def add_to_registry(host: str, subkey: str) -> subprocess.CompletedProcess[str]:
    body = "[Console]::Out.Write((Add-UserPathEntry $env:PAF_DIR $env:PAF_KEY))"
    return run_ps(host, body, PAF_DIR=FOLDER, PAF_KEY=subkey)


@windows_only
def test_real_an_expandable_path_stays_expandable_and_keeps_its_variables(host, private_key):
    import winreg

    write_path(private_key, r"%USERPROFILE%\bin;C:\a;", winreg.REG_EXPAND_SZ)
    done = add_to_registry(host, private_key)
    assert done.returncode == 0 and done.stdout == "True", done.stderr
    assert read_path(private_key) == (rf"%USERPROFILE%\bin;C:\a;{FOLDER}", winreg.REG_EXPAND_SZ)


@windows_only
def test_real_a_plain_string_path_stays_a_plain_string(host, private_key):
    import winreg

    write_path(private_key, r"C:\a", winreg.REG_SZ)
    assert add_to_registry(host, private_key).stdout == "True"
    assert read_path(private_key) == (rf"C:\a;{FOLDER}", winreg.REG_SZ)


@windows_only
def test_real_a_missing_path_is_created_as_expandable(host, private_key):
    import winreg

    assert add_to_registry(host, private_key).stdout == "True"
    assert read_path(private_key) == (FOLDER, winreg.REG_EXPAND_SZ)


@windows_only
def test_real_a_path_that_has_the_folder_is_left_exactly_as_it_was(host, private_key):
    import winreg

    value = rf"%USERPROFILE%\bin;{FOLDER}\;"
    write_path(private_key, value, winreg.REG_EXPAND_SZ)
    assert add_to_registry(host, private_key).stdout == "False"
    assert read_path(private_key) == (value, winreg.REG_EXPAND_SZ)


@windows_only
def test_real_a_path_that_is_not_text_is_left_alone(host, private_key):
    import winreg

    write_path(private_key, 7, winreg.REG_DWORD)
    done = add_to_registry(host, private_key)
    assert done.returncode != 0 and "not a text value" in done.stderr
    assert read_path(private_key) == (7, winreg.REG_DWORD)
