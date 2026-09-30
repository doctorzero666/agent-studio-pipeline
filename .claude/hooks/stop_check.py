#!/usr/bin/env python3
"""Stop hook: refuse to end the turn while ``just check`` fails.

- ``stop_hook_active`` true  -> allow (exit 0) to avoid an endless loop.
- check passes              -> allow (exit 0).
- check fails / cannot run  -> block (exit 2) with the output tail on stderr.

``STUDIO_TOOLS_STOP_CMD`` overrides the command (used by tests).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

DEFAULT_COMMAND = "just check"
TAIL_LINES = 40


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    if payload.get("stop_hook_active") is True:
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    command = os.environ.get("STUDIO_TOOLS_STOP_CMD", DEFAULT_COMMAND)
    try:
        result = subprocess.run(
            shlex.split(command),
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=540,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"[studio-tools] 收工前检查无法运行（{command}）：{error}。请修复后再结束。", file=sys.stderr)
        return 2
    if result.returncode == 0:
        return 0
    output = (result.stdout + result.stderr).strip().splitlines()[-TAIL_LINES:]
    print(
        f"[studio-tools] 收工前检查失败：`{command}` 退出码 {result.returncode}。修复后再结束。输出尾部：",
        file=sys.stderr,
    )
    print("\n".join(output), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
