"""Create portable Studio workspaces without touching existing projects or user configuration."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from importlib.resources import files
from pathlib import Path

from studio_tools.check_studio import REQUIRED_PATHS
from studio_tools.task_files import TaskError, git, root_lock, safe_path, timestamp, validate_id


def name(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
        raise TaskError("Application names must use lowercase letters, digits and hyphens (1–64 characters).", 2)
    return value


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def require_identity(directory: Path) -> None:
    if git(directory, "var", "GIT_AUTHOR_IDENT", check=False).returncode:
        raise TaskError("Configure your Git user.name and user.email before initialization.")


def initialize(destination: Path) -> Path:
    target = destination.absolute()
    safe_path(target.parent.resolve(), target)
    if target.exists():
        raise TaskError("Destination already exists; choose a new directory. Nothing was overwritten.")
    require_identity(target.parent)
    target.mkdir()
    studio = target / "studio"
    for relative in REQUIRED_PATHS:
        if relative.startswith("bin/"):
            agent = relative.removeprefix("bin/studio-")
            content = f'#!/bin/sh\nset -eu\ncd "$(dirname "$0")/.."\nexec {agent} "$@"\n'
        else:
            content = f"# {Path(relative).stem}\n\nThis file belongs to your private workspace.\n"
        write(studio / relative, content)
        if relative.startswith("bin/"):
            (studio / relative).chmod(0o755)
    (studio / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (studio / "AGENTS.md").write_text(
        "# Studio rules\n\nRead the task card before writing. One writer per task.\n"
        "Use isolated worktrees; checkpoint actual files, validation and the next action.\n"
        "Review must be performed by a non-author. Do not publish, merge or spend without authorization.\n"
        "Never store credentials or customer data in public repositories.\n",
        encoding="utf-8",
    )
    (studio / "STATUS.md").write_text("# Status\n\n## 当前重点\n\nNo active task.\n", encoding="utf-8")
    (studio / "registry/任务队列.md").write_text(
        "# Tasks\n\n| 任务编号 | 项目 | 任务卡 |\n|---|---|---|\n", encoding="utf-8"
    )
    write(target / ".gitignore", "/*/\n!/studio/\n.DS_Store\n.env*\n")
    write(target / "README.md", "# Private Studio workspace\n\nApplication repositories are independent siblings.\n")
    git(target, "init", "-b", "main")
    git(target, "add", "README.md", ".gitignore", "studio")
    git(target, "commit", "-m", "chore: initialize private studio")
    return studio


def studio_root(value: str | None) -> Path:
    root = Path(value or os.environ.get("STUDIO_DIR", "../studio")).absolute()
    if root.resolve() != root or not (root / "AGENTS.md").is_file():
        raise TaskError("Set --studio or STUDIO_DIR to an initialized Studio directory (no symlinks).")
    return root


def add_app(studio: Path, app_name: str) -> Path:
    app = safe_path(studio.parent, studio.parent / name(app_name))
    if app.exists():
        raise TaskError("Application directory already exists; no files were overwritten.")
    require_identity(studio.parent)
    template = files("studio_tools").joinpath("templates/application")
    shutil.copytree(str(template), app)
    if not (app / ".claude/hooks/guard_bash.py").exists():
        # Editable source checkout: wheels include these exact files via force-include.
        source_hooks = Path(__file__).resolve().parents[2] / ".claude"
        if not (source_hooks / "hooks/guard_bash.py").is_file():
            raise TaskError("Installation lacks hook assets; reinstall from a release wheel.")
        shutil.copytree(source_hooks / "hooks", app / ".claude/hooks", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(source_hooks / "settings.json", app / ".claude/settings.json")
    git(app, "init", "-b", "main")
    git(app, "add", ".")
    git(app, "commit", "-m", "chore: initialize application")
    return app


def add_task(studio: Path, app_name: str, task_id: str, goal: str) -> Path:
    with root_lock(studio.parent):
        return _add_task_locked(studio, app_name, task_id, goal)


def _add_task_locked(studio: Path, app_name: str, task_id: str, goal: str) -> Path:
    name(app_name)
    validate_id(task_id)
    if not goal.strip() or len(goal) > 1000 or any(ord(c) < 32 for c in goal) or "|" in goal:
        raise TaskError("Goal must be a nonempty single line, at most 1000 characters, without pipes.", 2)
    app = safe_path(studio.parent, studio.parent / app_name)
    if git(app, "rev-parse", "--show-toplevel").stdout.strip() != str(app):
        raise TaskError("Application must be an independent repository.")
    root = studio.parent
    if git(root, "status", "--porcelain").stdout:
        raise TaskError("Commit or reconcile your workspace changes before adding a task.")
    card = safe_path(studio, studio / "项目/应用" / app_name / "tasks" / task_id / "task.md")
    if card.exists():
        raise TaskError("Task already exists; nothing was overwritten.")
    fields = {
        "任务编号": f"`{task_id}`",
        "项目编号": app_name,
        "目标": goal,
        "状态": "todo",
        "负责人": "Workspace owner",
        "当前执行者": "无",
        "最后更新时间": timestamp(),
        "时间与费用边界": "No additional paid API calls authorized",
        "代码仓库": f"`{app_name}`",
        "issue": "无（local）",
        "分支 / worktree": f"`.claude/worktrees/{task_id}`",
        "PR": "无（local）",
        "CI 结果": "未运行",
        "评审者": "Non-author required",
    }
    content = f"# {task_id}\n\n| 字段 | 值 |\n|---|---|\n"
    content += "".join(f"| {key} | {value} |\n" for key, value in fields.items())
    content += (
        "\n## 目标与验收\n\n- [ ] Define and verify the acceptance criteria before implementation.\n"
        "\n## 阅读入口\n\nRead the application AGENTS.md.\n"
        "\n## 当前检查点\n\nNot started. Next: define acceptance, then claim the task.\n"
        "\n## 对外操作与授权\n\nLocal work only. Publishing, spending and production changes need authorization.\n"
    )
    queue = safe_path(studio, studio / "registry/任务队列.md")
    focus = safe_path(studio, studio / "STATUS.md")
    relative = card.relative_to(studio).as_posix()
    originals = {card: None, queue: queue.read_bytes(), focus: focus.read_bytes()}
    updates = {
        card: content.encode(),
        queue: originals[queue] + f"| `{task_id}` | {app_name} | [task](../{relative}) |\n".encode(),
        focus: f"# Status\n\n## 当前重点\n\n`{task_id}`: [task]({relative})\n".encode(),
    }
    before = git(root, "rev-parse", "HEAD").stdout.strip()
    paths = [f":(literal){path.relative_to(root)}" for path in updates]
    written = []
    try:
        card.parent.mkdir(parents=True, exist_ok=True)
        for path, value in updates.items():
            path.write_bytes(value)
            written.append(path)
        git(root, "add", "--", *paths)
        git(root, "commit", "--only", "-m", f"chore: add task [{task_id}]", "--", *paths)
    except (TaskError, OSError):
        unchanged = git(root, "rev-parse", "HEAD").stdout.strip() == before
        unchanged = unchanged and all(path.read_bytes() == updates[path] for path in written)
        if unchanged:
            git(root, "restore", "--staged", "--source=HEAD", "--", *paths, check=False)
            for path in written:
                if originals[path] is None:
                    path.unlink()
                else:
                    path.write_bytes(originals[path])
        raise TaskError(
            "Task creation failed. If no external edits intervened, files were restored; "
            "check git status and commit hooks before retrying."
        ) from None
    return card


def status(studio: Path) -> list[dict[str, str]]:
    from studio_tools.task_files import field

    return [
        {
            "task": field(card.read_text(), "任务编号").strip("`"),
            "status": field(card.read_text(), "状态"),
            "executor": field(card.read_text(), "当前执行者"),
        }
        for card in sorted((studio / "项目/应用").glob("*/tasks/*/task.md"))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a new private workspace")
    init.add_argument("destination", type=Path)
    for command in ("app", "task", "status", "doctor"):
        child = commands.add_parser(command)
        child.add_argument("--studio")
        if command in {"app", "task"}:
            child.add_argument("app")
        if command == "task":
            child.add_argument("task_id")
            child.add_argument("--goal", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(initialize(args.destination))
            return 0
        studio = studio_root(args.studio)
        if args.command == "app":
            print(add_app(studio, args.app))
        elif args.command == "task":
            print(add_task(studio, args.app, args.task_id, args.goal))
        elif args.command == "status":
            print(json.dumps(status(studio), ensure_ascii=False, indent=2))
        else:
            tools = {tool: bool(shutil.which(tool)) for tool in ("git", "uv", "just", "codex", "claude", "hermes")}
            print(
                json.dumps(
                    {
                        "platform": sys.platform,
                        "tools": tools,
                        "scope": "availability only; no credentials, quota or hook-trust verification",
                    },
                    indent=2,
                )
            )
            return 0 if all(tools[t] for t in ("git", "uv", "just")) else 1
        return 0
    except (TaskError, OSError, UnicodeError) as exc:
        print(f"studio: {exc}", file=sys.stderr)
        return exc.code if isinstance(exc, TaskError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
