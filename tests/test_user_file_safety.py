"""Edits of the user's own files (userChrome.css, user.js): atomic, backed up once, never worse.

Most of these tests are hostile on purpose: links of every kind, read-only things, a full disk, a
crash half way, a file that changes under our hands, two installs at once, a huge file.
"""

from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from support import needs_permissions, needs_symlinks

from peek_a_foxy import errors, installer
from peek_a_foxy import userfiles as uf
from peek_a_foxy.cli import app
from peek_a_foxy.errors import UserFileError
from peek_a_foxy.installer import (
    BACKUP_SUFFIX,
    TEMP_SUFFIX,
    _edit,
    backup_path,
    plan_install,
    plan_uninstall,
)

SRC = str(Path(__file__).resolve().parents[1] / "src")


def leftovers(folder: Path) -> list[Path]:
    """Temporary files that an edit left behind (there must never be any)."""
    return sorted(folder.rglob(f"*{TEMP_SUFFIX}"))


def add_import(path: Path) -> None:
    _edit(path, uf.with_css_import)


# --- atomic replacement ------------------------------------------------------------------------


def test_an_edit_replaces_the_file_in_one_step_and_leaves_no_temporary_file(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    before = css.stat().st_ino
    add_import(css)
    assert css.read_text() == f"{uf.CSS_IMPORT}\nbody{{}}\n"
    assert css.stat().st_ino != before  # a new file took the name; nobody ever saw a half file
    assert leftovers(tmp_path) == []


def test_the_edit_keeps_the_permissions_of_the_file(tmp_path: Path):
    user_js = tmp_path / "user.js"
    user_js.write_text("")
    user_js.chmod(0o640)
    _edit(user_js, lambda text: text + "// x\n")
    assert stat.S_IMODE(user_js.stat().st_mode) == 0o640
    assert stat.S_IMODE(backup_path(user_js).stat().st_mode) == 0o640  # a secret stays a secret


def test_the_edit_asks_for_the_same_owner_and_group_back(tmp_path: Path, monkeypatch):
    """Run as root, an edit must not turn a person's file into root's."""
    if not hasattr(os, "chown"):
        pytest.skip("no chown on this system")
    asked: list[tuple[int, int]] = []
    monkeypatch.setattr(installer.os, "chown", lambda path, uid, gid: asked.append((uid, gid)))
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    add_import(css)
    assert asked and asked[0] == (css.stat().st_uid, css.stat().st_gid)


def test_a_chown_that_is_not_allowed_is_not_an_error(tmp_path: Path, monkeypatch):
    if not hasattr(os, "chown"):
        pytest.skip("no chown on this system")

    def denied(*args: object) -> None:
        raise PermissionError(errno.EPERM, "not permitted")

    monkeypatch.setattr(installer.os, "chown", denied)
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    add_import(css)
    assert css.read_text().startswith(uf.CSS_IMPORT)


@needs_permissions
def test_a_read_only_file_is_respected_not_replaced_around(tmp_path: Path):
    """Atomic replacement could swap a read-only file in a writable folder: not ours to do."""
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    css.chmod(0o444)
    with pytest.raises(PermissionError):
        add_import(css)
    assert css.read_text() == "body{}\n"
    assert leftovers(tmp_path) == [] and not backup_path(css).exists()


@needs_permissions
def test_a_read_only_folder_fails_cleanly_and_changes_nothing(tmp_path: Path):
    folder = tmp_path / "chrome"
    folder.mkdir()
    css = folder / "userChrome.css"
    css.write_text("body{}\n")
    folder.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            add_import(css)
    finally:
        folder.chmod(0o755)
    assert css.read_text() == "body{}\n"
    assert leftovers(folder) == [] and not backup_path(css).exists()


@needs_permissions
def test_a_read_only_folder_is_a_coded_error_at_the_command_line(profile: Path):
    from typer.testing import CliRunner

    (profile / "chrome" / "userChrome.css").write_text("body{}\n")
    (profile / "chrome").chmod(0o555)
    try:
        result = CliRunner().invoke(
            app, ["install", "--skip-loader", "--yes", "--profile", str(profile)]
        )
    finally:
        (profile / "chrome").chmod(0o755)
    assert result.exit_code == 1 and "error [PAF-402]" in result.output
    assert "Traceback" not in result.output


def test_a_full_disk_while_writing_leaves_the_original_and_no_leftover(tmp_path: Path, monkeypatch):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")

    def full(descriptor: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(installer.os, "fsync", full)
    with pytest.raises(OSError, match="No space"):
        add_import(css)
    assert css.read_text() == "body{}\n"
    assert leftovers(tmp_path) == [] and not backup_path(css).exists()


def test_a_full_disk_while_keeping_the_copy_stops_before_the_file_is_touched(
    tmp_path: Path, monkeypatch
):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    real_new_file = installer._new_file

    def fails_for_the_backup(directory, name, data, template):
        if name.endswith(BACKUP_SUFFIX):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_new_file(directory, name, data, template)

    monkeypatch.setattr(installer, "_new_file", fails_for_the_backup)
    with pytest.raises(OSError):
        add_import(css)
    assert css.read_text() == "body{}\n"  # no backup, so no edit
    assert leftovers(tmp_path) == []


@pytest.mark.parametrize("crash", [KeyboardInterrupt, SystemExit, RuntimeError, MemoryError])
def test_a_crash_between_the_temporary_file_and_the_rename_is_cleaned_up(
    tmp_path: Path, monkeypatch, crash
):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")

    def dies(*args: object) -> None:
        raise crash()

    monkeypatch.setattr(installer.os, "replace", dies)
    with pytest.raises(crash):
        add_import(css)
    assert css.read_text() == "body{}\n"
    assert leftovers(tmp_path) == []
    # The copy is already in place; the next run finds it and does not make another.
    assert backup_path(css).read_bytes() == b"body{}\n"


def test_a_process_killed_before_the_rename_never_leaves_a_half_file(tmp_path: Path):
    """A real crash (no cleanup runs): the file is still the old one, and the next run copes."""
    css = tmp_path / "userChrome.css"
    css.write_bytes(b"body{}\n")
    code = (
        "import os, sys; from pathlib import Path\n"
        "from peek_a_foxy import installer, userfiles\n"
        "os.replace = lambda *a: os._exit(9)\n"
        "installer._edit(Path(sys.argv[1]), userfiles.with_css_import)\n"
    )
    env = {**os.environ, "PYTHONPATH": SRC}
    result = subprocess.run([sys.executable, "-c", code, str(css)], env=env, timeout=60)
    assert result.returncode == 9
    assert css.read_bytes() == b"body{}\n"  # never a half file
    assert len(leftovers(tmp_path)) == 1  # only a kill can leave this: it never replaced anything
    add_import(css)  # the next run neither trips on the leftover nor on the copy
    assert css.read_text() == f"{uf.CSS_IMPORT}\nbody{{}}\n"
    assert backup_path(css).read_bytes() == b"body{}\n"


# --- links -------------------------------------------------------------------------------------


@needs_symlinks
def test_a_symbolic_link_stays_a_link_and_the_real_file_is_replaced(tmp_path: Path):
    real = tmp_path / "dotfiles" / "userChrome.css"
    real.parent.mkdir()
    real.write_text("body{}\n")
    link = tmp_path / "chrome" / "userChrome.css"
    link.parent.mkdir()
    link.symlink_to(real)
    add_import(link)
    assert link.is_symlink() and os.readlink(link) == str(real)
    assert real.read_text() == f"{uf.CSS_IMPORT}\nbody{{}}\n"
    assert not real.is_symlink()
    assert leftovers(tmp_path) == []
    # The copy sits next to the name the person knows (the link), and holds the old bytes.
    assert backup_path(link).read_bytes() == b"body{}\n"
    assert not backup_path(real).exists()


@needs_symlinks
def test_a_chain_of_links_is_followed_to_its_end(tmp_path: Path):
    real = tmp_path / "real.css"
    real.write_text("a{}\n")
    middle = tmp_path / "middle.css"
    middle.symlink_to(real.name)  # relative link
    link = tmp_path / "userChrome.css"
    link.symlink_to(middle.name)
    add_import(link)
    assert link.is_symlink() and middle.is_symlink() and not real.is_symlink()
    assert real.read_text().startswith(uf.CSS_IMPORT)


@needs_symlinks
def test_a_dangling_link_gets_its_target_created_and_stays_a_link(tmp_path: Path):
    link = tmp_path / "userChrome.css"
    target = tmp_path / "later.css"
    link.symlink_to(target)
    add_import(link)
    assert link.is_symlink() and target.read_text() == f"{uf.CSS_IMPORT}\n"
    assert not backup_path(link).exists()  # there was no file to keep a copy of


@needs_symlinks
def test_a_dangling_link_into_a_missing_folder_is_an_error_and_creates_no_folder(tmp_path: Path):
    link = tmp_path / "userChrome.css"
    link.symlink_to(tmp_path / "nowhere" / "x.css")
    with pytest.raises(OSError):
        add_import(link)
    assert not (tmp_path / "nowhere").exists()


@needs_symlinks
def test_a_loop_of_links_is_refused_before_anything_changes(profile: Path):
    css = profile / "chrome" / "userChrome.css"
    other = profile / "chrome" / "other.css"
    css.symlink_to(other)
    other.symlink_to(css)
    with pytest.raises(UserFileError, match="never ends") as caught:
        plan_install(profile, None)  # fails while planning: no step has run
    assert caught.value.code is errors.FILE_IO
    assert css.is_symlink() and other.is_symlink()
    assert not (profile / "chrome" / "autohide.css").exists()


@needs_symlinks
def test_a_link_to_a_folder_is_an_error_not_a_replaced_folder(tmp_path: Path):
    folder = tmp_path / "somewhere"
    folder.mkdir()
    (folder / "keep.txt").write_text("keep")
    link = tmp_path / "userChrome.css"
    link.symlink_to(folder, target_is_directory=True)
    with pytest.raises(OSError):
        add_import(link)
    assert (folder / "keep.txt").read_text() == "keep" and link.is_symlink()
    assert leftovers(tmp_path) == []


@needs_symlinks
def test_a_link_put_in_place_of_the_file_meanwhile_is_followed_and_kept(tmp_path: Path):
    """The edit starts over and follows the new link: it never swaps the link for a plain file."""
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    new_home = tmp_path / "dotfiles.css"
    new_home.write_text("p{}\n")
    swapped = []

    def swap_in_a_link(text: str) -> str:
        if not swapped:
            swapped.append(1)
            css.unlink()
            css.symlink_to(new_home)
        return uf.with_css_import(text)

    _edit(css, swap_in_a_link)
    assert css.is_symlink() and new_home.read_text() == f"{uf.CSS_IMPORT}\np{{}}\n"
    assert leftovers(tmp_path) == []


@needs_symlinks
def test_a_planted_link_at_the_backup_name_is_never_followed_or_replaced(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    backup_path(css).symlink_to(victim)
    add_import(css)
    assert victim.read_text() == "precious"
    assert backup_path(css).is_symlink()


@needs_symlinks
def test_a_dangling_link_at_the_backup_name_is_left_alone(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    backup_path(css).symlink_to(tmp_path / "nowhere")
    add_import(css)
    assert not (tmp_path / "nowhere").exists()
    assert css.read_text().startswith(uf.CSS_IMPORT)


# --- a file that changes under our hands -------------------------------------------------------


def test_a_change_made_while_the_edit_is_prepared_is_not_overwritten(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    calls: list[int] = []

    def transform(text: str) -> str:
        if not calls:  # the first time, another program saves the file meanwhile
            css.write_text(text + "/* added by an editor */\n")
        calls.append(1)
        return uf.with_css_import(text)

    _edit(css, transform)
    assert len(calls) == 2  # it started over from the new content
    assert css.read_text() == f"{uf.CSS_IMPORT}\nbody{{}}\n/* added by an editor */\n"
    assert backup_path(css).read_text() == "body{}\n/* added by an editor */\n"


def test_a_file_replaced_by_another_one_in_the_meantime_is_noticed(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    done = []

    def transform(text: str) -> str:
        if not done:
            done.append(1)
            css.unlink()  # an editor's "safe save": remove, then write a new file
            css.write_text("p{}\n")
        return uf.with_css_import(text)

    _edit(css, transform)
    assert css.read_text() == f"{uf.CSS_IMPORT}\np{{}}\n"


def test_a_file_deleted_in_the_meantime_is_noticed(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    done = []

    def transform(text: str) -> str:
        if not done:
            done.append(1)
            css.unlink()
        return uf.with_css_import(text)

    _edit(css, transform)
    assert css.read_text() == f"{uf.CSS_IMPORT}\n"  # recreated from what is there now: nothing


def test_a_file_that_never_stops_changing_is_given_up_with_a_coded_error(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    css.write_text("0")
    counter = [0]

    def transform(text: str) -> str:
        counter[0] += 1
        css.write_text(str(counter[0]))  # a sync tool rewriting it again and again
        return text + "!"

    with pytest.raises(UserFileError, match="keeps changing") as caught:
        _edit(css, transform)
    assert caught.value.code is errors.FILE_IO and counter[0] == installer.EDIT_ATTEMPTS
    assert css.read_text() == str(counter[0]) and leftovers(tmp_path) == []


def test_two_installs_at_once_end_with_one_correct_result(profile: Path):
    css = profile / "chrome" / "userChrome.css"
    css.write_bytes(b"\xef\xbb\xbfbody {\r\n  color: red;\r\n}\r\n")
    env = {**os.environ, "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"}
    command = [
        sys.executable,
        "-m",
        "peek_a_foxy",
        "install",
        "--skip-loader",
        "--yes",
        "--profile",
        str(profile),
    ]
    processes = [
        subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(6)
    ]
    outputs = [(p.communicate(timeout=120), p.returncode) for p in processes]
    assert [code for _, code in outputs] == [0] * 6, outputs
    expected = (
        b"\xef\xbb\xbf" + f"{uf.CSS_IMPORT}\r\n".encode() + b"body {\r\n  color: red;\r\n}\r\n"
    )
    assert css.read_bytes() == expected
    assert backup_path(css).read_bytes() == b"\xef\xbb\xbfbody {\r\n  color: red;\r\n}\r\n"
    assert leftovers(profile) == []
    user_js = (profile / "user.js").read_text()
    assert user_js.count(uf.STYLESHEETS_PREF) == 1  # not appended once per process


# --- what is in the file: bytes, not just text -------------------------------------------------


def test_a_bom_and_crlf_survive_and_the_copy_is_byte_identical(tmp_path: Path):
    original = b"\xef\xbb\xbf@namespace url(x);\r\nbody{}\r\n"
    css = tmp_path / "userChrome.css"
    css.write_bytes(original)
    add_import(css)
    assert css.read_bytes() == b"\xef\xbb\xbf" + f"{uf.CSS_IMPORT}\r\n".encode() + original[3:]
    assert backup_path(css).read_bytes() == original


def test_nul_bytes_and_odd_line_separators_pass_through(tmp_path: Path):
    original = "a\x00b c\x0bd\x1ce\nbody{}".encode()
    css = tmp_path / "userChrome.css"
    css.write_bytes(original)
    add_import(css)
    assert css.read_bytes() == f"{uf.CSS_IMPORT}\n".encode() + original
    assert backup_path(css).read_bytes() == original


def test_a_file_that_is_not_utf8_is_refused_while_planning_and_keeps_no_copy(profile: Path):
    css = profile / "chrome" / "userChrome.css"
    css.write_bytes(b"body{} /* \xff\xfe */\n")
    with pytest.raises(UserFileError) as caught:
        plan_install(profile, None)
    assert caught.value.code is errors.FILE_NOT_UTF8
    assert css.read_bytes() == b"body{} /* \xff\xfe */\n" and not backup_path(css).exists()


def test_a_large_file_is_edited(tmp_path: Path):
    body = ("a { color: red; }\n" * 1000 + "\n") * 1100  # about 20 MB
    css = tmp_path / "userChrome.css"
    css.write_text(body)
    add_import(css)
    assert css.read_text() == f"{uf.CSS_IMPORT}\n{body}"
    assert backup_path(css).stat().st_size == len(body.encode())


def test_a_file_beyond_the_limit_is_refused_without_reading_it_all(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(installer, "MAX_USER_FILE_BYTES", 1024)
    css = tmp_path / "userChrome.css"
    css.write_bytes(b"x" * 5000)
    with pytest.raises(UserFileError, match="larger than") as caught:
        add_import(css)
    assert caught.value.code is errors.FILE_IO and caught.value.hint != errors.FILE_IO.hint
    assert css.read_bytes() == b"x" * 5000 and leftovers(tmp_path) == []


def test_a_huge_sparse_file_does_not_exhaust_memory(tmp_path: Path):
    css = tmp_path / "userChrome.css"
    with css.open("wb") as handle:
        handle.truncate(3 * 1024**3)  # 3 GiB of nothing, which costs no disk space
    with pytest.raises(UserFileError, match="larger than"):
        add_import(css)


# --- the one-time copy -------------------------------------------------------------------------


def test_the_copy_is_made_once_from_the_first_original_and_never_replaced(profile: Path):
    css = profile / "chrome" / "userChrome.css"
    css.write_text("body{}\n")
    plan_install(profile, None).execute()
    assert backup_path(css).read_text() == "body{}\n"
    css.write_text(css.read_text() + "/* later edit by the user */\n")
    css.write_text(uf.without_css_import(css.read_text()))
    plan_install(profile, None).execute()  # the import is added again: the file changes again
    assert backup_path(css).read_text() == "body{}\n"  # still the first original


def test_no_copy_is_made_for_a_file_that_did_not_exist_or_does_not_change(profile: Path):
    plan_install(profile, None).execute()
    assert not backup_path(profile / "chrome" / "userChrome.css").exists()
    assert not backup_path(profile / "user.js").exists()
    plan_install(profile, None).execute()  # nothing to change the second time
    assert not list(profile.rglob(f"*{BACKUP_SUFFIX}"))


def test_both_user_files_get_a_copy(profile: Path):
    (profile / "chrome" / "userChrome.css").write_text("body{}\n")
    (profile / "user.js").write_text('user_pref("my.own", 1);\n')
    plan_install(profile, None).execute()
    assert backup_path(profile / "user.js").read_text() == 'user_pref("my.own", 1);\n'
    assert backup_path(profile / "chrome" / "userChrome.css").read_text() == "body{}\n"


def test_an_existing_copy_of_any_kind_is_never_overwritten(profile: Path):
    css = profile / "chrome" / "userChrome.css"
    css.write_text("body{}\n")
    backup_path(css).write_text("the user's own earlier copy")
    backup_path(profile / "user.js").mkdir()  # even a folder is "something is there"
    (profile / "user.js").write_text("// mine\n")
    plan_install(profile, None).execute()
    assert backup_path(css).read_text() == "the user's own earlier copy"
    assert backup_path(profile / "user.js").is_dir()


def test_a_copy_that_cannot_be_linked_is_still_made(tmp_path: Path, monkeypatch):
    """File systems without hard links (some network and FAT volumes)."""

    def no_links(source: object, target: object) -> None:
        raise OSError(errno.EPERM, "hard links are not supported")

    monkeypatch.setattr(installer.os, "link", no_links)
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    add_import(css)
    assert backup_path(css).read_text() == "body{}\n" and leftovers(tmp_path) == []


def test_two_runs_racing_for_the_copy_leave_the_first_one(tmp_path: Path, monkeypatch):
    css = tmp_path / "userChrome.css"
    css.write_text("body{}\n")
    real_link = os.link

    def somebody_else_was_first(source: str | os.PathLike[str], target: str | os.PathLike[str]):
        Path(target).write_text("the winner's copy")
        return real_link(source, target)  # now raises FileExistsError

    monkeypatch.setattr(installer.os, "link", somebody_else_was_first)
    add_import(css)
    assert backup_path(css).read_text() == "the winner's copy"
    assert leftovers(tmp_path) == []


def test_the_steps_say_that_a_copy_is_kept_and_where(profile: Path):
    texts = [step.description for step in plan_install(profile, None).steps]
    assert any("userChrome.css.peek-a-foxy.bak" in text and "once" in text for text in texts)
    assert any("user.js.peek-a-foxy.bak" in text for text in texts)
    uninstall = [step.description for step in plan_uninstall(profile).steps]
    assert any("userChrome.css.peek-a-foxy.bak" in text and "kept" in text for text in uninstall)
    assert any("user.js.peek-a-foxy.bak" in text for text in uninstall)


# --- uninstall: edits the same way, and never deletes a copy -----------------------------------


def test_uninstall_keeps_the_copies_and_says_so(profile: Path):
    from typer.testing import CliRunner

    (profile / "chrome" / "userChrome.css").write_text("body{}\n")
    plan_install(profile, None).execute()
    result = CliRunner().invoke(app, ["uninstall", "--profile", str(profile), "--yes"])
    assert result.exit_code == 0
    assert backup_path(profile / "chrome" / "userChrome.css").read_text() == "body{}\n"
    assert ".peek-a-foxy.bak" in result.output and "yours to keep or delete" in result.output
    assert (profile / "chrome" / "userChrome.css").read_text() == "body{}\n"


def test_uninstall_makes_a_copy_before_it_changes_a_file_that_has_none(profile: Path):
    css = profile / "chrome" / "userChrome.css"
    css.write_text(f"{uf.CSS_IMPORT}\nbody{{}}\n")  # installed by an older version: no copy exists
    plan_uninstall(profile).execute()
    assert css.read_text() == "body{}\n"
    assert backup_path(css).read_text() == f"{uf.CSS_IMPORT}\nbody{{}}\n"


def test_uninstall_does_not_touch_files_that_it_does_not_change(profile: Path):
    (profile / "user.js").write_text('user_pref("my.own", 1);\n')
    plan_uninstall(profile).execute()
    assert not backup_path(profile / "user.js").exists()
    assert (profile / "user.js").read_text() == 'user_pref("my.own", 1);\n'


# --- a property: whatever the file holds, the copy is exact and nothing is left over ----------

contents = st.text(
    st.characters(blacklist_categories=("Cs",)),  # no lone surrogates: not encodable as UTF-8
    max_size=200,
)


@settings(max_examples=60, deadline=None)
@given(text=contents, bom=st.booleans(), crlf=st.booleans())
def test_for_any_content_the_copy_is_exact_and_nothing_is_left_over(
    text: str, bom: bool, crlf: bool
):
    body = text.replace("\r", "").replace("\n", "\r\n" if crlf else "\n")
    original = (b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8")
    with tempfile.TemporaryDirectory() as folder:
        css = Path(folder) / "userChrome.css"
        css.write_bytes(original)
        add_import(css)
        edited = css.read_bytes()
        assert edited.startswith(b"\xef\xbb\xbf") == bom
        assert uf.CSS_IMPORT.encode() in edited
        assert uf.without_css_import(edited.decode("utf-8-sig")) == body
        assert backup_path(css).read_bytes() == original
        assert [p.name for p in Path(folder).iterdir() if p.name.endswith(TEMP_SUFFIX)] == []
        again = css.read_bytes()
        add_import(css)  # idempotent: a second edit changes nothing
        assert css.read_bytes() == again
