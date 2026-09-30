"""Bounded foreground agent runs with metadata receipts and explicit quota-only fallback.

No daemon, hidden API client, automatic purchase, retry of unknown outcomes or auto-merge.
Provider billing is controlled by the user's CLI configuration, not by this supervisor.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from studio_tools.launcher import LaunchOptions, agent_command, claim
from studio_tools.scaffold import name, studio_root
from studio_tools.task_files import TaskError, git, safe_path, timestamp, validate_id

QUOTA = re.compile(r"you['’]ve hit your limit|usage limit (?:reached|exceeded)|quota exceeded", re.IGNORECASE)


def group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def terminate(process: subprocess.Popen) -> bool:
    """Reap the leader AND stop residual writers in its process group."""
    if group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    if group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)
    deadline = time.monotonic() + 2
    while group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not group_exists(process.pid)


def execute(command: list[str], cwd: Path, env: dict[str, str], timeout: int) -> dict:
    start = time.monotonic()
    # CLI output may contain private material: never persist it in receipts or echo it into Git.
    with tempfile.TemporaryFile(mode="w+b") as output:
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True
        )
        outcome = "failed"
        try:
            process.wait(timeout=timeout)
            outcome = "exited" if process.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            terminate(process)
            outcome = "timeout"
        except KeyboardInterrupt:
            terminate(process)
            outcome = "interrupted"
        group_stopped = terminate(process)
        output.seek(0, os.SEEK_END)
        size = output.tell()
        output.seek(max(0, size - 65536))
        tail = output.read().decode("utf-8", errors="replace")
        if outcome == "failed" and QUOTA.search(tail):
            outcome = "quota"
    return {
        "outcome": outcome,
        "group_stopped": group_stopped,
        "returncode": process.returncode,
        "seconds": round(time.monotonic() - start, 3),
        "at": timestamp(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", choices=("codex", "claude", "hermes"))
    parser.add_argument("app")
    parser.add_argument("task_id")
    parser.add_argument("--studio")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--takeover", action="store_true")
    parser.add_argument(
        "--fallback",
        choices=("codex", "claude", "hermes"),
        help="Explicitly authorize one alternate CLI after a quota error; may consume its configured plan",
    )
    parser.add_argument("--prompt-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.timeout <= 7200:
            raise TaskError("Timeout must be 1–7200 seconds.", 2)
        if args.fallback == args.agent:
            raise TaskError("Fallback must differ from the primary agent.", 2)
        name(args.app)
        validate_id(args.task_id)
        studio = studio_root(args.studio)
        app = safe_path(studio.parent, studio.parent / args.app)
        if args.prompt_file.stat().st_size > 32768:
            raise TaskError("Prompt file exceeds 32 KiB.", 2)
        prompt = args.prompt_file.read_text(encoding="utf-8")
        if not prompt.strip() or "\x00" in prompt:
            raise TaskError("Prompt must be nonempty text without NUL.", 2)
        common = Path(git(app, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
        lock_path = common / f"studio-run-{args.task_id}.lock"
        with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TaskError("A supervised run already owns this task; reconcile it before takeover.", 3) from exc
            agents = [args.agent] + ([args.fallback] if args.fallback else [])
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            env["STUDIO_DIR"] = str(studio)
            receipts = []
            for index, agent in enumerate(agents):
                extra = {
                    "codex": ["exec", prompt],
                    "claude": ["-p", "--", prompt],
                    "hermes": ["chat", "--oneshot", "-q", prompt],
                }[agent]
                if not shutil.which(agent):
                    raise TaskError(f"Agent CLI is not installed: {agent}")
                worktree = safe_path(app, app / ".claude/worktrees" / args.task_id)
                card = safe_path(studio, studio / "项目/应用" / args.app / "tasks" / args.task_id / "task.md")
                if Path(git(app, "rev-parse", "--show-toplevel").stdout.strip()).resolve() != app:
                    raise TaskError("Application must be an independent Git repository.")
                options = LaunchOptions(
                    agent, args.app, args.task_id, False, args.takeover or bool(index), tuple(extra)
                )
                # Claim failure exits before any supervisor checkpoint. Existing owners remain untouched.
                claim(options, app, card, worktree, f"agent/{agent}/{args.task_id}")
                result = execute(agent_command(options, worktree), worktree, env, args.timeout)
                result["agent"] = agent
                worktree = app / ".claude/worktrees" / args.task_id
                if worktree.is_dir():
                    checkpoint = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "studio_tools.checkpoint",
                            args.task_id,
                            f"Supervisor: {agent} {result['outcome']}; rc={result['returncode']}. "
                            "Reconcile files and external operations before resuming. "
                            "Exit 0 does not certify completion.",
                        ],
                        cwd=worktree,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    result["checkpoint_returncode"] = checkpoint.returncode
                receipts.append(result)
                # Unknown failures/timeouts are never retried. A failed checkpoint also blocks fallback.
                if (
                    result["outcome"] != "quota"
                    or result.get("checkpoint_returncode", 1) != 0
                    or not result["group_stopped"]
                ):
                    break
            destination = common / "studio-runs"
            destination.mkdir(mode=0o700, exist_ok=True)
            receipt = destination / f"{args.task_id}-{time.time_ns()}.json"
            with receipt.open("x", encoding="utf-8") as stream:
                json.dump({"task": args.task_id, "attempts": receipts}, stream, indent=2)
                stream.write("\n")
            print(json.dumps({"receipt": str(receipt), "attempts": receipts}, indent=2))
            last = receipts[-1]
            return (
                0
                if last["outcome"] == "exited" and last.get("checkpoint_returncode") == 0 and last["group_stopped"]
                else 1
            )
    except (TaskError, OSError, UnicodeError) as exc:
        print(f"studio-run: {exc}", file=sys.stderr)
        return exc.code if isinstance(exc, TaskError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
