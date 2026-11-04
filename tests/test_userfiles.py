from peek_a_foxy import userfiles as uf


def test_import_is_added_as_first_line_and_user_rules_are_kept():
    result = uf.with_css_import("body { color: red; }\n")
    assert result.splitlines() == [uf.CSS_IMPORT, "body { color: red; }"]


def test_import_on_an_empty_file():
    assert uf.with_css_import("") == uf.CSS_IMPORT + "\n"


def test_import_is_idempotent_and_moves_to_the_top():
    once = uf.with_css_import("a{}\n")
    assert uf.with_css_import(once) == once
    assert uf.with_css_import(f"a{{}}\n{uf.CSS_IMPORT}\n").splitlines()[0] == uf.CSS_IMPORT


def test_legacy_import_is_replaced():
    result = uf.with_css_import(f"{uf.LEGACY_CSS_IMPORT}\nbody{{}}\n")
    assert uf.LEGACY_CSS_IMPORT not in result
    assert result.splitlines() == [uf.CSS_IMPORT, "body{}"]


def test_without_import_keeps_user_rules():
    text = uf.with_css_import("body{}\n")
    assert uf.without_css_import(text) == "body{}\n"


def test_set_pref_appends_and_replaces():
    text = uf.set_pref("", "a.b", True)
    assert text == 'user_pref("a.b", true);\n'
    assert uf.set_pref(text, "a.b", False) == 'user_pref("a.b", false);\n'


def test_set_pref_keep_existing_leaves_a_user_value_alone():
    text = 'user_pref("a.b", true);\n'
    assert uf.set_pref(text, "a.b", False, keep_existing=True) == text
    assert 'user_pref("c.d", false);' in uf.set_pref(text, "c.d", False, keep_existing=True)


def test_remove_pref_only_removes_the_named_pref():
    text = 'user_pref("a.b", true);\nuser_pref("a.bc", true);\n'
    assert uf.remove_pref(text, "a.b") == 'user_pref("a.bc", true);\n'


# --- line endings, final newline, odd characters -------------------------------------------


def test_crlf_files_keep_their_line_endings():
    text = 'user_pref("a", 1);\r\nuser_pref("b", 2);\r\n'
    result = uf.set_pref(text, "peekafoxy.tabs.autohide", False)
    assert result.count("\r\n") == 3 and "\n" not in result.replace("\r\n", "")
    css = uf.with_css_import("body{}\r\n")
    assert css == f"{uf.CSS_IMPORT}\r\nbody{{}}\r\n"


def test_a_noop_returns_the_input_unchanged_even_without_a_final_newline():
    text = f"{uf.CSS_IMPORT}\nbody{{}}"  # no trailing newline
    assert uf.with_css_import(text) is text
    assert uf.without_css_import("body{}") == "body{}"
    assert uf.remove_pref("x", "a.b") == "x"
    assert uf.set_pref('user_pref("a.b", true);', "a.b", True) == 'user_pref("a.b", true);'


def test_unicode_line_separators_are_not_treated_as_line_breaks():
    text = "a b\x0bc\x1cd\n"
    assert uf.with_css_import(text) == f"{uf.CSS_IMPORT}\n{text}"


def test_a_leading_charset_stays_first():
    result = uf.with_css_import('@charset "UTF-8";\nbody{}\n')
    assert result.splitlines()[:2] == ['@charset "UTF-8";', uf.CSS_IMPORT]


def test_lines_without_a_trailing_newline_get_the_new_pref_on_its_own_line():
    assert uf.set_pref('user_pref("a", 1);', "b.c", True) == (
        'user_pref("a", 1);\nuser_pref("b.c", true);'
    )


# --- pref matching ---------------------------------------------------------------------------


def test_commented_out_prefs_do_not_count_as_set():
    text = '// user_pref("peekafoxy.tabs.autohide", true);\n'
    assert not uf.has_pref(text, uf.TABS_PREF)
    assert uf.set_pref(text, uf.TABS_PREF, False, keep_existing=True).endswith(
        'user_pref("peekafoxy.tabs.autohide", false);\n'
    )


def test_pref_spacing_variants_are_recognized():
    for line in (
        'user_pref("a.b",true);',
        'user_pref( "a.b" , true );',
        '  user_pref("a.b", true);',
    ):
        assert uf.has_pref(line + "\n", "a.b")


def test_a_non_boolean_user_value_is_kept():
    text = 'user_pref("a.b", "something");\n'
    assert uf.set_pref(text, "a.b", False, keep_existing=True) == text


def test_set_pref_rewrites_in_place_and_collapses_duplicates():
    text = (
        'user_pref("x", 1);\nuser_pref("a.b", true);\nuser_pref("y", 2);\nuser_pref("a.b", true);\n'
    )
    assert uf.set_pref(text, "a.b", False).splitlines() == [
        'user_pref("x", 1);',
        'user_pref("a.b", false);',
        'user_pref("y", 2);',
    ]


def test_get_bool_pref():
    text = (
        'user_pref("a", true);\nuser_pref("b",false );\nuser_pref("c", "x");\n'
        '// user_pref("d", true);\n'
    )
    assert uf.get_bool_pref(text, "a") is True
    assert uf.get_bool_pref(text, "b") is False
    assert uf.get_bool_pref(text, "c") is None  # not a boolean
    assert uf.get_bool_pref(text, "d") is None  # commented out
    assert uf.get_bool_pref(text, "missing") is None
