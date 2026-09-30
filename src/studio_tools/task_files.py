"""Task-card I/O shared by the launcher and checkpoint command.

Only tracked, clean task cards can be edited. Commits use --only so unrelated
staged changes remain staged. A ROOT-wide advisory lock serializes our writers;
other editors and Git clients must still coordinate with the orchestrator.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class TaskError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def git(directory: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    if check and result.returncode:
        raise TaskError(f"Git {args[0]} 失败（退出码 {result.returncode}）；请在终端检查仓库与钩子。")
    return result


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_id(task_id: str) -> None:
    if len(task_id) > 100 or not re.fullmatch(r"[A-Z][A-Z0-9]*-[0-9]{3,}", task_id):
        raise TaskError("任务编号格式不合法", 2)


def safe_path(base: Path, path: Path) -> Path:
    if not path.is_relative_to(base) or path.resolve() != path:
        raise TaskError("路径包含符号链接或越过允许的目录")
    for part in (path, *path.parents):
        if part == base:
            break
        if part.is_symlink():
            raise TaskError("路径包含符号链接")
    return path


def validate_card(content: str, task_id: str) -> None:
    if field(content, "任务编号").strip("`") != task_id:
        raise TaskError("任务卡中的任务编号与请求不一致")
    for name in ("状态", "当前执行者", "最后更新时间"):
        field(content, name)


def field(content: str, name: str) -> str:
    matches = list(re.finditer(rf"^\| {re.escape(name)} \|[^\n]*\|[ \t]*$", content, re.MULTILINE))
    if len(matches) != 1:
        raise TaskError(f"任务卡必须恰有一个 {name} 字段")
    return matches[0][0].split("|", 2)[2].rsplit("|", 1)[0].strip()


def set_field(content: str, name: str, value: str) -> str:
    field(content, name)
    return re.sub(rf"^\| {re.escape(name)} \|[^\n]*$", lambda _: f"| {name} | {value} |", content, flags=re.MULTILINE)


def append_checkpoint(content: str, entry: str) -> str:
    headings = list(re.finditer(r"^## 当前检查点[ \t]*$", content, re.MULTILINE))
    if len(headings) != 1:
        raise TaskError("任务卡必须恰有一个 当前检查点 章节")
    following = re.search(r"^## ", content[headings[0].end() :], re.MULTILINE)
    end = headings[0].end() + following.start() if following else len(content)
    return content[:end].rstrip() + "\n\n" + entry + "\n\n" + content[end:]


def card_repository(card: Path) -> Path:
    root = Path(git(card.parent, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if not card.is_relative_to(root):
        raise TaskError("任务卡不在 ROOT 仓库内")
    return root


@contextmanager
def root_lock(root: Path) -> Iterator[None]:
    """Fail promptly on contention; release automatically on exit or process death."""
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    descriptor = os.open(common / "studio-task.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TaskError("另一个任务命令正在写入 ROOT；请稍后重试") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_clean_card(root: Path, card: Path) -> str:
    relative = f":(literal){card.relative_to(root)}"
    git(root, "ls-files", "--error-unmatch", "--", relative)
    if git(root, "status", "--porcelain", "--", relative).stdout:
        raise TaskError("任务卡有未提交改动；请先由编排方处理")
    return card.read_text(encoding="utf-8")


def commit_card(root: Path, card: Path, original: str, updated: str, message: str) -> None:
    before = git(root, "rev-parse", "HEAD").stdout.strip()
    original_bytes = card.read_bytes()
    # Match read_clean_card's newline normalization while retaining exact rollback bytes.
    current = original_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if current != original:
        raise TaskError("任务卡已被其他进程修改；请重新核对")
    updated_bytes = updated.encode("utf-8")
    card.write_bytes(updated_bytes)
    relative = f":(literal){card.relative_to(root)}"
    result = git(root, "commit", "--only", "-m", message, "--", relative, check=False)
    if result.returncode:
        after = git(root, "rev-parse", "HEAD").stdout.strip()
        if after == before and card.read_bytes() == updated_bytes:
            card.write_bytes(original_bytes)
        raise TaskError("任务卡提交失败；未启动 agent。请检查 ROOT 状态与提交钩子后重试")
