#!/usr/bin/env python3
"""PostToolUse(Edit|Write) hook: run ``ruff format`` on an edited .py file.

Never blocks. Prefers the project's .venv ruff, then ``ruff`` on PATH, then
``uv run ruff``; silently skips when none is available.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def ruff_command(project_dir: Path) -> list[str] | None:
    local = project_dir / ".venv" / "bin" / "ruff"
    if local.exists():
        return [str(local)]
    found = shutil.which("ruff")
    if found:
        return [found]
    if shutil.which("uv") and (project_dir / "pyproject.toml").exists():
        return ["uv", "run", "--project", str(project_dir), "ruff"]
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not file_path.endswith(".py") or not Path(file_path).is_file():
        return 0
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    command = ruff_command(project_dir)
    if command is None:
        return 0
    try:
        result = subprocess.run(
            [*command, "format", file_path],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"[studio-tools] ruff format 未运行：{error}", file=sys.stderr)
        return 0
    if result.returncode != 0:
        print(f"[studio-tools] ruff format 失败：{result.stderr.strip()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
