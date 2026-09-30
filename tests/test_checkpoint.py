"""Checkpoint CLI behavior in temporary Git repositories (tmp_path fixture)."""

import re
from datetime import datetime

import pytest
from conftest import TaskWorkspace


@pytest.mark.parametrize("dirty", [False, True])
def test_checkpoint_records_real_worktree_state_and_only_commits_card(workspace: TaskWorkspace, dirty: bool) -> None:
    ws = workspace
    ws.git(ws.app, "worktree", "add", "-b", "agent/codex/TOOLS-009", str(ws.worktree), "main")
    source_commit = ws.git(ws.worktree, "rev-parse", "--short", "HEAD")
    if dirty:
        (ws.worktree / "untracked.py").write_text("# pending\n", encoding="utf-8")
    (ws.root / "unrelated.txt").write_text("staged", encoding="utf-8")
    ws.git(ws.root, "add", "unrelated.txt")
    before = datetime.now().astimezone().replace(microsecond=0)
    result = ws.cli(
        "checkpoint", "TOOLS-009", "已完成；下一步评审", "--test-tail", "189 passed in 1.00s", cwd=ws.worktree
    )
    after = datetime.now().astimezone()
    assert result.returncode == 0, result.stderr
    content = ws.card.read_text()
    section = content.split("## 当前检查点", 1)[1].split("## 对外操作与授权", 1)[0]
    assert "已有检查点。" in section
    assert "已完成；下一步评审" in section
    assert "agent/codex/TOOLS-009" in section
    assert source_commit in section
    assert ("工作区：不干净" if dirty else "工作区：干净") in section
    assert "189 passed in 1.00s" in section
    times = re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", section)
    assert times and all(before <= datetime.fromisoformat(value) <= after for value in times)
    files = ws.git(ws.root, "-c", "core.quotepath=false", "show", "--pretty=", "--name-only", "HEAD")
    assert files == str(ws.card.relative_to(ws.root))
    assert ws.git(ws.root, "diff", "--cached", "--name-only") == "unrelated.txt"
    assert ws.git(ws.worktree, "rev-parse", "--short", "HEAD") == source_commit
    assert "| 状态 | todo |" in content
    assert "| 当前执行者 | 无 |" in content


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ([], 2),
        (["TOOLS-009"], 2),
        (["../TOOLS-009", "text"], 2),
        (["TOOLS-009", ""], 2),
        (["TOOLS-009", "  "], 2),
        (["TOOLS-009", "x" * 20001], 2),
        (["TOOLS-009", "x\x1b"], 2),
        (["TOOLS-009", "ok", "--test-tail", "a\nb"], 2),
    ],
)
def test_checkpoint_rejects_invalid_input_without_changes(workspace: TaskWorkspace, args: list[str], code: int) -> None:
    ws = workspace
    before = ws.git(ws.root, "rev-parse", "HEAD")
    result = ws.cli("checkpoint", *args)
    assert result.returncode == code, result.stderr
    assert ws.git(ws.root, "rev-parse", "HEAD") == before
    assert ws.git(ws.root, "status", "--porcelain") == ""


@pytest.mark.parametrize("failure", ["hook", "dirty", "missing_section", "duplicate_section"])
def test_checkpoint_failure_preserves_card(workspace: TaskWorkspace, failure: str) -> None:
    ws = workspace
    if failure == "hook":
        hook = ws.root / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
    elif failure == "dirty":
        ws.card.write_text(ws.card.read_text() + "pending\n", encoding="utf-8")
    else:
        heading = "" if failure == "missing_section" else "## 当前检查点\n\n## 当前检查点"
        ws.card.write_text(ws.card.read_text().replace("## 当前检查点", heading), encoding="utf-8")
        ws.git(ws.root, "commit", "-am", "chore: invalid section")
    ws.git(ws.app, "worktree", "add", "-b", "agent/codex/TOOLS-009", str(ws.worktree), "main")
    original = ws.card.read_bytes()
    before = ws.git(ws.root, "rev-parse", "HEAD")
    result = ws.cli("checkpoint", "TOOLS-009", "should fail", cwd=ws.worktree)
    assert result.returncode == 1
    assert ws.card.read_bytes() == original
    assert ws.git(ws.root, "rev-parse", "HEAD") == before


def test_checkpoint_appends_again_and_infers_studio_without_environment(workspace: TaskWorkspace) -> None:
    ws = workspace
    ws.env.pop("STUDIO_DIR")
    ws.git(ws.app, "worktree", "add", "-b", "agent/codex/TOOLS-009", str(ws.worktree), "main")
    for description in ("first", "second\n## 对外操作与授权\nthird"):
        result = ws.cli("checkpoint", "TOOLS-009", description, cwd=ws.worktree)
        assert result.returncode == 0, result.stderr
    content = ws.card.read_text()
    assert content.count("### 检查点 · ") == 2
    assert "first" in content and "second" in content
    assert content.count("\n## 对外操作与授权\n") == 1
