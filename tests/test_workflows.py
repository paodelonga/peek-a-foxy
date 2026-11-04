"""Guards for CI files that nothing else would notice breaking (a schedule that stops firing)."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def load(name: str) -> dict:
    path = WORKFLOWS / name
    if not path.is_file():
        pytest.skip("not a source checkout")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_weekly_run_covers_the_current_release_and_the_beta():
    workflow = load("firefox-weekly.yml")
    triggers = workflow[True]  # YAML reads the key `on` as the boolean True
    assert triggers["schedule"] and "workflow_dispatch" in triggers
    job = workflow["jobs"]["browser"]
    assert set(job["strategy"]["matrix"]["firefox"]) == {"latest", "latest-beta"}
    assert job["strategy"]["fail-fast"] is False  # one channel failing must not hide the other
    assert any("-m browser" in step.get("run", "") for step in job["steps"])


def test_the_regular_ci_does_not_run_on_a_schedule():
    assert "schedule" not in load("ci.yml")[True]
