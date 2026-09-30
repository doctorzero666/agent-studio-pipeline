"""Launcher contract tests; all Git mutations stay below tmp_path."""

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from conftest import TaskWorkspace


def test_launcher_dry_run_is_read_only(workspace: TaskWorkspace) -> None:
    ws = workspace
    before = ws.git(ws.root, "rev-parse", "HEAD")
    result = ws.cli("launcher", "codex", "sample-app", "TOOLS-009", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert str(ws.worktree) in result.stdout
    assert "agent/codex/TOOLS-009" in result.stdout
    assert "dry-run" in result.stdout
    assert not ws.worktree.exists()
    assert ws.git(ws.root, "rev-parse", "HEAD") == before
    assert ws.git(ws.root, "status", "--porcelain") == ""
    assert ws.git(ws.app, "status", "--porcelain") == ""
    assert not (ws.root / ".git/studio-task.lock").exists()


def test_launcher_commits_claim_before_agent_without_other_staged_files(workspace: TaskWorkspace) -> None:
    ws = workspace
    record = ws.install_agent()
    unrelated = ws.root / "unrelated.txt"
    unrelated.write_text("keep staged", encoding="utf-8")
    ws.git(ws.root, "add", "unrelated.txt")
    result = ws.cli("launcher", "codex", "sample-app", "TOOLS-009", "--", "exec", "a b; $(false)")
    assert result.returncode == 0, result.stderr
    observed = ws.observed_agent(record)
    assert observed["files"] == str(ws.card.relative_to(ws.root))
    assert "| 状态 | doing |" in observed["card"]
    assert "| 当前执行者 | Codex" in observed["card"]
    timestamp = re.search(r"\| 最后更新时间 \| (.*?) \|", observed["card"])[1]
    assert datetime.fromisoformat(timestamp).utcoffset() is not None
    assert observed["argv"] == ["--cd", str(ws.worktree), "--sandbox", "workspace-write", "exec", "a b; $(false)"]
    assert ws.git(ws.worktree, "branch", "--show-current") == "agent/codex/TOOLS-009"
    assert ws.git(ws.root, "diff", "--cached", "--name-only") == "unrelated.txt"


def test_launcher_takeover_preserves_previous_executor(workspace: TaskWorkspace) -> None:
    ws = workspace
    ws.card.write_text(ws.card.read_text().replace("| 无 |", "| Alice（原执行者） |"), encoding="utf-8")
    ws.git(ws.root, "commit", "-am", "chore: existing claim")
    record = ws.install_agent()
    result = ws.cli("launcher", "codex", "--takeover", "sample-app", "TOOLS-009")
    assert result.returncode == 0, result.stderr
    content = ws.observed_agent(record)["card"]
    checkpoint = content.split("## 当前检查点", 1)[1].split("## 对外操作与授权", 1)[0]
    assert "Alice（原执行者）" in checkpoint
    assert "Codex" in checkpoint
    assert "已有检查点。" in checkpoint


@pytest.mark.parametrize(
    ("args", "executor"),
    [
        (["sample-app", "TOOLS-009", "--dry-run"], "无"),
        (["--dry-run", "sample-app", "TOOLS-009"], "无（已释放）"),
        (["sample-app", "--dry-run", "TOOLS-009", "--takeover"], "Alice"),
        (["--dry-run", "sample-app", "TOOLS-009"], "Alice"),
        (["--dry-run", "sample-app", "TOOLS-009"], "无人认领"),
        (["--dry-run", "sample-app", "TOOLS-009"], "无; 已释放"),
        (["--dry-run", "sample-app", "TOOLS-009", "--", "--takeover"], "Alice"),
        (["--dry-run", "sample-app", "TOOLS-009", "--", "--dry-run=bad"], "无"),
        (["sample-app", "TOOLS-009", "--dry-run=bad"], "无"),
        (["--dry-run", "sample-app", "tools-009"], "无"),
        (["--dry-run", "sample-app", "TOOLS-09"], "无"),
        (["--dry-run", "sample-app", "TOOLS-009/../../bad"], "无"),
        (["--dry-run", "sample-app", "A1-0009"], "无"),
        (["--dry-run", "../sample-app", "TOOLS-009"], "无"),
        (["--dry-run", "sample-app"], "无"),
        (["--unknown", "sample-app", "TOOLS-009"], "无"),
        (["--help"], "无"),
    ],
)
def test_launcher_matches_frozen_app_lib(workspace: TaskWorkspace, args: list[str], executor: str) -> None:
    """The fixture is the unmodified studio/bin/app-lib.sh read on 2026-09-30."""
    ws = workspace
    ws.card.write_text(ws.card.read_text().replace("| 无 |", f"| {executor} |"), encoding="utf-8")
    if "A1-0009" in args:
        alternative = ws.card.parent.parent / "A1-0009/task.md"
        alternative.parent.mkdir()
        alternative.write_text(ws.card.read_text().replace("TOOLS-009", "A1-0009"), encoding="utf-8")
    bin_dir = ws.studio / "bin"
    bin_dir.mkdir()
    script = bin_dir / "app-codex"
    reference = Path(__file__).parent / "fixtures/app-lib.sh"
    script.write_text(
        'AGENT=codex\n. "$REFERENCE"\nn=$#\ni=0\n'
        'while [ "$i" -lt "$n" ]; do\n a=$1; shift; i=$((i+1)); app_take_arg "$a"\n'
        ' if [ "$KEEP" -eq 1 ]; then set -- "$@" "$a"; fi\ndone\napp_prepare\n',
        encoding="utf-8",
    )
    ws.git(ws.root, "add", ".")
    ws.git(ws.root, "commit", "-qm", "chore: parity inputs")
    legacy = subprocess.run(
        ["sh", str(script), *args],
        env={**ws.env, "REFERENCE": str(reference)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    current = ws.cli("launcher", "codex", *args)
    assert current.returncode == legacy.returncode, (current.stderr, legacy.stderr)
    if legacy.returncode == 0:
        for value in (str(ws.app), "agent/codex/", "dry-run"):
            assert value in current.stdout and value in legacy.stdout
    assert not ws.worktree.exists()
    assert ws.git(ws.root, "status", "--porcelain") == ""


@pytest.mark.parametrize("agent", ["codex", "claude", "hermes"])
def test_launcher_preserves_agent_command_and_exit_code(workspace: TaskWorkspace, agent: str) -> None:
    ws = workspace
    record = ws.install_agent(agent, exit_code=17)
    result = ws.cli("launcher", agent, "sample-app", "TOOLS-009", "--", "--dry-run", "two words", "")
    assert result.returncode == 17, result.stderr
    observed = ws.observed_agent(record)
    prefixes = {
        "codex": ["--cd", str(ws.worktree), "--sandbox", "workspace-write"],
        "claude": ["--name", "sample-app TOOLS-009"],
        "hermes": ["--in", str(ws.worktree), "--tui"],
    }
    assert observed["argv"] == prefixes[agent] + ["--dry-run", "two words", ""]
    if agent == "claude":
        assert observed["cwd"] == str(ws.worktree)
    assert ws.git(ws.worktree, "branch", "--show-current") == f"agent/{agent}/TOOLS-009"


@pytest.mark.parametrize(
    "failure",
    [
        "commit_hook",
        "dirty_card",
        "staged_card",
        "missing_executor",
        "duplicate_executor",
        "missing_status",
        "missing_time",
        "wrong_id",
        "card_symlink",
        "app_symlink",
        "worktree_symlink",
        "fake_worktree",
        "missing_main",
        "occupied",
        "untracked_card",
        "merge_in_progress",
    ],
)
def test_launcher_failure_never_starts_agent(workspace: TaskWorkspace, failure: str) -> None:
    ws = workspace
    record = ws.install_agent()
    if failure == "commit_hook":
        hook = ws.root / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
    elif failure in {"dirty_card", "staged_card"}:
        ws.card.write_text(ws.card.read_text() + "uncommitted\n", encoding="utf-8")
        if failure == "staged_card":
            ws.git(ws.root, "add", ".")
    elif failure in {
        "missing_executor",
        "duplicate_executor",
        "missing_status",
        "missing_time",
        "wrong_id",
        "occupied",
    }:
        content = ws.card.read_text()
        substitutions = {
            "missing_executor": ("| 当前执行者 | 无 |", ""),
            "duplicate_executor": ("| 当前执行者 | 无 |", "| 当前执行者 | 无 |\n| 当前执行者 | 无 |"),
            "missing_status": ("| 状态 | todo |", ""),
            "missing_time": ("| 最后更新时间 | 2026-01-01 |", ""),
            "wrong_id": ("`TOOLS-009`", "`TOOLS-010`"),
            "occupied": ("| 当前执行者 | 无 |", "| 当前执行者 | Alice |"),
        }
        ws.card.write_text(content.replace(*substitutions[failure]), encoding="utf-8")
        ws.git(ws.root, "commit", "-am", "chore: invalid card")
    elif failure == "card_symlink":
        outside = ws.root.parent / "outside.md"
        outside.write_bytes(ws.card.read_bytes())
        ws.card.unlink()
        ws.card.symlink_to(outside)
        ws.git(ws.root, "commit", "-am", "chore: linked card")
    elif failure == "app_symlink":
        moved = ws.root.parent / "moved-app"
        ws.app.rename(moved)
        ws.app.symlink_to(moved, target_is_directory=True)
    elif failure == "worktree_symlink":
        ws.worktree.parent.mkdir(parents=True)
        ws.worktree.symlink_to(ws.app, target_is_directory=True)
    elif failure == "fake_worktree":
        ws.worktree.mkdir(parents=True)
    elif failure == "missing_main":
        ws.git(ws.app, "branch", "-m", "not-main")
    elif failure == "untracked_card":
        ws.git(ws.root, "rm", "--cached", str(ws.card))
        ws.git(ws.root, "commit", "-m", "chore: untrack card")
    elif failure == "merge_in_progress":
        (ws.root / ".git/MERGE_HEAD").write_text(ws.git(ws.root, "rev-parse", "HEAD") + "\n", encoding="utf-8")
    before = ws.git(ws.root, "rev-parse", "HEAD")
    card_before = ws.card.read_bytes()
    result = ws.cli("launcher", "codex", "sample-app", "TOOLS-009")
    assert result.returncode == (3 if failure == "occupied" else 1), result.stderr
    assert not record.exists()
    assert ws.git(ws.root, "rev-parse", "HEAD") == before
    assert ws.card.read_bytes() == card_before
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("existing", ["branch", "worktree", "different_branch", "not_ignored"])
def test_launcher_reuses_worktrees_and_reports_warnings(workspace: TaskWorkspace, existing: str) -> None:
    ws = workspace
    branch = "agent/codex/TOOLS-009"
    if existing == "branch":
        ws.git(ws.app, "branch", branch)
        ws.git(ws.app, "branch", "-m", "not-main")
    elif existing in {"worktree", "different_branch", "detached"}:
        if existing == "different_branch":
            branch = "agent/claude/TOOLS-009"
        ws.git(ws.app, "worktree", "add", "-b", branch, str(ws.worktree), "main")
        if existing == "detached":
            ws.git(ws.worktree, "checkout", "--detach")
    else:
        (ws.app / ".gitignore").write_text("", encoding="utf-8")
        ws.git(ws.app, "commit", "-am", "chore: remove ignore")
    record = ws.install_agent()
    result = ws.cli("launcher", "codex", "sample-app", "TOOLS-009")
    assert result.returncode == 0, result.stderr
    assert record.exists()
    if existing in {"different_branch", "detached", "not_ignored"}:
        assert "警告" in result.stderr
    if existing != "detached":
        assert ws.git(ws.worktree, "branch", "--show-current") == branch


def test_launcher_command_entries_are_declared() -> None:
    import tomllib

    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as stream:
        scripts = tomllib.load(stream)["project"]["scripts"]
    assert scripts["studio-launch"] == "studio_tools.launcher:main"
    assert scripts["studio-checkpoint"] == "studio_tools.checkpoint:main"


def test_launcher_missing_agent_does_not_claim_or_create_worktree(workspace: TaskWorkspace) -> None:
    ws = workspace
    bin_dir = Path(ws.env["PATH"].split(os.pathsep)[0])
    (bin_dir / "codex").unlink()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    ws.env["PATH"] = str(bin_dir)
    before = ws.git(ws.root, "rev-parse", "HEAD")
    result = ws.cli("launcher", "codex", "sample-app", "TOOLS-009")
    assert result.returncode == 1
    assert "找不到 agent 命令" in result.stderr
    assert not ws.worktree.exists()
    assert ws.git(ws.root, "rev-parse", "HEAD") == before
    assert ws.git(ws.root, "status", "--porcelain") == ""
