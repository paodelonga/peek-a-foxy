"""Property-based tests: whatever the user's files contain, our edits must be safe."""

from hypothesis import given
from hypothesis import strategies as st

from peek_a_foxy import userfiles as uf

# Any text, including CR, unusual separators and non-ASCII; '\n' is handled by joining lines.
line = st.text(
    st.characters(blacklist_characters="\n\r", blacklist_categories=("Cs",)), max_size=40
)
documents = st.builds(
    lambda lines, ending, trailing: ending.join(lines) + (ending if trailing else ""),
    st.lists(line, max_size=8),
    st.sampled_from(["\n", "\r\n"]),
    st.booleans(),
)
pref_names = st.sampled_from(["a.b", "userchrome.tabs.autohide", "x.y.z"])


def user_lines(text: str) -> list[str]:
    """The lines of ``text`` that are not ours (compared without line endings)."""
    return [
        part
        for part in text.replace("\r\n", "\n").split("\n")
        if part.strip() not in uf.OWN_IMPORTS
    ]


@given(documents)
def test_with_css_import_is_idempotent(text):
    once = uf.with_css_import(text)
    assert uf.with_css_import(once) == once


@given(documents)
def test_with_css_import_never_touches_the_users_lines(text):
    result = uf.with_css_import(text)
    assert uf.CSS_IMPORT in result
    assert [part for part in user_lines(result) if part != ""] == [
        part for part in user_lines(text) if part != ""
    ]


@given(documents)
def test_import_then_remove_restores_the_users_content(text):
    restored = uf.without_css_import(uf.with_css_import(text))
    assert [p for p in user_lines(restored) if p] == [p for p in user_lines(text) if p]


@given(documents, pref_names, st.booleans())
def test_set_pref_is_idempotent(text, name, value):
    once = uf.set_pref(text, name, value)
    assert uf.set_pref(once, name, value) == once
    assert uf.has_pref(once, name)


@given(documents, pref_names, st.booleans())
def test_set_pref_keeps_every_unrelated_line(text, name, value):
    before = [p for p in text.replace("\r\n", "\n").split("\n") if not uf.has_pref(p, name)]
    after_text = uf.set_pref(text, name, value)
    after = [p for p in after_text.replace("\r\n", "\n").split("\n") if not uf.has_pref(p, name)]
    assert [p for p in after if p] == [p for p in before if p]


@given(documents, pref_names)
def test_remove_pref_removes_it_and_is_idempotent(text, name):
    once = uf.remove_pref(text, name)
    assert not uf.has_pref(once, name)
    assert uf.remove_pref(once, name) == once


@given(documents, pref_names, st.booleans())
def test_keep_existing_never_changes_a_present_pref(text, name, value):
    if uf.has_pref(text, name):
        assert uf.set_pref(text, name, value, keep_existing=True) == text
