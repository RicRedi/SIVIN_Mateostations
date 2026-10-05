"""Invariants of ``.github/workflows/pipeline.yml`` (WP-4.1).

The shell steps that decide something (the local-time gate, the exit-code judgement, the
creation of the ``data`` branch) are executed here with bash and git against a local bare
repository; nothing is contacted over the network.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pipeline.yml"

BASH = shutil.which("bash")
GIT = shutil.which("git")

needs_bash = pytest.mark.skipif(BASH is None, reason="bash is not available")
needs_git = pytest.mark.skipif(BASH is None or GIT is None, reason="bash or git not available")


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def triggers(workflow: Mapping[Any, Any]) -> Mapping[str, Any]:
    """The ``on:`` mapping (YAML 1.1 reads the bare key ``on`` as ``True``)."""
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return value


def step(workflow: Mapping[Any, Any], job: str, name: str) -> Mapping[str, Any]:
    for item in workflow["jobs"][job]["steps"]:
        if item.get("name") == name:
            return item
    raise AssertionError(f"no step {name!r} in job {job!r}")


def run_script(
    script: str, cwd: Path, env: Mapping[str, str], workflow: Mapping[Any, Any]
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Run a step's script like GitHub does (``bash -eo pipefail``); return its outputs."""
    output = cwd / "github-output.txt"
    output.write_text("", encoding="utf-8")
    full_env = {
        **os.environ,
        **{key: str(value) for key, value in workflow["env"].items()},
        **env,
        "GITHUB_OUTPUT": str(output),
    }
    assert BASH is not None
    process = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = output.read_text(encoding="utf-8").splitlines()
    return process, dict(line.split("=", 1) for line in lines if "=" in line)


class TestTriggers:
    def test_two_utc_crons_and_a_manual_trigger(self, workflow: dict[Any, Any]) -> None:
        on = triggers(workflow)
        assert sorted(item["cron"] for item in on["schedule"]) == ["0 4 * * *", "0 5 * * *"]
        inputs = on["workflow_dispatch"]["inputs"]
        assert set(inputs) == {"skip_fetch", "full_site_build"}
        assert all(
            item["type"] == "boolean" and item["default"] is False for item in inputs.values()
        )

    def test_one_run_at_a_time_never_cancelled(self, workflow: dict[Any, Any]) -> None:
        assert workflow["concurrency"] == {"group": "pipeline", "cancel-in-progress": False}

    def test_local_time_settings(self, workflow: dict[Any, Any]) -> None:
        assert workflow["env"]["LOCAL_TIMEZONE"] == "Europe/Prague"
        assert workflow["env"]["LOCAL_RUN_HOUR"] == "6"
        assert workflow["jobs"]["collect"]["needs"] == "gate"
        assert workflow["jobs"]["collect"]["if"] == "needs.gate.outputs.run == 'true'"


@needs_bash
class TestGate:
    """The gate lets through only the cron that is 06:00 in Prague on the day it fires."""

    @pytest.fixture
    def fake_date(self, tmp_path: Path) -> Path:
        """A ``date`` that prints the hour and offset given in FAKE_HOUR / FAKE_OFFSET."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "date"
        fake.write_text(
            '#!/bin/sh\ncase "$1" in\n  +%H) echo "$FAKE_HOUR" ;;\n'
            '  +%z) echo "$FAKE_OFFSET" ;;\n  *) exit 1 ;;\nesac\n',
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return bin_dir

    @pytest.mark.parametrize(
        ("schedule", "hour", "offset", "expected"),
        [
            ("0 4 * * *", "06", "+0200", "true"),
            ("0 5 * * *", "07", "+0200", "false"),
            ("0 4 * * *", "05", "+0100", "false"),
            ("0 5 * * *", "06", "+0100", "true"),
            ("0 4 * * *", "07", "+0200", "true"),
            ("0 5 * * *", "08", "+0200", "false"),
        ],
        ids=[
            "summer-04utc",
            "summer-05utc",
            "winter-04utc",
            "winter-05utc",
            "summer-04utc-delayed-an-hour",
            "summer-05utc-delayed-an-hour",
        ],
    )
    def test_schedule(
        self,
        workflow: dict[Any, Any],
        fake_date: Path,
        tmp_path: Path,
        schedule: str,
        hour: str,
        offset: str,
        expected: str,
    ) -> None:
        script = step(workflow, "gate", "Continue only for the cron that is 06:00 in Prague today")
        env = {
            "EVENT": "schedule",
            "SCHEDULE": schedule,
            "FAKE_HOUR": hour,
            "FAKE_OFFSET": offset,
            "PATH": f"{fake_date}{os.pathsep}{os.environ['PATH']}",
        }
        process, outputs = run_script(script["run"], tmp_path, env, workflow)
        assert process.returncode == 0, process.stderr
        assert outputs == {"run": expected}

    def test_manual_runs_always_pass(self, workflow: dict[Any, Any], tmp_path: Path) -> None:
        script = step(workflow, "gate", "Continue only for the cron that is 06:00 in Prague today")
        process, outputs = run_script(
            script["run"], tmp_path, {"EVENT": "workflow_dispatch", "SCHEDULE": ""}, workflow
        )
        assert process.returncode == 0, process.stderr
        assert outputs == {"run": "true"}

    def test_uses_the_local_clock_of_prague(self, workflow: dict[Any, Any]) -> None:
        script = step(workflow, "gate", "Continue only for the cron that is 06:00 in Prague today")
        assert 'TZ="$LOCAL_TIMEZONE" date +%H' in script["run"]
        assert script["env"]["SCHEDULE"] == "${{ github.event.schedule }}"


@needs_bash
class TestExitCodes:
    @pytest.mark.parametrize(
        ("code", "publish"),
        [
            ("0", "true"),
            ("1", "true"),
            ("4", "true"),
            ("2", "false"),
            ("3", "false"),
            ("5", "false"),
            ("130", "false"),
            ("", "false"),
        ],
    )
    def test_judgement(
        self, workflow: dict[Any, Any], tmp_path: Path, code: str, publish: str
    ) -> None:
        script = step(workflow, "collect", "Judge the exit code")["run"]
        process, outputs = run_script(script, tmp_path, {"CODE": code}, workflow)
        assert process.returncode == 0, process.stderr
        assert outputs == {"publish": publish}
        if code == "4":
            assert "::warning::Portal unavailable" in process.stdout

    def test_summary_before_commit_and_failure(self, workflow: dict[Any, Any]) -> None:
        names = [item.get("name") for item in workflow["jobs"]["collect"]["steps"]]
        summary = names.index("Job summary")
        assert names.index("Run the pipeline") < summary < names.index("Judge the exit code")
        assert summary < names.index("Commit and push the data branch")
        assert names[-1] == "Fail on a broken run"
        assert step(workflow, "collect", "Job summary")["if"] == "always()"
        commit = step(workflow, "collect", "Commit and push the data branch")
        assert commit["if"] == "steps.judge.outputs.publish == 'true'"
        fail = step(workflow, "collect", "Fail on a broken run")
        assert fail["if"] == "steps.judge.outputs.publish != 'true'"

    def test_the_run_step_keeps_going_to_record_the_code(self, workflow: dict[Any, Any]) -> None:
        script = step(workflow, "collect", "Run the pipeline")["run"]
        assert script.lstrip().startswith("set +e")
        assert 'echo "code=$code" >> "$GITHUB_OUTPUT"' in script

    def test_summary_is_the_markdown_report_of_this_run(self, workflow: dict[Any, Any]) -> None:
        script = step(workflow, "collect", "Job summary")["run"]
        assert "report --format markdown --run latest" in script
        assert '--since "$STARTED"' in script
        assert '--outcome "$CODE"' in script
        assert '>> "$GITHUB_STEP_SUMMARY"' in script


class TestSafety:
    def test_no_verbose_logging(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "DEBUG" not in text.upper()
        assert "set -x" not in text
        invocations = re.findall(r"^\s*(?:if ! )?sivin .*$", text, flags=re.MULTILINE)
        assert invocations
        assert all("--log-level INFO" in line or '"${args[@]}"' in line for line in invocations)
        assert text.count("args=(--log-level INFO") == 2

    def test_minimal_permissions(self, workflow: dict[Any, Any]) -> None:
        jobs = workflow["jobs"]
        assert workflow["permissions"] == {}
        assert jobs["gate"]["permissions"] == {}
        assert jobs["collect"]["permissions"] == {"contents": "write"}
        assert jobs["build-site"]["permissions"] == {"contents": "read"}
        assert jobs["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}

    def test_never_force_push(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        pushes = [line for line in text.splitlines() if "git push" in line]
        assert pushes == ['            git push origin "HEAD:refs/heads/$DATA_BRANCH"']
        assert "--force" not in text
        assert "force" not in text.lower()

    def test_actions_pinned_to_major_versions(self, workflow: dict[Any, Any]) -> None:
        uses = [
            item["uses"]
            for job in workflow["jobs"].values()
            for item in job["steps"]
            if "uses" in item
        ]
        assert uses
        assert all(re.fullmatch(r"[\w-]+/[\w-]+@v\d+", value) for value in uses), uses

    def test_every_job_has_a_timeout(self, workflow: dict[Any, Any]) -> None:
        assert all(job["timeout-minutes"] > 0 for job in workflow["jobs"].values())

    def test_secrets_only_reach_sivin_through_the_environment(
        self, workflow: dict[Any, Any]
    ) -> None:
        holders = []
        for job_name, job in workflow["jobs"].items():
            for item in job["steps"]:
                assert "SIVIN_PASSWORD" not in item.get("run", "")
                assert "secrets." not in item.get("run", "")
                if "SIVIN_PASSWORD" in item.get("env", {}):
                    holders.append((job_name, item["name"]))
        assert holders == [("collect", "Run the pipeline"), ("collect", "Job summary")]

    def test_artifacts_hold_no_downloads(self, workflow: dict[Any, Any]) -> None:
        upload = step(workflow, "collect", "Keep the summary and the quarantine reports")
        paths = upload["with"]["path"].split()
        assert paths == ["run-summary/run-summary.md", "data/quarantine/*.report.json"]
        assert upload["with"]["retention-days"] <= 14


class TestDeployment:
    def test_web_built_with_real_data_and_the_pages_base(self, workflow: dict[Any, Any]) -> None:
        build = step(workflow, "build-site", "Build the web portal")
        assert build["env"]["VITE_DEMO_DATA"] == "false"
        assert build["env"]["SITE_BASE"] == "/${{ github.event.repository.name }}/"
        site = step(workflow, "build-site", "Site data")["run"]
        assert "rm -rf web/public/data" in site
        assert "cp -a site/data web/public/data" in site
        upload = step(workflow, "build-site", "Upload the Pages artifact")
        assert upload["uses"].startswith("actions/upload-pages-artifact@")
        assert upload["with"]["path"] == "web/dist"

    def test_deploy_job(self, workflow: dict[Any, Any]) -> None:
        deploy = workflow["jobs"]["deploy"]
        assert deploy["needs"] == "build-site"
        assert deploy["environment"]["name"] == "github-pages"
        assert deploy["steps"][0]["uses"].startswith("actions/deploy-pages@")
        assert workflow["jobs"]["build-site"]["needs"] == "collect"

    def test_site_built_from_the_commit_of_this_run(self, workflow: dict[Any, Any]) -> None:
        checkout = step(workflow, "build-site", "Check out the data committed by this run")
        assert checkout["with"]["ref"] == "${{ needs.collect.outputs.data_sha }}"


@needs_git
class TestDataBranch:
    """The first run creates the orphan ``data`` branch; later runs check it out."""

    SCRIPT = "Check out the data branch (create it if missing)"

    @pytest.fixture
    def clone(self, tmp_path: Path) -> Path:
        assert GIT is not None
        origin = tmp_path / "origin.git"
        work = tmp_path / "work"
        git = [GIT, "-c", "user.name=test", "-c", "user.email=test@example.invalid"]
        subprocess.run([*git, "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run([*git, "clone", "-q", str(origin), str(work)], check=True)
        (work / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
        subprocess.run([*git, "-C", str(work), "add", "-A"], check=True)
        subprocess.run([*git, "-C", str(work), "commit", "-q", "-m", "main"], check=True)
        subprocess.run([*git, "-C", str(work), "push", "-q", "origin", "HEAD:main"], check=True)
        return work

    def test_creates_an_orphan_branch_that_keeps_data(
        self, workflow: dict[Any, Any], clone: Path
    ) -> None:
        script = step(workflow, "collect", self.SCRIPT)["run"]
        process, _ = run_script(script, clone, {}, workflow)
        assert process.returncode == 0, process.stderr
        branch = clone / ".data-branch"
        assert "::notice::Branch 'data' does not exist yet" in process.stdout
        assert (
            subprocess.run(
                [GIT or "git", "-C", str(branch), "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            == "data"
        )
        ignored = (branch / ".gitignore").read_text(encoding="utf-8").splitlines()
        rules = [line for line in ignored if line and not line.startswith("#")]
        assert rules == ["/data/downloads/", "/data/quarantine/", ".*.tmp"]
        assert (branch / "README.md").read_text(encoding="utf-8").startswith("# SIVIN")
        assert not (branch / "pyproject.toml").exists()
        assert (clone / "data").is_dir()

    def test_checks_out_an_existing_branch(self, workflow: dict[Any, Any], clone: Path) -> None:
        assert GIT is not None
        git = [GIT, "-c", "user.name=test", "-c", "user.email=test@example.invalid"]
        script = step(workflow, "collect", self.SCRIPT)["run"]
        assert run_script(script, clone, {}, workflow)[0].returncode == 0
        branch = clone / ".data-branch"
        stored = branch / "data" / "raw" / "77678271"
        stored.mkdir(parents=True)
        (stored / "2026.csv").write_text("synthetic\n", encoding="utf-8")
        subprocess.run([*git, "-C", str(branch), "add", "-A"], check=True)
        subprocess.run([*git, "-C", str(branch), "commit", "-q", "-m", "data"], check=True)
        subprocess.run(
            [*git, "-C", str(branch), "push", "-q", "origin", "HEAD:refs/heads/data"], check=True
        )
        subprocess.run(
            [*git, "-C", str(clone), "worktree", "remove", "--force", ".data-branch"], check=True
        )
        shutil.rmtree(clone / "data")
        process, _ = run_script(script, clone, {}, workflow)
        assert process.returncode == 0, process.stderr
        assert "does not exist yet" not in process.stdout
        assert (clone / "data" / "raw" / "77678271" / "2026.csv").read_text(encoding="utf-8") == (
            "synthetic\n"
        )
