"""Checks against the real fx-autoconfig repository. Opt-in: ``pytest -m network``."""

import pytest

from peek_a_foxy import loader

pytestmark = pytest.mark.network


def test_the_pinned_commit_exists_upstream_and_has_the_files_we_install(monkeypatch):
    # Guards against the upstream repository being rewritten or reorganized.
    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)
    with loader.fetch_loader() as checkout:
        for name in loader.LOADER_FILES:
            assert (checkout / "program" / name).is_file()
        assert (checkout / "profile" / "chrome" / "utils" / "boot.sys.mjs").is_file()
        assert "userchromejs" in (checkout / "program" / "config.js").read_text()
