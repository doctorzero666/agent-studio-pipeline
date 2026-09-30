#!/usr/bin/env python3
"""PreToolUse(Bash) guard.

Blocks (exit 2, reason on stderr):
- ``git push`` that targets main/master (explicit refspec, --all/--mirror, or a bare
  push while the current branch is main/master);
- ``gh pr merge``;
- any ``--no-verify`` (and ``git commit -n``).

Everything else is allowed (exit 0, no output). Standard library only.

本文件是三家 agent 共用的唯一规则来源（TOOLS-008，ADR 0004，说明见 ``docs/agent拦截钩子.md``）：
- Claude Code：``.claude/settings.json`` 的 PreToolUse，matcher ``Bash``；
- Codex CLI：仓库级 ``.codex/hooks.json`` 的 PreToolUse，matcher ``^Bash$``（tool_name ``Bash``）；
- Hermes Agent：用户级 ``~/.hermes/config.yaml`` 的 ``hooks.pre_tool_call``，matcher ``terminal``，
  片段见 ``scripts/agent-hooks/hermes-hooks.yaml``（tool_name ``terminal``，可带 ``tool_input.workdir``）。
三家都认"退出码 2 + stderr 写原因"为阻断。其它文件只负责定位并调用本脚本，不得复制规则。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}
SHELLS = {"sh", "bash", "zsh", "dash"}
# shell options that consume the next token (before the -c cluster)
SHELL_OPTS_WITH_VALUE = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")", "{", "}"}
# git global options that consume the next token
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
# wrappers that just run the rest of the line
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "time", "xargs"}


def split_segments(command: str) -> list[list[str]]:
    """Tokenize a shell command and split it into simple commands."""

    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in SEPARATORS or set(token) <= set(";&|()"):
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def strip_prefix(tokens: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and transparent wrappers."""

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            index += 1
        elif token.rsplit("/", 1)[-1] in WRAPPERS:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
        else:
            break
    return tokens[index:]


def current_branch(cwd: str | None) -> str:
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=5,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def refspec_targets_protected(arg: str) -> bool:
    ref = arg.lstrip("+")
    destination = ref.split(":", 1)[1] if ":" in ref else ref
    destination = destination.removeprefix("refs/heads/")
    return destination in PROTECTED


def check_git(args: list[str], cwd: str | None) -> str | None:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        option = args[index]
        index += 2 if option in GIT_OPTS_WITH_VALUE else 1
    if index >= len(args):
        return None
    subcommand, rest = args[index], args[index + 1 :]

    if subcommand == "commit":
        for token in rest:
            if token == "--":
                break
            if re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", token):
                return "禁止 git commit -n（等同 --no-verify）：提交必须经过 lefthook。"
        return None

    if subcommand != "push":
        return None
    if any(flag in rest for flag in ("--all", "--mirror")):
        return "禁止 git push --all/--mirror：会推送 main。请只推送 agent/<agent>/<任务ID> 分支。"
    positionals = [token for token in rest if not token.startswith("-")]
    refspecs = positionals[1:]
    if any(refspec_targets_protected(ref) for ref in refspecs):
        return "禁止推送到 main/master：agent 只能推 agent/<agent>/<任务ID> 分支，合并由用户执行。"
    if not refspecs or any(ref.lstrip("+").split(":", 1)[0] == "HEAD" and ":" not in ref for ref in refspecs):
        if current_branch(cwd) in PROTECTED:
            return "当前分支是 main/master，禁止不带分支名的 git push。"
    return None


def shell_script_arg(args: list[str]) -> str | None:
    """Return the script of ``sh/bash/zsh -c SCRIPT`` (also ``-lc``, ``-l -c``, ``--login -c``, ``-ec`` ...).

    Scans options up to the first short-option cluster containing ``c``; options that take a value
    (``-o``/``-O``/``--rcfile``/``--init-file``) skip it. A non-option argument (a script file) ends the scan.
    """

    index = 0
    while index < len(args):
        token = args[index]
        if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token):
            return args[index + 1] if index + 1 < len(args) else None
        if token in SHELL_OPTS_WITH_VALUE:
            index += 2
        elif token == "--":
            return None
        elif token.startswith(("-", "+")):
            index += 1
        else:
            return None
    return None


def check_segment(tokens: list[str], cwd: str | None, depth: int) -> str | None:
    tokens = strip_prefix(tokens)
    if not tokens:
        return None
    program = tokens[0].rsplit("/", 1)[-1]
    args = tokens[1:]

    if program in SHELLS and depth < 3:
        script = shell_script_arg(args)
        if script is not None:
            return check_command(script, cwd, depth + 1)
    if program == "eval" and depth < 3:
        return check_command(" ".join(args), cwd, depth + 1)
    if program == "git":
        return check_git(args, cwd)
    if program == "gh":
        positionals: list[str] = []
        skip = False
        for token in args:
            if skip:
                skip = False
            elif token in ("-R", "--repo"):
                skip = True
            elif not token.startswith("-"):
                positionals.append(token)
        if positionals[:2] == ["pr", "merge"]:
            return "禁止 gh pr merge：合并只能由用户执行。"
    return None


def check_command(command: str, cwd: str | None, depth: int = 0) -> str | None:
    """Return a block reason, or None when the command is allowed."""

    if re.search(r"--no-verify\b", command):
        return "禁止 --no-verify：提交与推送必须经过 lefthook 检查。"
    try:
        segments = split_segments(command)
    except ValueError:
        # Unparseable (e.g. unbalanced quotes): fall back to conservative regexes.
        if re.search(r"\bgit\b.*\bpush\b.*\b(main|master)\b", command):
            return "无法解析的命令中疑似 git push 到 main/master，已阻断。"
        if re.search(r"\bgh\b.*\bpr\b.*\bmerge\b", command):
            return "无法解析的命令中疑似 gh pr merge，已阻断。"
        return None
    for segment in segments:
        reason = check_segment(segment, cwd, depth)
        if reason:
            return reason
    return None


# 以下只做输入适配，不含规则：哪些工具名承载 shell 命令、命令与工作目录从哪里取。
# Claude Code 与 Codex 的 shell 工具名是 "Bash"，Hermes 的是 "terminal"。
SHELL_TOOL_NAMES = {"Bash", "terminal"}


def command_from_input(tool_input: object) -> str:
    """取 ``tool_input.command``；为 argv 列表时按 shell 写法拼成字符串。"""

    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command")
    if isinstance(command, list):
        return shlex.join(str(part) for part in command)
    return command if isinstance(command, str) else ""


def cwd_from_payload(payload: dict) -> str | None:
    """命令实际运行的目录。

    Hermes 的 terminal 工具有逐条命令的 ``workdir`` 参数（schema 要求绝对路径），它优先于负载里的
    ``cwd``（Hermes 填的是自身进程的 cwd）；相对 workdir 按 ``cwd`` 拼接。
    """

    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    tool_input = payload.get("tool_input")
    workdir = tool_input.get("workdir") if isinstance(tool_input, dict) else None
    if isinstance(workdir, str) and workdir:
        return os.path.join(cwd, workdir) if cwd else workdir
    return cwd


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if (payload.get("tool_name") or "Bash") not in SHELL_TOOL_NAMES:
        return 0
    command = command_from_input(payload.get("tool_input"))
    reason = check_command(command, cwd_from_payload(payload))
    if reason:
        print(f"[studio-tools guard] {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
