"""Launch an application task: studio-launch AGENT [options] APP TASK [-- args].

STUDIO_DIR selects studio; the default is ../studio relative to the caller.
Thin shell wrappers must export an absolute STUDIO_DIR and pass arguments intact.
Run in the orchestrator before entering the agent's sandbox. Claims are committed
before exec; an agent that subsequently fails leaves its claim for reconciliation.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from studio_tools.task_files import (
    TaskError,
    append_checkpoint,
    card_repository,
    commit_card,
    field,
    git,
    read_clean_card,
    root_lock,
    safe_path,
    set_field,
    timestamp,
    validate_card,
    validate_id,
)


@dataclass(frozen=True)
class LaunchOptions:
    agent: str
    app: str
    task_id: str
    dry_run: bool
    takeover: bool
    extra: tuple[str, ...]


def parse_args(argv: list[str]) -> LaunchOptions:
    if not argv or argv[0] not in {"codex", "claude", "hermes"}:
        raise TaskError("用法：studio-launch <codex|claude|hermes> [--dry-run] [--takeover] <app> <ID> [-- args]", 2)
    positional: list[str] = []
    extra: list[str] = []
    dry_run = takeover = passthrough = False
    for arg in argv[1:]:
        if passthrough:
            extra.append(arg)
        elif arg == "--":
            passthrough = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg == "--takeover":
            takeover = True
        elif arg in {"-h", "--help"} or arg.startswith(("--dry-run", "--takeover")):
            raise TaskError("用法：studio-launch AGENT [--dry-run] [--takeover] APP ID [-- args]", 2)
        elif len(positional) == 2:
            extra.append(arg)
        elif arg.startswith("-"):
            raise TaskError("给 agent 的参数请放在 -- 之后", 2)
        else:
            positional.append(arg)
    if len(positional) != 2:
        raise TaskError("需要应用名和任务编号", 2)
    app, task_id = positional
    if not app or app.startswith(".") or "/" in app or "\\" in app or any(ord(c) < 32 for c in app):
        raise TaskError("应用名不合法", 2)
    validate_id(task_id)
    return LaunchOptions(argv[0], app, task_id, dry_run, takeover, tuple(extra))


def occupied_executor(executor: str) -> bool:
    return bool(executor) and not bool(re.match(r"^无(?:$|[（(；;，, ])", executor))


def claim(options: LaunchOptions, app: Path, card: Path, worktree: Path, branch: str) -> None:
    root = card_repository(card)
    with root_lock(root):
        content = read_clean_card(root, card)
        validate_card(content, options.task_id)
        executor = field(content, "当前执行者")
        occupied = occupied_executor(executor)
        if occupied and not options.takeover:
            raise TaskError("任务卡已有执行者，拒绝启动；确认中断后用 --takeover 接手", 3)
        if worktree.exists():
            top = Path(git(worktree, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
            common = git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
            expected_common = git(app, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
            if top != worktree or common != expected_common:
                raise TaskError("已有目录不是该应用的 worktree")
            actual = git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            if actual.returncode or not re.fullmatch(
                rf"agent/(?:codex|claude|hermes)/{re.escape(options.task_id)}", actual.stdout.strip()
            ):
                raise TaskError("已有工作树必须位于当前任务分支，不能是其他任务或分离 HEAD")

        else:
            exists = git(app, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
            args = (str(worktree), branch) if exists else ("-b", branch, str(worktree), "main")
            git(app, "worktree", "add", *args)
        now = timestamp()
        name = {"codex": "Codex", "claude": "Claude", "hermes": "Hermes"}[options.agent]
        updated = set_field(content, "当前执行者", f"{name}（启动器代认领；{now}）")
        updated = set_field(updated, "状态", "doing")
        updated = set_field(updated, "最后更新时间", now)
        if occupied and options.takeover:
            updated = append_checkpoint(updated, f"### 接管记录 · {now}\n\n原执行者：{executor}\n\n当前执行者：{name}")
        commit_card(root, card, content, updated, f"chore(tasks): 代认领 [{options.task_id}]")


def agent_command(options: LaunchOptions, worktree: Path) -> list[str]:
    if options.agent == "codex":
        command = ["codex", "--cd", str(worktree), "--sandbox", "workspace-write"]
    elif options.agent == "claude":
        command = ["claude", "--name", f"{options.app} {options.task_id}"]
    else:
        command = ["hermes", "--in", str(worktree)]
        if not options.extra or options.extra[0] != "chat":
            command.append("--tui")
    return command + list(options.extra)


def main(argv: list[str] | None = None) -> int:
    try:
        options = parse_args(sys.argv[1:] if argv is None else argv)
        studio = Path(os.environ.get("STUDIO_DIR", "../studio")).resolve()
        app = safe_path(studio.parent, studio.parent / options.app)
        if Path(git(app, "rev-parse", "--show-toplevel").stdout.strip()).resolve() != app:
            raise TaskError("应用目录不是独立 Git 仓库的根目录")
        card = safe_path(studio, studio / "项目/应用" / options.app / "tasks" / options.task_id / "task.md")
        content = card.read_text(encoding="utf-8")
        executor = field(content, "当前执行者")
        worktree = safe_path(app, app / ".claude/worktrees" / options.task_id)
        branch = f"agent/{options.agent}/{options.task_id}"
        current_branch = branch
        if worktree.exists():
            result = git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            current_branch = result.stdout.strip() if result.returncode == 0 else "（分离 HEAD 或非 worktree）"
        print(f"应用仓库：{app}\nworktree：{worktree}\n分支：{current_branch}\n任务卡：{card}\n当前执行者：{executor}")
        occupied = occupied_executor(executor)
        if occupied and not options.takeover:
            raise TaskError("任务卡已有执行者，拒绝启动；确认中断后用 --takeover 接手", 3)
        if occupied:
            print("警告：--takeover 将记录原执行者并代为认领；请确认原执行者已中断。", file=sys.stderr)
        if current_branch != branch:
            print(f"警告：已有 worktree 的分支是 {current_branch}，不是约定的 {branch}。", file=sys.stderr)
        if git(app, "check-ignore", "-q", f".claude/worktrees/{options.task_id}", check=False).returncode:
            print(f"警告：{options.app} 的 .gitignore 未忽略 .claude/worktrees/。", file=sys.stderr)
        if options.dry_run:
            print(f"dry-run：只打印，不创建 worktree，不启动 {options.agent}。")
            return 0
        executable = shutil.which(options.agent)
        if executable is None:
            raise TaskError(f"找不到 agent 命令：{options.agent}")
        claim(options, app, card, worktree, branch)
        command = agent_command(options, worktree)
        if options.agent == "claude":
            os.chdir(worktree)
        sys.stdout.flush()
        os.execve(executable, command, {k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
        return 0
    except (TaskError, OSError, UnicodeError) as exc:
        print(f"studio-launch：{exc}", file=sys.stderr)
        return exc.code if isinstance(exc, TaskError) else 1


if __name__ == "__main__":
    sys.exit(main())
