"""Feed hook scripts JSON on stdin, exactly as Claude Code does, and check exit codes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
SETTINGS = REPO / ".claude" / "settings.json"


def run_hook(name: str, payload: dict, env: dict[str, str] | None = None, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        cwd=cwd,
        timeout=60,
        check=False,
    )


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def feature_repo(tmp_path: Path) -> Path:
    """A throwaway repo on a non-protected branch, so bare pushes are judged by refspec only."""

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "agent/claude/TOOLS-001")
    return repo


def bash_payload(command: str, cwd: Path) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }


BLOCKED = [
    "git push origin main",
    "git push -u origin main",
    "git push origin HEAD:main",
    "git push origin +main",
    "git push origin feature:refs/heads/master",
    "git -C . push origin main",
    "git -c push.default=current push origin master",
    "GIT_TRACE=1 git push origin main",
    "echo hi && git push origin main",
    "bash -c 'git push origin main'",
    "bash -lc 'git push origin main'",
    'zsh -ic "gh pr merge 1"',
    "bash -l -c 'git push origin HEAD:master'",
    "git push --all origin",
    "gh pr merge 1",
    "gh pr merge --squash 12",
    "gh -R me/repo pr merge 3",
    "git commit --no-verify -m 'feat: x'",
    "git push --no-verify origin agent/claude/TOOLS-001",
    "git commit -nm 'feat: x'",
]

ALLOWED = [
    "git status",
    "git push origin agent/claude/TOOLS-001",
    "git push -u origin agent/codex/TOOLS-002",
    "git log main",
    "git diff main...HEAD",
    "gh pr create --title 'feat: x'",
    "gh pr view 1",
    "git commit -m 'feat: x'",
    "just check",
    "bash -lc 'git status'",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_guard_blocks(command: str, feature_repo: Path) -> None:
    result = run_hook("guard_bash.py", bash_payload(command, feature_repo))
    assert result.returncode == 2, result
    assert "[studio-tools guard]" in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_guard_allows(command: str, feature_repo: Path) -> None:
    result = run_hook("guard_bash.py", bash_payload(command, feature_repo))
    assert result.returncode == 0, result
    assert result.stdout == ""


def test_guard_blocks_bare_push_on_main(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    assert run_hook("guard_bash.py", bash_payload("git push", repo)).returncode == 2
    assert run_hook("guard_bash.py", bash_payload("git push origin HEAD", repo)).returncode == 2


def test_guard_ignores_other_tools(feature_repo: Path) -> None:
    payload = {"tool_name": "Read", "tool_input": {"file_path": "x"}, "cwd": str(feature_repo)}
    assert run_hook("guard_bash.py", payload).returncode == 0


def test_stop_blocks_when_check_fails(tmp_path: Path) -> None:
    result = run_hook(
        "stop_check.py",
        {"hook_event_name": "Stop", "stop_hook_active": False, "cwd": str(tmp_path)},
        env={"STUDIO_TOOLS_STOP_CMD": "false", "CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "收工前检查失败" in result.stderr


def test_stop_allows_when_check_passes(tmp_path: Path) -> None:
    result = run_hook(
        "stop_check.py",
        {"hook_event_name": "Stop", "stop_hook_active": False},
        env={"STUDIO_TOOLS_STOP_CMD": "true", "CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert result.returncode == 0


def test_stop_allows_when_stop_hook_active(tmp_path: Path) -> None:
    result = run_hook(
        "stop_check.py",
        {"hook_event_name": "Stop", "stop_hook_active": True},
        env={"STUDIO_TOOLS_STOP_CMD": "false", "CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert result.returncode == 0


def test_session_start_prints_task_card(tmp_path: Path) -> None:
    tools = tmp_path / "studio-tools"
    tools.mkdir()
    git(tools, "init", "-q", "-b", "agent/claude/TOOLS-001")
    card = tmp_path / "studio" / "项目" / "应用" / "studio-tools" / "tasks" / "TOOLS-001" / "task.md"
    card.parent.mkdir(parents=True)
    card.write_text("# T\n\n## 当前检查点\n\n- CP-001：写测试\n\n## 对外操作与授权\n\n无\n", encoding="utf-8")

    result = run_hook("session_start.py", {"hook_event_name": "SessionStart", "cwd": str(tools)})

    assert result.returncode == 0
    assert "当前分支：agent/claude/TOOLS-001" in result.stdout
    assert str(card.resolve()) in result.stdout
    assert "CP-001：写测试" in result.stdout
    assert "对外操作与授权" not in result.stdout


def test_session_start_reports_missing_card(tmp_path: Path) -> None:
    tools = tmp_path / "studio-tools"
    tools.mkdir()
    git(tools, "init", "-q", "-b", "agent/codex/TOOLS-009")

    result = run_hook("session_start.py", {"hook_event_name": "SessionStart", "cwd": str(tools)})

    assert result.returncode == 0
    assert "未找到任务卡" in result.stdout


def test_format_hook_formats_python(tmp_path: Path) -> None:
    source = tmp_path / "ugly.py"
    source.write_text("x=[1,2 ,3]\n", encoding="utf-8")
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(source)}}

    result = run_hook("format_python.py", payload, env={"CLAUDE_PROJECT_DIR": str(REPO)})

    assert result.returncode == 0
    assert source.read_text(encoding="utf-8") == "x = [1, 2, 3]\n"


def test_settings_wire_every_hook() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    hooks = settings["hooks"]
    assert set(hooks) == {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}
    for groups in hooks.values():
        for group in groups:
            for hook in group["hooks"]:
                script = hook["command"].split("/.claude/hooks/")[1].rstrip('"')
                assert (HOOKS / script).is_file(), script
    deny = settings["permissions"]["deny"]
    assert "Bash(git push * main)" in deny
    assert any(rule.startswith("Read(") and ".env" in rule for rule in deny)
