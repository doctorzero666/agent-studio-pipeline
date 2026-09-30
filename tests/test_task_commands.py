"""Cross-command concurrency and clone acceptance, entirely beneath tmp_path."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import TaskWorkspace


@pytest.mark.parametrize("command", ["launcher", "checkpoint"])
def test_task_commands_restore_crlf_card_on_commit_failure_and_allow_retry(
    workspace: TaskWorkspace, command: str
) -> None:
    ws = workspace
    ws.git(ws.root, "config", "core.autocrlf", "false")
    original = ws.card.read_bytes().replace(b"\n", b"\r\n")
    ws.card.write_bytes(original)
    ws.git(ws.root, "add", str(ws.card))
    ws.git(ws.root, "commit", "-qm", "chore: CRLF task card")
    before = ws.git(ws.root, "rev-parse", "HEAD")
    record = ws.install_agent()
    hook = ws.root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    args = ("codex", "sample-app", "TOOLS-009") if command == "launcher" else ("TOOLS-009", "retry checkpoint")

    cwd = ws.app
    if command == "checkpoint":
        ws.git(ws.app, "worktree", "add", "-b", "agent/codex/TOOLS-009", str(ws.worktree), "main")
        cwd = ws.worktree
    failed = ws.cli(command, *args, cwd=cwd)
    assert failed.returncode == 1, failed.stderr
    assert ws.card.read_bytes() == original
    assert ws.git(ws.root, "rev-parse", "HEAD") == before
    assert ws.git(ws.root, "status", "--porcelain") == ""
    assert not record.exists()

    hook.unlink()
    retried = ws.cli(command, *args, cwd=cwd)
    assert retried.returncode == 0, retried.stderr
    assert ws.git(ws.root, "rev-parse", "HEAD") != before
    assert ws.git(ws.root, "status", "--porcelain") == ""
    assert ws.git(ws.root, "-c", "core.quotepath=false", "show", "--pretty=", "--name-only") == str(
        ws.card.relative_to(ws.root)
    )
    assert record.exists() == (command == "launcher")


@pytest.mark.parametrize("command", ["launcher", "checkpoint"])
def test_task_commands_treat_wildcard_app_name_as_literal_path(workspace: TaskWorkspace, command: str) -> None:
    ws = workspace
    app_name = "sample*"
    renamed_app = ws.app.with_name(app_name)
    ws.app.rename(renamed_app)
    renamed_cards = ws.card.parents[2].with_name(app_name)
    ws.card.parents[2].rename(renamed_cards)
    ws.app = renamed_app
    ws.card = renamed_cards / "tasks/TOOLS-009/task.md"
    other = renamed_cards.with_name("sample-other") / "tasks/TOOLS-009/task.md"
    other.parent.mkdir(parents=True)
    other.write_bytes(ws.card.read_bytes())
    (ws.root / ".gitignore").write_text("/sample*/\n", encoding="utf-8")
    ws.git(ws.root, "add", "-A", ".gitignore", "studio")
    ws.git(ws.root, "commit", "-qm", "chore: wildcard app fixture")
    other.write_text(other.read_text(encoding="utf-8") + "\nUnrelated staged change.\n", encoding="utf-8")
    ws.git(ws.root, "--literal-pathspecs", "add", "--", str(other.relative_to(ws.root)))
    other_before = other.read_bytes()
    record = ws.install_agent()
    args = ("codex", app_name, "TOOLS-009") if command == "launcher" else ("TOOLS-009", "literal checkpoint")

    cwd = ws.app
    if command == "checkpoint":
        ws.git(ws.app, "worktree", "add", "-b", "agent/codex/TOOLS-009", str(ws.worktree), "main")
        cwd = ws.worktree
    result = ws.cli(command, *args, cwd=cwd)
    assert result.returncode == 0, result.stderr
    assert ws.git(ws.root, "-c", "core.quotepath=false", "show", "--pretty=", "--name-only") == str(
        ws.card.relative_to(ws.root)
    )
    assert other.read_bytes() == other_before
    assert ws.git(ws.root, "-c", "core.quotepath=false", "diff", "--cached", "--name-only") == str(
        other.relative_to(ws.root)
    )
    assert (
        ws.git(ws.root, "--literal-pathspecs", "status", "--porcelain", "--", str(ws.card.relative_to(ws.root))) == ""
    )
    assert record.exists() == (command == "launcher")


def test_task_commands_serialize_root_writes(workspace: TaskWorkspace, tmp_path: Path) -> None:
    ws = workspace
    other = ws.card.parent.parent / "TOOLS-010/task.md"
    other.parent.mkdir()
    other.write_text(ws.card.read_text().replace("TOOLS-009", "TOOLS-010"), encoding="utf-8")
    ws.git(ws.root, "add", ".")
    ws.git(ws.root, "commit", "-qm", "chore: second task")
    other_worktree = ws.app / ".claude/worktrees/TOOLS-010"
    ws.git(ws.app, "worktree", "add", "-b", "agent/codex/TOOLS-010", str(other_worktree), "main")
    entered = tmp_path / "entered"
    release = tmp_path / "release"
    hook = ws.root / ".git/hooks/pre-commit"
    hook.write_text(
        f"#!{sys.executable}\nimport pathlib, time, sys\n"
        f"pathlib.Path({str(entered)!r}).touch()\n"
        "deadline = time.monotonic() + 15\n"
        f"while not pathlib.Path({str(release)!r}).exists():\n"
        "    if time.monotonic() > deadline: sys.exit(1)\n"
        "    time.sleep(0.02)\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    first = subprocess.Popen(
        [sys.executable, "-m", "studio_tools.launcher", "codex", "sample-app", "TOOLS-009"],
        cwd=ws.app,
        env=ws.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert entered.exists(), "first command never reached the commit hook"
        second = ws.cli("checkpoint", "TOOLS-010", "concurrent write", cwd=other_worktree)
        assert second.returncode == 1
        assert "另一个任务命令" in second.stderr
    finally:
        release.touch()
        stdout, stderr = first.communicate(timeout=20)
    assert first.returncode == 0, (stdout, stderr)
    assert "concurrent write" not in other.read_text()
    assert ws.git(ws.root, "status", "--porcelain") == ""


def test_task_commands_clone_acceptance(workspace: TaskWorkspace, tmp_path: Path) -> None:
    """Keep a reviewable transcript alongside the disposable local clones."""
    source = workspace
    root = tmp_path / "cloned-root"
    app = root / "sample-app"
    source.git(tmp_path, "clone", "--no-local", str(source.root), str(root))
    source.git(tmp_path, "clone", "--no-local", str(source.app), str(app))
    studio = root / "studio"
    card = studio / source.card.relative_to(source.studio)
    ws = TaskWorkspace(root, studio, app, card, {**source.env, "STUDIO_DIR": str(studio)})
    for repo in (root, app):
        ws.git(repo, "config", "user.name", "Test User")
        ws.git(repo, "config", "user.email", "test@example.invalid")
        ws.git(repo, "config", "commit.gpgsign", "false")
    record = ws.install_agent()

    def console(command: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(Path(sys.executable).parent / command), *args],
            cwd=cwd or app,
            env=ws.env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    dry = console("studio-launch", "codex", "sample-app", "TOOLS-009", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert ws.git(root, "status", "--porcelain") == ""
    launch = console("studio-launch", "codex", "sample-app", "TOOLS-009")
    assert launch.returncode == 0, launch.stderr
    observed = ws.observed_agent(record)
    assert observed["files"] == str(card.relative_to(root))
    assert "| 状态 | doing |" in observed["card"]
    (ws.worktree / "code.py").write_text("# complete\n", encoding="utf-8")
    ws.git(ws.worktree, "add", "code.py")
    ws.git(ws.worktree, "commit", "-qm", "feat: example [TOOLS-009]")
    code_commit = ws.git(ws.worktree, "rev-parse", "--short", "HEAD")
    checkpoint = console(
        "studio-checkpoint",
        "TOOLS-009",
        "临时克隆实测：提交代码后保存检查点",
        "--test-tail",
        "example check: PASS",
        cwd=ws.worktree,
    )
    assert checkpoint.returncode == 0, checkpoint.stderr
    assert code_commit in card.read_text()
    assert "工作区：干净" in card.read_text()
    assert "example check: PASS" in card.read_text()
    assert ws.git(root, "-c", "core.quotepath=false", "show", "--pretty=", "--name-only") == str(card.relative_to(root))
    assert ws.git(root, "status", "--porcelain") == ""
    transcript = {
        "scope": "Local temporary clones with a stub agent; no live agent or real ROOT writes.",
        "root": str(root),
        "worktree": str(ws.worktree),
        "source_commit": code_commit,
        "commands": [
            {"argv": r.args, "returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
            for r in (dry, launch, checkpoint)
        ],
        "agent_at_start": observed,
        "root_log": ws.git(root, "-c", "core.quotepath=false", "log", "-2", "--format=%h %s", "--name-only"),
        "card": card.read_text(),
    }
    (tmp_path / "acceptance.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
