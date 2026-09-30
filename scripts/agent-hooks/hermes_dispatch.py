"""Run an installed, reviewed guard; never execute code from the target repository.

Usage: python3 hermes_dispatch.py /absolute/installed/guard_bash.py
The target repository's guard filename is only an opt-in marker. This dispatcher
and the guard are copied together to a private user-owned installation directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MAX_INPUT = 1_048_576


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("missing installed guard")
        guard = Path(sys.argv[1])
        if not guard.is_absolute() or guard.is_symlink() or not guard.is_file():
            raise ValueError("invalid installed guard")
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("payload too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")
        if not isinstance(payload.get("tool_name"), str):
            raise ValueError("invalid tool name")
        if payload["tool_name"] != "terminal":
            return 0
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            raise ValueError("invalid tool input")
        cwd = payload.get("cwd")
        workdir = tool_input.get("workdir")
        if not isinstance(cwd, str) or not cwd or len(cwd) > 4096:
            raise ValueError("invalid cwd")
        if workdir is not None and (not isinstance(workdir, str) or len(workdir) > 4096):
            raise ValueError("invalid workdir")
        directory = Path(os.path.join(cwd, workdir)) if workdir else Path(cwd)
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError("invalid effective directory")
        # Ignore inherited Git relocation variables: inspect the actual tool directory.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        protected = False
        for candidate in {str(directory), cwd}:
            result = subprocess.run(
                ["git", "-C", candidate, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
                env=env,
            )
            if result.returncode == 0:
                marker = Path(result.stdout.strip()) / ".claude/hooks/guard_bash.py"
                protected = protected or marker.is_file()
        if not protected:
            return 0
        # The marker is never imported/read/executed. The only executable is the
        # fixed installed copy named by the reviewed user configuration.
        return subprocess.run(
            [sys.executable, "-I", str(guard)],
            input=raw,
            check=False,
            timeout=5,
            cwd=directory,
            env=env,
        ).returncode
    except (ValueError, OSError, subprocess.TimeoutExpired):
        print("[studio-tools guard] Hermes 守卫输入或安装异常，已阻断。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
