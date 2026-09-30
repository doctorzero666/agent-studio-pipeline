"""Public-install behavior, privacy boundaries and cross-task protections."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import TaskWorkspace

from studio_tools import scaffold
from studio_tools.check_studio import main as check
from studio_tools.task_files import TaskError


@pytest.fixture
def private_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n name = Example User\n email = test@example.invalid\n")
    monkeypatch.setenv("HOME", str(home))
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    return home


def test_new_workspace_end_to_end(tmp_path, private_home):
    studio = scaffold.initialize(tmp_path / "workspace")
    app = scaffold.add_app(studio, "sample")
    card = scaffold.add_task(studio, "sample", "DEMO-001", "Add a greeting")
    scaffold.add_task(studio, "sample", "DEMO-002", "Handle invalid input")
    assert check([str(studio)]) == 0
    assert len(scaffold.status(studio)) == 2
    assert card.is_file() and (app / ".github/workflows/ci.yml").is_file()
    assert (app / ".claude/hooks/guard_bash.py").is_file()
    assert subprocess.check_output(["git", "-C", str(app), "branch", "--show-current"], text=True).strip() == "main"
    # A clone has all private control files without copying the ignored application or credentials.
    restored = tmp_path / "restored"
    subprocess.run(["git", "clone", "--quiet", str(studio.parent), str(restored)], check=True)
    assert check([str(restored / "studio")]) == 0
    assert not (restored / "sample").exists()


def test_init_never_overwrites_existing_directory(tmp_path, private_home):
    content = tmp_path / "keep.txt"
    content.write_text("keep")
    with pytest.raises(TaskError, match="exists"):
        scaffold.initialize(tmp_path)
    assert content.read_text() == "keep"


def test_generated_application_tests_run_without_source_pythonpath(tmp_path, private_home):
    studio = scaffold.initialize(tmp_path / "workspace")
    app = scaffold.add_app(studio, "sample")
    # Exercise the console entry point used by the generated justfile, with
    # installed dev tools but without this repository's import-path assistance.
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTEST_ADDOPTS"}}
    result = subprocess.run(
        [str(Path(sys.executable).with_name("pytest")), "-q"],
        cwd=app,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout


@pytest.mark.parametrize("value", ["../escape", "a/b", "-option", "space name", "a" * 65, ""])
def test_invalid_application_name(value):
    with pytest.raises(TaskError):
        scaffold.name(value)


@pytest.mark.parametrize("branch", ["main", "agent/codex/TOOLS-010", "detached"])
def test_launch_rejects_wrong_task_or_detached(workspace: TaskWorkspace, branch):
    ws = workspace
    ws.git(ws.app, "worktree", "add", "-b", "temporary", str(ws.worktree), "main")
    if branch == "detached":
        ws.git(ws.worktree, "checkout", "--detach")
    elif branch == "main":
        ws.git(ws.app, "branch", "-m", "base")
        ws.git(ws.worktree, "branch", "-m", "main")
    else:
        ws.git(ws.worktree, "branch", "-m", branch)
    before = ws.card.read_bytes()
    result = ws.cli("launcher", "codex", "sample-app", "TOOLS-009")
    assert result.returncode != 0 and ws.card.read_bytes() == before
    assert not (ws.root.parent / "codex-called.json").exists()


def test_checkpoint_rejects_cross_task_and_main(workspace):
    ws = workspace
    ws.git(ws.app, "worktree", "add", "-b", "agent/codex/TOOLS-009", str(ws.worktree), "main")
    before = ws.card.read_bytes()
    assert ws.cli("checkpoint", "TOOLS-009", "wrong", cwd=ws.app).returncode == 1
    assert ws.cli("checkpoint", "TOOLS-010", "wrong", cwd=ws.worktree).returncode == 1
    assert ws.card.read_bytes() == before


def test_git_environment_cannot_redirect_launch(workspace):
    ws = workspace
    original = ws.env.copy()
    ws.env.update(GIT_DIR=str(ws.root / ".git"), GIT_WORK_TREE=str(ws.root), GIT_INDEX_FILE=str(ws.root / "evil-index"))
    result = ws.cli("launcher", "codex", "sample-app", "TOOLS-009")
    assert result.returncode == 0, result.stderr
    ws.env = original
    assert ws.git(ws.worktree, "branch", "--show-current") == "agent/codex/TOOLS-009"
    assert not (ws.root / "evil-index").exists()


def test_supervisor_success_and_no_raw_output_receipt(workspace):
    ws = workspace
    (ws.studio / "AGENTS.md").write_text("# Rules\n")
    ws.git(ws.root, "add", ".")
    ws.git(ws.root, "commit", "-qm", "chore: rules")
    prompt = ws.root.parent / "prompt.txt"
    prompt.write_text("Inspect this synthetic task")
    result = ws.cli("runner", "codex", "sample-app", "TOOLS-009", "--prompt-file", str(prompt))
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["attempts"][0]["outcome"] == "exited"
    assert "prompt" not in Path(receipt["receipt"]).read_text()
    assert "Supervisor" in ws.card.read_text()
    # The supervisor never treats CLI exit 0 as task acceptance or releases a writer silently.
    assert "| 状态 | doing |" in ws.card.read_text()


@pytest.mark.parametrize(("message", "expected_calls"), [("usage limit exceeded", 2), ("unknown failure", 1)])
def test_supervisor_only_explicit_quota_fallback(workspace, message, expected_calls):
    ws = workspace
    (ws.studio / "AGENTS.md").write_text("# Rules\n")
    ws.git(ws.root, "add", ".")
    ws.git(ws.root, "commit", "-qm", "chore: rules")
    binary = Path(ws.env["PATH"].split(os.pathsep)[0]) / "codex"
    binary.write_text(f"#!{sys.executable}\nprint({message!r})\nraise SystemExit(1)\n")
    prompt = ws.root.parent / "prompt.txt"
    prompt.write_text("Synthetic task only")
    result = ws.cli("runner", "codex", "sample-app", "TOOLS-009", "--fallback", "claude", "--prompt-file", str(prompt))
    assert len(json.loads(result.stdout)["attempts"]) == expected_calls
    assert (ws.root.parent / "claude-called.json").exists() == (expected_calls == 2)


def test_supervisor_timeout_preserves_claim_and_never_falls_back(workspace):
    ws = workspace
    (ws.studio / "AGENTS.md").write_text("# Rules\n")
    ws.git(ws.root, "add", ".")
    ws.git(ws.root, "commit", "-qm", "chore: rules")
    binary = Path(ws.env["PATH"].split(os.pathsep)[0]) / "codex"
    binary.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    prompt = ws.root.parent / "prompt.txt"
    prompt.write_text("Synthetic task")
    result = ws.cli(
        "runner",
        "codex",
        "sample-app",
        "TOOLS-009",
        "--fallback",
        "claude",
        "--timeout",
        "1",
        "--prompt-file",
        str(prompt),
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["attempts"][0]["outcome"] == "timeout"
    assert not (ws.root.parent / "claude-called.json").exists()
    assert "| 状态 | doing |" in ws.card.read_text()


def test_rejected_supervisor_cannot_checkpoint_another_writer(workspace):
    ws = workspace
    (ws.studio / "AGENTS.md").write_text("# Rules\n")
    ws.git(ws.root, "add", ".")
    ws.git(ws.root, "commit", "-qm", "chore: rules")
    assert ws.cli("launcher", "codex", "sample-app", "TOOLS-009").returncode == 0
    before = ws.card.read_bytes(), ws.git(ws.root, "rev-parse", "HEAD")
    prompt = ws.root.parent / "prompt.txt"
    prompt.write_text("Do not take over")
    result = ws.cli("runner", "claude", "sample-app", "TOOLS-009", "--prompt-file", str(prompt))
    assert result.returncode == 3
    assert before == (ws.card.read_bytes(), ws.git(ws.root, "rev-parse", "HEAD"))
    assert not (ws.root.parent / "claude-called.json").exists()


def test_timeout_stops_sigterm_resistant_descendant(tmp_path):
    from studio_tools.runner import execute, group_exists

    script = tmp_path / "child.py"
    pid = tmp_path / "pgid.txt"
    script.write_text(
        "import subprocess, sys, time, os\n"
        f"open({str(pid)!r}, 'w').write(str(os.getpid()))\n"
        "subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
        "time.sleep(60)\n"
    )
    result = execute([sys.executable, str(script)], tmp_path, dict(os.environ), 1)
    assert result["outcome"] == "timeout"
    assert result["group_stopped"]
    assert not group_exists(int(pid.read_text()))


def test_application_session_hook_reads_its_own_card(workspace):
    ws = workspace
    assert ws.cli("launcher", "codex", "sample-app", "TOOLS-009").returncode == 0
    decoy = ws.studio / "项目/应用/studio-tools/tasks/TOOLS-009/task.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("## 当前检查点\nPRIVATE-DECOY-NOT-FOR-THIS-APP\n")
    hook = Path(__file__).parents[1] / ".claude/hooks/session_start.py"
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"cwd": str(ws.worktree)}),
        text=True,
        capture_output=True,
        env=ws.env,
        check=False,
    )
    assert result.returncode == 0 and "已有检查点" in result.stdout
    assert "PRIVATE-DECOY" not in result.stdout


def test_new_task_failed_commit_rolls_back_and_can_retry(tmp_path, private_home):
    studio = scaffold.initialize(tmp_path / "workspace")
    scaffold.add_app(studio, "sample")
    root = studio.parent
    before = (studio / "registry/任务队列.md").read_bytes(), (studio / "STATUS.md").read_bytes()
    hook = root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(TaskError, match="creation failed"):
        scaffold.add_task(studio, "sample", "DEMO-001", "Synthetic failure")
    assert before == ((studio / "registry/任务队列.md").read_bytes(), (studio / "STATUS.md").read_bytes())
    assert subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True) == ""
    hook.unlink()
    assert scaffold.add_task(studio, "sample", "DEMO-001", "Retry after fixing hook").exists()
