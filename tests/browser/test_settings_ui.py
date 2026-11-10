from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("locale", ["constructor", "__proto__", "toString", "hasOwnProperty-US"])
def test_a_language_named_like_a_property_of_every_object_gets_english(browser, locale):
    """Adversarial: ``STRINGS[locale]`` used to answer with Object.prototype's own members."""
    assert (
        browser.diag("return Peek.textFor(arguments[0]).settings.supportGroup;", locale)
        == "Support"
    )
