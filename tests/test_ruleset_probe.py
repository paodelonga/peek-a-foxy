def test_this_fails_on_purpose():
    """Probe for the branch protection rules (issue #4). This branch is never merged."""
    assert False, "failing on purpose: a required check must block the merge"
