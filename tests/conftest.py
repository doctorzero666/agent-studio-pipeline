"""Isolated repositories and CLI subprocesses for the task commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_outer_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Git hooks export repository selectors; fixtures must create their own repos.

    Tests may still inject GIT_* variables explicitly after this isolation.
    """
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)


@dataclass
class TaskWorkspace:
    root: Path
    studio: Path
    app: Path
    card: Path
    env: dict[str, str] = field(repr=False)

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(cwd), *args], env=self.env, text=True, capture_output=True, check=True
        ).stdout.strip()

    def cli(self, module: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", f"studio_tools.{module}", *args],
            cwd=cwd or self.app,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    @property
    def worktree(self) -> Path:
        return self.app / ".claude/worktrees/TOOLS-009"

    def install_agent(self, agent: str = "codex", exit_code: int = 0) -> Path:
        """A real executable observes the card and ROOT commit at agent startup."""
        bin_dir = self.root.parent / "bin"
        bin_dir.mkdir(exist_ok=True)
        record = self.root.parent / f"{agent}-called.json"
        script = bin_dir / agent
        script.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, subprocess, sys\n"
            f"card = pathlib.Path({str(self.card)!r})\n"
            f"root = {str(self.root)!r}\n"
            "def git(*args):\n"
            "    return subprocess.check_output(['git', '-C', root, *args], text=True).strip()\n"
            "data = dict(argv=sys.argv[1:], cwd=os.getcwd(), card=card.read_text(), "
            "files=git('-c', 'core.quotepath=false', 'show', '--pretty=', '--name-only', 'HEAD'))\n"
            f"pathlib.Path({str(record)!r}).write_text(json.dumps(data))\n"
            f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.env["PATH"] = str(bin_dir) + os.pathsep + self.env["PATH"]
        return record

    def observed_agent(self, record: Path) -> dict:
        return json.loads(record.read_text(encoding="utf-8"))


@pytest.fixture
def workspace(tmp_path: Path) -> TaskWorkspace:
    root = tmp_path / "工作 空间"
    studio = root / "studio"
    app = root / "sample-app"
    card = studio / "项目/应用/sample-app/tasks/TOOLS-009/task.md"
    card.parent.mkdir(parents=True)
    app.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        STUDIO_DIR=str(studio),
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
    )
    ws = TaskWorkspace(root, studio, app, card, env)
    for repo in (root, app):
        ws.git(repo, "init", "-q", "-b", "main")
        ws.git(repo, "config", "user.name", "Test User")
        ws.git(repo, "config", "user.email", "test@example.invalid")
        ws.git(repo, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text("/sample-app/\n", encoding="utf-8")
    (app / ".gitignore").write_text(".claude/worktrees/\n", encoding="utf-8")
    card.write_text(
        "# TOOLS-009\n\n| 字段 | 值 |\n|---|---|\n| 任务编号 | `TOOLS-009` |\n"
        "| 状态 | todo |\n| 当前执行者 | 无 |\n| 最后更新时间 | 2026-01-01 |\n\n"
        "## 当前检查点\n\n已有检查点。\n\n## 对外操作与授权\n\n无。\n",
        encoding="utf-8",
    )
    for repo in (root, app):
        ws.git(repo, "add", ".")
        ws.git(repo, "commit", "-qm", "chore: fixture")
    # Never fall through to a real installed agent, even when the launcher is buggy.
    for agent in ("codex", "claude", "hermes"):
        ws.install_agent(agent)
    return ws
