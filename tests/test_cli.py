"""CLI-level tests: output text and exit codes of ``studio-check``."""

from __future__ import annotations

from pathlib import Path

import pytest

from studio_tools.check_studio import REQUIRED_PATHS, main

TASK_CARD = "\n".join(
    (
        "# Task",
        "| 任务编号 | `SYS-001` |",
        "| 状态 | todo |",
        "## 目标与验收",
        "## 阅读入口",
        "## 当前检查点",
        "## 对外操作与授权",
        "",
    )
)


def make_studio(root: Path) -> None:
    for relative in REQUIRED_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# x\n", encoding="utf-8")
    # 规则 2（STATUS／队列／任务卡一致性）要求任务登记到队列、STATUS 当前重点指向实时任务。
    (root / "registry" / "任务队列.md").write_text(
        "| 任务编号 | 任务卡 |\n|---|---|\n| `SYS-001` | [打开](../项目/内部/SYS-001/task.md) |\n", encoding="utf-8"
    )
    (root / "STATUS.md").write_text("# 当前状态\n\n## 当前重点\n\n`SYS-001`\n", encoding="utf-8")
    task = root / "项目" / "内部" / "SYS-001" / "task.md"
    task.parent.mkdir(parents=True)
    task.write_text(TASK_CARD, encoding="utf-8")


def test_passes_minimal_studio(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_studio(tmp_path)
    markdown_count = sum(1 for relative in REQUIRED_PATHS if relative.endswith(".md")) + 1

    assert main([str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"Studio 检查通过：{markdown_count} 个 Markdown 文件，1 个实时任务。\n"
    assert captured.err == ""


def test_reports_missing_paths_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_studio(tmp_path)
    (tmp_path / "STATUS.md").unlink()

    assert main([str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Studio 检查失败：\n- 缺少必要路径：STATUS.md\n"


def test_relative_argument_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    studio = tmp_path / "studio"
    studio.mkdir()
    make_studio(studio)
    work = tmp_path / "studio-tools"
    work.mkdir()
    monkeypatch.chdir(work)

    assert main([]) == 0
    assert "1 个实时任务" in capsys.readouterr().out
