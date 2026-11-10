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


def test_the_weekly_run_covers_the_current_release_the_beta_and_the_esr():
    workflow = load("firefox-weekly.yml")
    triggers = workflow[True]  # YAML reads the key `on` as the boolean True
    assert triggers["schedule"] and "workflow_dispatch" in triggers
    job = workflow["jobs"]["browser"]
    assert set(job["strategy"]["matrix"]["firefox"]) == {"latest", "latest-beta", "latest-esr"}
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    assert job["strategy"]["fail-fast"] is False  # one channel failing must not hide the other
    assert any("-m browser" in step.get("run", "") for step in job["steps"])


def test_every_firefox_name_in_the_weekly_matrix_is_one_the_setup_action_documents():
    """A typo would fail only on a Monday; these are the names browser-actions/setup-firefox has."""
    documented = {"latest", "latest-beta", "latest-devedition", "latest-nightly", "latest-esr"}
    names = load("firefox-weekly.yml")["jobs"]["browser"]["strategy"]["matrix"]["firefox"]
    assert names and set(names) <= documented and len(names) == len(set(names))


def test_the_regular_ci_does_not_run_on_a_schedule():
    assert "schedule" not in load("ci.yml")[True]


def test_every_test_job_uploads_a_doctor_report_without_failing_on_it():
    job = load("ci.yml")["jobs"]["test"]
    assert set(job["strategy"]["matrix"]["os"]) == {
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
    }
    steps = job["steps"]
    names = [step.get("name") for step in steps]
    tests = names.index("Test")
    doctor = steps[tests + 1]
    assert "doctor --json --save doctor.json" in doctor["run"]
    assert doctor["continue-on-error"] is True  # a runner may have no Firefox: exit code 1 is fine
    upload = steps[tests + 2]
    assert upload["uses"] == "actions/upload-artifact@v4" and upload["if"] == "always()"
    assert upload["with"]["name"] == "doctor-${{ matrix.os }}-py${{ matrix.python }}"
    assert upload["with"]["path"] == "doctor.json"
    assert upload["with"]["if-no-files-found"] == "ignore"


def test_the_ci_permissions_stay_read_only():
    workflow = load("ci.yml")
    assert workflow["permissions"] == {"contents": "read"}  # uploading an artifact needs no more
    assert all("permissions" not in job for job in workflow["jobs"].values())
