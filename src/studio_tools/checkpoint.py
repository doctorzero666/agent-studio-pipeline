"""Append and commit a task checkpoint from its application checkout/worktree.

Usage: studio-checkpoint ID "description" [--test-tail "last check output line"]
STUDIO_DIR overrides the studio directory inferred beside the main app checkout.
The command must run outside an agent sandbox that makes ROOT read-only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from studio_tools.task_files import (
    TaskError,
    append_checkpoint,
    card_repository,
    commit_card,
    git,
    read_clean_card,
    root_lock,
    safe_path,
    set_field,
    timestamp,
    validate_card,
    validate_id,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("description")
    parser.add_argument("--test-tail", help="检查输出末行（只记录，不代表命令已由本工具运行）")
    args = parser.parse_args(argv)
    try:
        validate_id(args.task_id)
        if (
            not args.description.strip()
            or len(args.description) > 20000
            or any(ord(char) < 32 and char not in "\n\t" or ord(char) == 127 for char in args.description)
        ):
            raise TaskError("说明须为 1–20000 字符，不能包含控制字符（换行与制表符除外）", 2)
        if args.test_tail is not None and (
            not args.test_tail.strip()
            or len(args.test_tail) > 2000
            or any(ord(char) < 32 or ord(char) == 127 for char in args.test_tail)
        ):
            raise TaskError("测试末行须为 1–2000 字符的单行文本", 2)
        cwd = Path.cwd()
        common = Path(git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
        app = common.resolve().parent
        studio = Path(os.environ.get("STUDIO_DIR", str(app.parent / "studio"))).resolve()
        if app != studio.parent / app.name:
            raise TaskError("当前应用仓库必须与 studio 平级")
        expected = safe_path(app, app / ".claude/worktrees" / args.task_id)
        actual_top = Path(git(cwd, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
        actual_branch = git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if (
            actual_top != expected
            or actual_branch.returncode
            or not re.fullmatch(
                rf"agent/(?:codex|claude|hermes)/{re.escape(args.task_id)}", actual_branch.stdout.strip()
            )
        ):
            raise TaskError("检查点只能从对应任务的工作树和分支记录")
        card = safe_path(studio, studio / "项目/应用" / app.name / "tasks" / args.task_id / "task.md")
        root = card_repository(card)
        with root_lock(root):
            content = read_clean_card(root, card)
            validate_card(content, args.task_id)
            now = timestamp()
            branch_result = git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "（分离 HEAD）"
            commit = git(cwd, "rev-parse", "--short", "HEAD").stdout.strip()
            dirty = bool(git(cwd, "status", "--porcelain").stdout)
            description = "\n".join(f"> {line}" for line in args.description.splitlines())
            entry = (
                f"### 检查点 · {now}\n\n{description}\n\n"
                f"- 分支：`{branch}`\n- 最后提交：`{commit}`\n- 工作区：{'不干净' if dirty else '干净'}"
            )
            if args.test_tail is not None:
                entry += f"\n\n检查末行（调用方提供）：\n\n> {args.test_tail}"
            updated = append_checkpoint(content, entry)
            updated = set_field(updated, "最后更新时间", now)
            commit_card(root, card, content, updated, f"docs(tasks): 追加检查点 [{args.task_id}]")
        print(f"已提交检查点：{card}")
        return 0
    except (TaskError, OSError, UnicodeError) as exc:
        print(f"studio-checkpoint：{exc}", file=sys.stderr)
        return exc.code if isinstance(exc, TaskError) else 1


if __name__ == "__main__":
    sys.exit(main())
