from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from studio_tools.check_studio import validate_markdown_links, validate_task


class MarkdownLinkTests(unittest.TestCase):
    def test_reports_link_outside_studio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            page = root / "page.md"
            page.write_text("[outside](../secret.md)\n", encoding="utf-8")

            errors = validate_markdown_links(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("链接越出 studio", errors[0])

    def test_accepts_existing_relative_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target.md"
            target.write_text("# Target\n", encoding="utf-8")
            (root / "page.md").write_text("[target](target.md)\n", encoding="utf-8")

            self.assertEqual(validate_markdown_links(root), [])


class TaskValidationTests(unittest.TestCase):
    def test_rejects_unknown_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            task_directory = root / "SYS-001"
            task_directory.mkdir()
            task = task_directory / "task.md"
            task.write_text(
                "\n".join(
                    (
                        "# Task",
                        "| 任务编号 | `SYS-001` |",
                        "| 状态 | waiting |",
                        "## 目标与验收",
                        "## 阅读入口",
                        "## 当前检查点",
                        "## 对外操作与授权",
                    )
                ),
                encoding="utf-8",
            )

            errors = validate_task(task, root)

            self.assertEqual(len(errors), 1)
            self.assertIn("未知状态", errors[0])


if __name__ == "__main__":
    unittest.main()
