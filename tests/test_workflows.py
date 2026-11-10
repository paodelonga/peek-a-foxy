"""Guards for CI files that nothing else would notice breaking (a schedule that stops firing)."""

from __future__ import annotations

import re
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
    assert upload["uses"].startswith("actions/upload-artifact@") and upload["if"] == "always()"
    assert upload["with"]["name"] == "doctor-${{ matrix.os }}-py${{ matrix.python }}"
    assert upload["with"]["path"] == "doctor.json"
    assert upload["with"]["if-no-files-found"] == "ignore"


def test_the_ci_permissions_stay_read_only():
    workflow = load("ci.yml")
    assert workflow["permissions"] == {"contents": "read"}  # uploading an artifact needs no more
    assert all("permissions" not in job for job in workflow["jobs"].values())


# --- the supply chain of the workflows (PF-19) and the lowest versions (PF-15) ------------------

ROOT = Path(__file__).resolve().parents[1]
USES = re.compile(r"^\s*-?\s*uses:\s*(?P<action>\S+?)@(?P<ref>\S+)(?P<comment>\s+#.*)?$")


def uses_lines(name: str) -> list[tuple[str, str, str]]:
    path = WORKFLOWS / name
    if not path.is_file():
        pytest.skip("not a source checkout")
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = USES.match(line)
        if match:
            found.append((match["action"], match["ref"], (match["comment"] or "").strip()))
    return found


@pytest.mark.parametrize("name", ["ci.yml", "firefox-weekly.yml"])
def test_every_action_is_pinned_by_a_full_commit_with_its_version_in_a_comment(name: str):
    """A tag can be moved to other code: the commit cannot (the third-party action most of all)."""
    found = uses_lines(name)
    assert found, "no action found: the pattern or the file changed"
    for action, ref, comment in found:
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{action}@{ref} is not a commit"
        assert re.fullmatch(r"#\s*v\d+(\.\d+){0,2}", comment), (action, comment)


@pytest.mark.parametrize("name", ["ci.yml", "firefox-weekly.yml"])
def test_no_checkout_leaves_the_token_in_the_git_configuration(name: str):
    workflow = load(name)
    checkouts = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    for step in checkouts:  # no job pushes, so none needs the token after the checkout
        assert step["with"]["persist-credentials"] is False


def test_no_workflow_asks_for_more_than_read_access_to_the_contents():
    for name in ("ci.yml", "firefox-weekly.yml"):
        workflow = load(name)
        assert workflow["permissions"] == {"contents": "read"}
        assert all("permissions" not in job for job in workflow["jobs"].values())


def test_dependabot_still_updates_the_actions_and_the_python_packages():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    kinds = {entry["package-ecosystem"] for entry in config["updates"]}
    assert {"github-actions", "pip"} <= kinds  # pinned commits are moved by it, with the comment


# --- nothing hangs for six hours, a superseded run stops, the newest Python is tried (review 3) ---

ALL_WORKFLOWS = ["ci.yml", "firefox-weekly.yml"]


@pytest.mark.parametrize("name", ALL_WORKFLOWS)
def test_every_job_has_a_time_limit_that_is_neither_missing_nor_the_default_of_six_hours(name):
    """A hung Firefox or a stalled network call would otherwise burn 360 minutes of a runner."""
    for job_name, job in load(name)["jobs"].items():
        limit = job.get("timeout-minutes")
        assert isinstance(limit, int) and not isinstance(limit, bool), (name, job_name)
        assert 0 < limit <= 60, (name, job_name, limit)


def test_the_browser_jobs_get_more_time_than_the_unit_jobs_but_not_unlimited():
    jobs = load("ci.yml")["jobs"]
    assert jobs["browser"]["timeout-minutes"] > jobs["test"]["timeout-minutes"]


def test_a_newer_push_to_a_pull_request_cancels_the_older_run_but_pushes_to_branches_are_kept():
    concurrency = load("ci.yml")["concurrency"]
    assert "github.workflow" in concurrency["group"]
    assert "github.event.pull_request.number" in concurrency["group"]  # one group per PR
    cancel = concurrency["cancel-in-progress"]
    assert isinstance(cancel, str)  # an expression; a plain true would also cancel pushes
    assert "github.event_name == 'pull_request'" in cancel  # an expression, not a plain true


def test_the_test_matrix_covers_the_oldest_and_the_newest_python_the_suite_was_tried_on():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    floor = re.search(r'requires-python\s*=\s*">=\s*(\d+\.\d+)"', text)
    assert floor, "requires-python is no longer a plain floor: update this test"
    versions = load("ci.yml")["jobs"]["test"]["strategy"]["matrix"]["python"]
    assert floor.group(1) in versions
    assert all(isinstance(v, str) for v in versions)  # unquoted, 3.10 would be read as 3.1
    newest = max(tuple(map(int, v.split("."))) for v in versions)
    assert newest >= (3, 14)


def test_the_lowest_job_runs_the_whole_suite_and_says_what_it_does_not_lower():
    job = load("ci.yml")["jobs"]["lowest"]
    runs = [step.get("run", "") for step in job["steps"]]
    assert "python -m pytest" in [run.strip() for run in runs]  # no -k, -m or path: all of it
    assert any("pip check" in run for run in runs)
    comment = [
        line
        for line in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#")
    ]
    wording = " ".join(line.lstrip("# ") for line in comment)
    assert "Typer and Rich" in wording and "stays at the newest" in wording


PRE_COMMIT_REV = re.compile(r"^\s*rev:\s*(?P<rev>\S+)(?P<comment>\s+#.*)?$")


def test_every_pre_commit_hook_is_pinned_by_a_full_commit_with_its_version_in_a_comment():
    """A tag of a hook repository can be moved; CI runs these hooks on every pull request."""
    path = ROOT / ".pre-commit-config.yaml"
    if not path.is_file():
        pytest.skip("not a source checkout")
    found = [
        PRE_COMMIT_REV.match(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("rev:")
    ]
    assert found and all(found), "a rev: line that the pattern does not understand"
    for match in found:
        assert match is not None
        assert re.fullmatch(r"[0-9a-f]{40}", match["rev"]), match["rev"]
        assert re.fullmatch(r"\s*# frozen: v\d+(\.\d+){1,2}", match["comment"] or "")
    repos = yaml.safe_load(path.read_text(encoding="utf-8"))["repos"]
    assert len(repos) == len(found)  # no repository escaped the check


def floor_of(requirement: str) -> str:
    match = re.search(r">=\s*([0-9][0-9.]*)", requirement)
    assert match, requirement
    return match.group(1)


def declared(package: str) -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(rf'"({package}[^"]*)"', text.split("[project.optional")[0])
    assert match, package
    return match.group(1)


def test_the_lowest_job_installs_exactly_the_lower_bounds_of_pyproject():
    steps = load("ci.yml")["jobs"]["lowest"]["steps"]
    run = " ".join(step.get("run", "") for step in steps)
    for package in ("typer", "rich"):
        assert f'"{package}=={floor_of(declared(package))}"' in run or (
            f'"{package}=={floor_of(declared(package))}.0"' in run
        ), (package, run)
    assert any(step.get("with", {}).get("python-version") == "3.10" for step in steps)


@pytest.mark.parametrize("package", ["typer", "rich"])
def test_the_runtime_dependencies_have_a_lower_and_an_upper_bound(package: str):
    requirement = declared(package)
    assert ">=" in requirement and "<" in requirement, requirement


def test_the_workflow_tests_are_not_silently_skipped_for_want_of_pyyaml():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"pyyaml' in text.lower()
