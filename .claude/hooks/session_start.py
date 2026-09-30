#!/usr/bin/env python3
"""SessionStart hook: print branch, ``git status -sb`` and the studio task card.

Stdout is added to Claude's context. Never blocks.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TASK_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9]*-[0-9]{3,}")
STATUS_LINE_LIMIT = 20


def git(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.rstrip("\n") if result.returncode == 0 else ""


def main_repo_root(cwd: Path) -> Path | None:
    """Locate the primary worktree via the shared git dir (works inside linked worktrees)."""

    common_dir = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    return Path(common_dir).parent if common_dir else None


def checkpoint_section(task_card: Path) -> str:
    lines = task_card.read_text(encoding="utf-8").splitlines()
    collected: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip() == "## 当前检查点"
        if inside:
            collected.append(line)
    return "\n".join(collected).strip()


def build_report(cwd: Path) -> str:
    branch = (
        git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
        or git(["rev-parse", "--short", "HEAD"], cwd)
        or "（无法读取分支）"
    )
    status = git(["status", "-sb"], cwd).splitlines()
    out = [f"[studio-tools] 当前分支：{branch}", "git status -sb："]
    out.extend(f"  {line}" for line in status[:STATUS_LINE_LIMIT])
    if len(status) > STATUS_LINE_LIMIT:
        out.append(f"  ……另有 {len(status) - STATUS_LINE_LIMIT} 行")

    match = TASK_ID_PATTERN.search(branch)
    if match is None:
        out.append("分支名不含任务编号；按 AGENTS.md，开工前应切到 agent/<agent>/<任务ID> 分支。")
        return "\n".join(out)

    task_id = match.group(0)
    root = main_repo_root(cwd)
    if root is None:
        out.append(f"任务 {task_id}：无法定位主仓库，找不到任务卡。")
        return "\n".join(out)
    studio = Path(os.environ.get("STUDIO_DIR", str(root.parent / "studio"))).absolute()
    task_card = studio / "项目/应用" / root.name / "tasks" / task_id / "task.md"
    if task_card.resolve() != task_card:
        out.append("任务卡路径包含符号链接，拒绝读取。")
        return "\n".join(out)
    if not task_card.is_file():
        out.append(f"任务 {task_id}：未找到任务卡 {task_card}，请先在 studio 登记任务卡或确认任务编号。")
        return "\n".join(out)
    out.append(f"任务卡：{task_card}")
    section = checkpoint_section(task_card)
    out.append(section if section else "（任务卡中没有“## 当前检查点”一节）")
    return "\n".join(out)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    cwd = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    print(build_report(cwd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
