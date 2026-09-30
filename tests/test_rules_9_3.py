"""方案 9.3 新增的 6 项检查（TOOLS-001）。

每项至少一个失败用例（构造不合规数据，断言报错）和一个通过用例。
测试通过模块属性调用新函数，未实现的规则只让自己的用例失败，不影响其他用例。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from studio_tools import check_studio as cs


def card(
    task_id: str = "SYS-001",
    *,
    status: str = "todo",
    executor: str | None = "无",
    updated: str = "2026-09-29，Australia/Sydney",
    repo: str | None = None,
    pr: str | None = None,
    ci: str | None = None,
    headings: tuple[str, ...] = cs.TASK_HEADINGS,
) -> str:
    """Build a task card; ``None`` leaves a field out entirely."""

    lines = ["# Task", "", "| 字段 | 值 |", "|---|---|", f"| 任务编号 | `{task_id}` |", f"| 状态 | {status} |"]
    if executor is not None:
        lines.append(f"| 当前执行者 | {executor} |")
    lines.append(f"| 最后更新时间 | {updated} |")
    for name, value in (("代码仓库", repo), ("PR", pr), ("CI 结果", ci)):
        if value is not None:
            lines.append(f"| {name} | {value} |")
    lines.extend(("", *headings, ""))
    return "\n".join(lines)


def write_task(root: Path, content: str, task_id: str = "SYS-001", area: str = "内部") -> Path:
    path = root / "项目" / area / task_id / "task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# 规则 1：标题精确匹配


def test_rule1_rejects_lower_level_heading(tmp_path: Path) -> None:
    headings = ("### 目标与验收", "## 阅读入口", "## 当前检查点", "## 对外操作与授权")
    task = write_task(tmp_path, card(headings=headings))

    errors = cs.validate_task(task, tmp_path)

    assert errors == ["项目/内部/SYS-001/task.md：缺少章节：## 目标与验收"]


def test_rule1_rejects_heading_with_suffix(tmp_path: Path) -> None:
    headings = ("## 目标与验收（草稿）", "## 阅读入口", "## 当前检查点", "## 对外操作与授权")
    task = write_task(tmp_path, card(headings=headings))

    assert cs.validate_task(task, tmp_path) == ["项目/内部/SYS-001/task.md：缺少章节：## 目标与验收"]


def test_rule1_accepts_exact_headings_with_trailing_space(tmp_path: Path) -> None:
    headings = ("## 目标与验收 ", "## 阅读入口", "## 当前检查点", "## 对外操作与授权")
    task = write_task(tmp_path, card(headings=headings))

    assert cs.validate_task(task, tmp_path) == []


# 规则 2：STATUS／队列／任务卡一致性

QUEUE_HEADER = "# 任务队列\n\n| 任务编号 | 项目 | 优先级 | 摘要 | 任务卡 |\n|---|---|---:|---|---|\n"


def queue_text(*rows: str) -> str:
    """表头加数据行组成的队列正文；第一行数据行的行号是 5。"""

    return QUEUE_HEADER + "".join(f"{row}\n" for row in rows)


def write_queue(root: Path, *rows: str) -> None:
    path = root / "registry" / "任务队列.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(queue_text(*rows), encoding="utf-8")


def write_status(root: Path, focus: str) -> None:
    (root / "STATUS.md").write_text(
        f"# 当前状态\n\n## 当前重点\n\n{focus}\n\n## 下一步\n\n- `SYS-009`\n", encoding="utf-8"
    )


def queue_row(task_id: str, link: str | None = None) -> str:
    target = link if link is not None else f"[打开](../项目/内部/{task_id}/task.md)"
    return f"| `{task_id}` | STUDIO | P1 | 摘要 | {target} |"


def consistent_studio(root: Path) -> None:
    write_task(root, card("SYS-001", status="doing", executor="Claude"), "SYS-001")
    write_queue(root, queue_row("SYS-001"))
    write_status(root, "`SYS-001`：进行中。")


def test_rule2_accepts_consistent_studio(tmp_path: Path) -> None:
    consistent_studio(tmp_path)

    assert cs.validate_consistency(tmp_path) == []


def test_rule2_rejects_queue_row_without_task_card(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), queue_row("SYS-002"))

    assert cs.validate_consistency(tmp_path) == ["registry/任务队列.md：SYS-002 找不到对应的 task.md"]


def test_rule2_rejects_task_card_missing_from_queue(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_task(tmp_path, card("SYS-002"), "SYS-002")

    assert cs.validate_consistency(tmp_path) == ["项目/内部/SYS-002/task.md：任务未登记到任务队列：SYS-002"]


def test_rule2_accepts_index_row_pointing_outside_studio(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), queue_row("AICH-001", "`ai-channel/tasks/AICH-001/task.md`"))

    assert cs.validate_consistency(tmp_path) == []


def test_rule2_rejects_index_row_when_studio_still_has_card(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_task(tmp_path, card("AICH-001"), "AICH-001", area="内容")
    write_queue(tmp_path, queue_row("SYS-001"), queue_row("AICH-001", "`ai-channel/tasks/AICH-001/task.md`"))

    assert cs.validate_consistency(tmp_path) == [
        "registry/任务队列.md：AICH-001 是指向 studio 外的索引行，但 studio 内仍有任务卡：项目/内容/AICH-001/task.md"
    ]


def test_rule2_inline_path_inside_studio_is_not_an_index_row(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), queue_row("SYS-003", "`项目/内部/SYS-003/task.md`"))

    assert cs.validate_consistency(tmp_path) == ["registry/任务队列.md：SYS-003 找不到对应的 task.md"]


def test_rule2_rejects_status_focus_on_done_task(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_task(tmp_path, card("SYS-001", status="`done`"), "SYS-001")

    assert cs.validate_consistency(tmp_path) == ["STATUS.md：当前重点指向已完成的任务：SYS-001"]


def test_rule2_rejects_status_focus_on_missing_task(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_status(tmp_path, "`SYS-001` 与 `SYS-404`。")

    assert cs.validate_consistency(tmp_path) == ["STATUS.md：当前重点指向的任务不存在：SYS-404"]


def test_rule2_rejects_status_without_focus_task(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_status(tmp_path, "暂无。")

    assert cs.validate_consistency(tmp_path) == ["STATUS.md：当前重点没有指向任何任务编号"]


def test_rule2_status_focus_may_name_index_row_task(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), queue_row("AICH-001", "`ai-channel/tasks/AICH-001/task.md`"))
    write_status(tmp_path, "`SYS-001`；频道任务 `AICH-001` 见频道仓库。")

    assert cs.validate_consistency(tmp_path) == []


# 规则 3：doing 无执行者

DOING_WITHOUT_EXECUTOR = "项目/内部/SYS-001/task.md：状态为 doing 但当前执行者为空"


def test_rule3_rejects_doing_with_executor_none(tmp_path: Path) -> None:
    task = write_task(tmp_path, card(status="doing", executor="无"))

    assert cs.validate_task(task, tmp_path) == [DOING_WITHOUT_EXECUTOR]


def test_rule3_rejects_doing_with_executor_none_and_note(tmp_path: Path) -> None:
    task = write_task(tmp_path, card(status="`doing`", executor="无（CP-011 后释放；负责人执行试跑）"))

    assert cs.validate_task(task, tmp_path) == [DOING_WITHOUT_EXECUTOR]


def test_rule3_rejects_doing_with_blank_or_missing_executor(tmp_path: Path) -> None:
    blank = write_task(tmp_path, card(status="doing", executor=" "))
    assert cs.validate_task(blank, tmp_path) == [DOING_WITHOUT_EXECUTOR]

    missing = write_task(tmp_path, card(status="doing", executor=None))
    assert cs.validate_task(missing, tmp_path) == [DOING_WITHOUT_EXECUTOR]


def test_rule3_accepts_doing_with_named_executor(tmp_path: Path) -> None:
    task = write_task(tmp_path, card(status="doing", executor="Claude Opus 5.5 subagent（会话开始 2026-09-29）"))

    assert cs.validate_task(task, tmp_path) == []


def test_rule3_ignores_executor_when_not_doing(tmp_path: Path) -> None:
    task = write_task(tmp_path, card(status="blocked", executor="无"))

    assert cs.validate_task(task, tmp_path) == []


def test_b3_2_noncompliant_card_reports_every_problem(tmp_path: Path) -> None:
    """验收门 B3-2：doing 无执行者且标题层级错误的任务卡，两项都报错。"""

    headings = ("### 目标与验收", "## 阅读入口", "## 当前检查点", "## 对外操作与授权")
    task = write_task(tmp_path, card(status="doing", executor="无", headings=headings))

    assert cs.validate_task(task, tmp_path) == [
        "项目/内部/SYS-001/task.md：缺少章节：## 目标与验收",
        DOING_WITHOUT_EXECUTOR,
    ]


# 规则 4：停滞认领（只警告，不影响退出码）

TODAY = date(2026, 9, 29)
STALE = "项目/内部/SYS-001/task.md：doing 已 4 天未更新（最后更新时间 2026-09-25，阈值 3 天），请核实认领是否仍有效"


def test_rule4_default_threshold_is_three_days() -> None:
    assert cs.STALE_CLAIM_DAYS == 3


def test_rule4_warns_when_doing_claim_is_stale(tmp_path: Path) -> None:
    write_task(tmp_path, card(status="doing", executor="Claude", updated="2026-09-25 15:10 AEST"))

    assert cs.collect_warnings(tmp_path, today=TODAY) == [STALE]


def test_rule4_threshold_day_is_not_stale(tmp_path: Path) -> None:
    write_task(tmp_path, card(status="doing", executor="Claude", updated="2026-09-26，Australia/Sydney"))

    assert cs.collect_warnings(tmp_path, today=TODAY) == []


def test_rule4_ignores_stale_date_when_not_doing(tmp_path: Path) -> None:
    write_task(tmp_path, card(status="blocked", updated="2026-01-01"))

    assert cs.collect_warnings(tmp_path, today=TODAY) == []


def test_rule4_warns_when_update_time_unparseable(tmp_path: Path) -> None:
    write_task(tmp_path, card(status="doing", executor="Claude", updated="上周"))

    assert cs.collect_warnings(tmp_path, today=TODAY) == [
        "项目/内部/SYS-001/task.md：doing 任务的最后更新时间无法解析：上周"
    ]


def test_rule4_cli_prints_warning_block_and_still_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for relative in cs.REQUIRED_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# x\n", encoding="utf-8")
    consistent_studio(tmp_path)
    write_task(tmp_path, card(status="doing", executor="Claude", updated="2026-09-25 15:10 AEST"))
    markdown_count = len(cs.markdown_files(tmp_path))

    assert cs.main([str(tmp_path)], today=TODAY) == 0
    captured = capsys.readouterr()
    assert captured.err == f"Studio 检查警告：\n- {STALE}\n"
    assert captured.out == f"Studio 检查通过：{markdown_count} 个 Markdown 文件，1 个实时任务。\n"


# 规则 5：review／done 的代码任务，PR 与 CI 结果不能为空

REPO = "`studio-tools`（`个人工作室/studio-tools`，无远程）"
PR_OK = "本地分支 agent/claude/TOOLS-001（阶段 0 无托管），待负责人合并"
CI_OK = "just check rc=0，70 passed，提交 abc1234"
LABEL = "项目/内部/SYS-001/task.md"


@pytest.mark.parametrize("status", ["review", "`done`"])
@pytest.mark.parametrize("empty", ["无", "无（阶段 0 本地；合并后记录合并提交号）", "未运行", " "])
def test_rule5_rejects_empty_pr_and_ci(tmp_path: Path, status: str, empty: str) -> None:
    task = write_task(tmp_path, card(status=status, repo=REPO, pr=empty, ci=empty))
    shown = status.strip("`")

    assert cs.validate_task(task, tmp_path) == [
        f"{LABEL}：状态为 {shown} 的代码任务缺少 PR 记录",
        f"{LABEL}：状态为 {shown} 的代码任务缺少 CI 结果",
    ]


def test_rule5_rejects_missing_ci_field(tmp_path: Path) -> None:
    task = write_task(tmp_path, card(status="review", repo=REPO, pr=PR_OK))

    assert cs.validate_task(task, tmp_path) == [f"{LABEL}：状态为 review 的代码任务缺少 CI 结果"]


def test_rule5_accepts_filled_code_fields(tmp_path: Path) -> None:
    task = write_task(tmp_path, card(status="review", repo=REPO, pr=PR_OK, ci=CI_OK))

    assert cs.validate_task(task, tmp_path) == []


def test_rule5_ignores_non_code_tasks(tmp_path: Path) -> None:
    not_applicable = write_task(tmp_path, card(status="done", repo="不适用（编排任务）", pr="不适用", ci="无"))
    assert cs.validate_task(not_applicable, tmp_path) == []

    legacy = write_task(tmp_path, card(status="done"))
    assert cs.validate_task(legacy, tmp_path) == []


def test_rule5_ignores_code_task_before_review(tmp_path: Path) -> None:
    task = write_task(tmp_path, card(status="doing", executor="Claude", repo=REPO, pr="无", ci="未运行"))

    assert cs.validate_task(task, tmp_path) == []


# 规则 6：指向应用仓库只能用行内代码路径或 https 链接


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """``tmp/studio`` 旁边有平级应用仓库 ``tmp/studio-tools``，studio 内有同名应用项目目录。"""

    studio = tmp_path / "studio"
    project = studio / "项目" / "应用" / "studio-tools" / "project.md"
    project.parent.mkdir(parents=True)
    project.write_text("# studio-tools\n", encoding="utf-8")
    source = tmp_path / "studio-tools" / "src" / "x.py"
    source.parent.mkdir(parents=True)
    source.write_text("", encoding="utf-8")
    return studio


def app_link_error(target: str) -> str:
    return f"page.md：指向应用仓库 studio-tools 的链接须改为行内代码路径或 https 链接：{target}"


@pytest.mark.parametrize(
    "target",
    [
        "../studio-tools/src/x.py",
        "http://github.com/me/studio-tools/blob/main/README.md",
        "file:///tmp/studio-tools/src/x.py",
    ],
)
def test_rule6_rejects_non_https_links_into_app_repo(workspace: Path, target: str) -> None:
    (workspace / "page.md").write_text(f"[代码]({target})\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == [app_link_error(target)]


def test_rule6_rejects_absolute_path_into_app_repo(workspace: Path) -> None:
    target = str(workspace.parent / "studio-tools" / "src" / "x.py")
    (workspace / "page.md").write_text(f"[代码]({target})\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == [app_link_error(target)]


def test_rule6_accepts_inline_code_https_and_studio_project_links(workspace: Path) -> None:
    (workspace / "page.md").write_text(
        "\n".join(
            (
                "代码见 `studio-tools/src/x.py`。",
                "[仓库](https://github.com/me/studio-tools)",
                "[项目](项目/应用/studio-tools/project.md)",
                "[别处](../other/notes.md)",
                "",
            )
        ),
        encoding="utf-8",
    )

    assert cs.validate_app_links(workspace) == []


def test_rule6_is_part_of_run_checks(workspace: Path) -> None:
    (workspace / "page.md").write_text("[代码](../studio-tools/src/x.py)\n", encoding="utf-8")

    assert app_link_error("../studio-tools/src/x.py") in cs.run_checks(workspace)


@pytest.mark.parametrize("repo_name", ["Studio-tools", "STUDIO-TOOLS"])
@pytest.mark.parametrize("link_kind", ["http", "file", "relative", "absolute"])
def test_rule6_rejects_repo_case_variants(workspace: Path, repo_name: str, link_kind: str) -> None:
    targets = {
        "http": f"http://github.com/me/{repo_name}",
        "file": f"file:///tmp/{repo_name}/src/x.py",
        "relative": f"../{repo_name}/src/x.py",
        "absolute": str(workspace.parent / repo_name / "src" / "x.py"),
    }
    target = targets[link_kind]
    (workspace / "page.md").write_text(f"[代码]({target})\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == [app_link_error(target)]


@pytest.mark.parametrize("repo_name", ["Studio-tools", "STUDIO-TOOLS"])
@pytest.mark.parametrize(
    "markdown",
    [
        "[仓库](https://github.com/me/{repo_name})",
        "代码见 `../{repo_name}/src/x.py`。",
        "[项目](项目/应用/{repo_name}/project.md)",
        "[其他仓库](http://github.com/me/{repo_name}-extra)",
    ],
)
def test_rule6_accepts_allowed_repo_case_variants(workspace: Path, repo_name: str, markdown: str) -> None:
    (workspace / "page.md").write_text(markdown.format(repo_name=repo_name) + "\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == []


def test_rule6_matches_mixed_case_registered_repo_and_preserves_error(workspace: Path) -> None:
    repo_name = "Mixed-App"
    (workspace / "项目" / "应用" / repo_name).mkdir()
    target = "http://github.com/me/mixed-app"
    (workspace / "page.md").write_text(f"[代码]({target})\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == [
        f"page.md：指向应用仓库 {repo_name} 的链接须改为行内代码路径或 https 链接：{target}"
    ]


# 评审阻塞项 1（Codex）：队列编号没有反引号时不能被静默跳过


def test_review1_plain_text_queue_id_without_card_is_reported(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_queue(
        tmp_path, queue_row("SYS-001"), "| SYS-999 | STUDIO | P1 | 摘要 | [打开](../项目/内部/SYS-999/task.md) |"
    )

    assert cs.validate_consistency(tmp_path) == ["registry/任务队列.md：SYS-999 找不到对应的 task.md"]


def test_review1_plain_text_queue_id_with_card_is_accepted(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_queue(tmp_path, "| SYS-001 | STUDIO | P1 | 摘要 | [打开](../项目/内部/SYS-001/task.md) |")

    assert cs.validate_consistency(tmp_path) == []


def test_review1_unrecognised_queue_id_is_a_format_error(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), "| `sys-7` | STUDIO | P1 | 摘要 | 无 |")

    assert cs.validate_consistency(tmp_path) == ["registry/任务队列.md：队列行的任务编号格式无法识别：`sys-7`"]


def test_review1_full_check_fails_on_plain_text_queue_id(tmp_path: Path) -> None:
    for relative in cs.REQUIRED_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# x\n", encoding="utf-8")
    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), "| SYS-999 | STUDIO | P1 | 摘要 | 待建 |")

    assert cs.main([str(tmp_path)], today=TODAY) == 1


# 评审阻塞项 2（Codex）：索引行要先按平级仓库路径规范化，确认目标确实在 studio 外


def sibling_studio(tmp_path: Path) -> Path:
    studio = tmp_path / "studio"
    consistent_studio(studio)
    return studio


def test_review2_index_path_resolving_back_into_studio_is_not_exempt(tmp_path: Path) -> None:
    studio = sibling_studio(tmp_path)
    write_queue(studio, queue_row("SYS-001"), queue_row("SYS-999", "`ai-channel/../studio/项目/内部/SYS-999/task.md`"))

    assert cs.validate_consistency(studio) == ["registry/任务队列.md：SYS-999 找不到对应的 task.md"]


def test_review2_index_path_back_into_studio_with_existing_card_is_consistent(tmp_path: Path) -> None:
    studio = sibling_studio(tmp_path)
    write_task(studio, card("SYS-002"), "SYS-002")
    write_queue(
        studio,
        queue_row("SYS-001"),
        queue_row("SYS-002", "`ai-channel/../studio/项目/内部/SYS-002/task.md`"),
    )

    assert cs.validate_consistency(studio) == []


def test_review2_real_sibling_index_path_is_still_exempt(tmp_path: Path) -> None:
    studio = sibling_studio(tmp_path)
    write_queue(studio, queue_row("SYS-001"), queue_row("AICH-001", "`ai-channel/tasks/AICH-001/task.md`"))

    assert cs.validate_consistency(studio) == []


# 评审阻塞项 3（Codex）：链接标题、尖括号自动链接、引用式链接不能绕过应用链接限制

APP_URL = "http://github.com/me/studio-tools"


@pytest.mark.parametrize(
    "markdown",
    [
        f'[仓库]({APP_URL} "应用仓库")',
        f"[仓库](<{APP_URL}> '应用仓库')",
        f"见 <{APP_URL}>。",
        f"见 [仓库][ref]。\n\n[ref]: {APP_URL}",
        f'[仓库][ref]\n\n  [ref]: <{APP_URL}> "应用仓库"',
    ],
    ids=["title", "angle-dest-title", "autolink", "reference", "reference-angle-title"],
)
def test_review3_link_syntax_variants_into_app_repo_are_rejected(workspace: Path, markdown: str) -> None:
    (workspace / "page.md").write_text(markdown + "\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == [app_link_error(APP_URL)]


def test_review3_https_variants_are_accepted(workspace: Path) -> None:
    (workspace / "page.md").write_text(
        '[a](https://github.com/me/studio-tools "t")\n<https://github.com/me/studio-tools>\n'
        "[b][r]\n\n[r]: https://github.com/me/studio-tools\n",
        encoding="utf-8",
    )

    assert cs.validate_app_links(workspace) == []


def test_review3_local_link_with_title_is_resolved_without_the_title(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("# t\n", encoding="utf-8")
    (tmp_path / "page.md").write_text('[t](target.md "标题")\n[u](<target.md>)\n', encoding="utf-8")

    assert cs.validate_markdown_links(tmp_path) == []


def test_review3_reference_definition_to_missing_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text("[t][r]\n\n[r]: missing.md\n", encoding="utf-8")

    assert cs.validate_markdown_links(tmp_path) == ["page.md：本地链接不存在：missing.md"]


# 增量复审 N3：脚注定义 [^...]: 与脚注引用 [^1] 不是链接


def test_n3_footnote_definition_is_not_a_link(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text("正文[^1]。\n\n[^1]: 来源见 STATUS.md。\n", encoding="utf-8")

    assert cs.validate_markdown_links(tmp_path) == []


def test_n3_footnote_reference_followed_by_parenthesis_is_not_a_link(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text("见注释[^note](补充说明)。\n\n[^note]: 说明。\n", encoding="utf-8")

    assert cs.validate_markdown_links(tmp_path) == []


def test_n3_footnotes_are_ignored_by_app_link_rule(workspace: Path) -> None:
    (workspace / "page.md").write_text("[^1]: http://github.com/me/studio-tools 旧地址\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == []


# 增量复审 N1：链接文字为空或含方括号（含徽章嵌套链接）时也要提取目标


@pytest.mark.parametrize(
    "markdown",
    [f"[]({APP_URL})", f"[a [b] c]({APP_URL})"],
    ids=["empty-text", "bracketed-text"],
)
def test_n1_link_text_variants_into_app_repo_are_rejected(workspace: Path, markdown: str) -> None:
    (workspace / "page.md").write_text(markdown + "\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == [app_link_error(APP_URL)]


def test_n1_badge_outer_link_into_app_repo_is_rejected(workspace: Path) -> None:
    (workspace / "x.md").write_text("# x\n", encoding="utf-8")
    (workspace / "page.md").write_text(f"[![i](x.md)]({APP_URL})\n", encoding="utf-8")

    assert cs.validate_app_links(workspace) == [app_link_error(APP_URL)]


def test_n1_badge_extracts_outer_and_inner_targets_in_order() -> None:
    assert cs.link_targets(f"[![i](x.md)]({APP_URL})") == [APP_URL, "x.md"]


def test_n1_badge_inner_missing_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text("[![i](x.md)](https://example.com/badge)\n", encoding="utf-8")

    assert cs.validate_markdown_links(tmp_path) == ["page.md：本地链接不存在：x.md"]


def test_n1_empty_text_local_link_is_checked(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text("[](missing.md)\n", encoding="utf-8")

    assert cs.validate_markdown_links(tmp_path) == ["page.md：本地链接不存在：missing.md"]


# 增量复审 N4-a（TOOLS-004）：队列表格中间漏写开头竖线的行不能静默跳过


def row_without_leading_pipe(task_id: str) -> str:
    """正常数据行去掉开头竖线，其余内容不变。"""

    normal = queue_row(task_id)
    assert normal.startswith("|"), normal
    return normal.removeprefix("|").strip()


def missing_pipe_message(line_number: int, row: str) -> str:
    """``queue_line_errors`` 的原始信息（``validate_consistency`` 会再加文件前缀）。"""

    return f"第 {line_number} 行在队列表格中缺少开头竖线：{row}"


def missing_pipe_error(line_number: int, row: str) -> str:
    return f"registry/任务队列.md：{missing_pipe_message(line_number, row)}"


def test_n4a_reports_row_missing_leading_pipe_in_the_middle(tmp_path: Path) -> None:
    """表格中间的漏竖线行要报错，而不是被当成非表格内容跳过。"""

    consistent_studio(tmp_path)
    for task_id in ("SYS-002", "SYS-003"):
        write_task(tmp_path, card(task_id), task_id)
    write_queue(tmp_path, queue_row("SYS-001"), row_without_leading_pipe("SYS-002"), queue_row("SYS-003"))

    assert cs.validate_consistency(tmp_path) == [missing_pipe_error(6, row_without_leading_pipe("SYS-002"))]


def test_n4a_reports_every_row_missing_leading_pipe(tmp_path: Path) -> None:
    consistent_studio(tmp_path)
    write_task(tmp_path, card("SYS-002"), "SYS-002")
    write_queue(tmp_path, row_without_leading_pipe("SYS-001"), row_without_leading_pipe("SYS-002"))

    assert cs.validate_consistency(tmp_path) == [
        missing_pipe_error(5, row_without_leading_pipe("SYS-001")),
        missing_pipe_error(6, row_without_leading_pipe("SYS-002")),
    ]


QUEUE_WITH_PROSE = (
    "# 任务队列\n\n"
    "说明：表格外的正文里出现竖线 A | B 不算表格行。\n\n"
    "| 任务编号 | 项目 | 优先级 | 摘要 | 任务卡 |\n"
    "|---|---|---:|---|---|\n"
    "| `SYS-001` | STUDIO | P1 | 摘要 | [打开](../项目/内部/SYS-001/task.md) |\n"
    "\n"
    "新增任务：从模板复制（正文里同样有竖线 A | B）。\n"
)


def test_n4a_ignores_pipes_outside_the_table(tmp_path: Path) -> None:
    """表格外的正文竖线、以及表格后的说明文字都不产生错误。"""

    consistent_studio(tmp_path)
    (tmp_path / "registry" / "任务队列.md").write_text(QUEUE_WITH_PROSE, encoding="utf-8")

    assert cs.validate_consistency(tmp_path) == []


def test_n4a_full_check_fails_on_row_missing_leading_pipe(tmp_path: Path) -> None:
    for relative in cs.REQUIRED_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# x\n", encoding="utf-8")
    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), row_without_leading_pipe("SYS-001"))

    assert cs.main([str(tmp_path)], today=TODAY) == 1


# 评审阻塞项 1（Codex，CP-003）：表格结束边界——含竖线的块级结构不能算漏竖线的数据行


@pytest.mark.parametrize(
    "line",
    [
        "## 新增任务 A | B",
        "- 列表项 A | B",
        "> 引用 A | B",
        "``` 围栏 A | B",
        "```python 带语言的围栏 A | B",
        "~~~ 波浪线围栏 A | B",
        "<div>HTML 块 A | B</div>",
        "<!-- HTML 注释 A | B -->",
        "<?xml 处理指令 A | B ?>",
        "<!DOCTYPE html> 声明 A | B",
        "<![CDATA[ 数据 A | B ]]>",
        "<pre 原始文本标签 A | B",
        "<source 数据 A | B",
        '<span title="A | B">',
    ],
    ids=[
        "heading",
        "list-item",
        "blockquote",
        "fenced-code",
        "fenced-code-with-info",
        "tilde-fence",
        "html-block-tag",
        "html-comment",
        "html-processing",
        "html-declaration",
        "html-cdata",
        "html-raw-tag",
        "html-block-tag-source",
        "html-complete-tag",
    ],
)
def test_n4a_block_start_with_pipe_ends_the_table(tmp_path: Path, line: str) -> None:
    """紧跟表格的块级结构（即使含竖线）结束表格，不当作漏写开头竖线的数据行。"""

    consistent_studio(tmp_path)
    write_queue(tmp_path, queue_row("SYS-001"), line)

    assert cs.validate_consistency(tmp_path) == []


def test_n4a_block_start_does_not_swallow_the_row_before_it(tmp_path: Path) -> None:
    """块级结构只结束表格：它前面的漏竖线行照样报错，行号不受影响。"""

    consistent_studio(tmp_path)
    write_task(tmp_path, card("SYS-002"), "SYS-002")
    write_queue(tmp_path, queue_row("SYS-001"), row_without_leading_pipe("SYS-002"), "## 新增任务 A | B")

    assert cs.validate_consistency(tmp_path) == [missing_pipe_error(6, row_without_leading_pipe("SYS-002"))]


# 评审 P2（Codex，第二轮）：围栏起始行要合法才算块级结构，否则漏竖线的数据行会被静默跳过


INLINE_CODE_ROW = "```SYS-999``` | STUDIO | P1 | 摘要 | [打开](../项目/内部/SYS-999/task.md) |"


def test_n4a_inline_code_row_is_still_a_queue_row() -> None:
    """首格用三个反引号行内代码的漏竖线行仍按数据行解析（评审 P2：修复后它不能从 queue_rows 消失）。"""

    rows = cs.queue_rows(queue_text(queue_row("SYS-001"), INLINE_CODE_ROW))

    assert rows == [
        ("`SYS-001`", "[打开](../项目/内部/SYS-001/task.md)"),
        ("```SYS-999```", "[打开](../项目/内部/SYS-999/task.md)"),
    ]


def test_n4a_inline_code_row_is_reported(tmp_path: Path) -> None:
    """评审 P2 的整链路复现：三反引号行内代码行要报漏竖线，而不是让整行从检查里消失。"""

    consistent_studio(tmp_path)
    write_task(tmp_path, card("SYS-999"), "SYS-999")
    write_queue(tmp_path, queue_row("SYS-001"), INLINE_CODE_ROW)

    assert cs.validate_consistency(tmp_path) == [missing_pipe_error(6, INLINE_CODE_ROW)]


@pytest.mark.parametrize(
    "line",
    [
        INLINE_CODE_ROW,
        "<SYS-999> | STUDIO | P1 | 摘要 | [打开](../项目/内部/SYS-999/task.md) |",
        "<- 待定 A | B",
        "<search A | B",
    ],
    ids=["inline-code-backticks", "tag-like-with-text-after", "less-than-dash", "block-tag-not-in-gfm"],
)
def test_n4a_block_lookalike_is_reported(line: str) -> None:
    """像 HTML 块或围栏、但按 GFM 不是块级结构起始行的行，仍按漏竖线的数据行报错。"""

    assert cs.queue_line_errors(queue_text(queue_row("SYS-001"), line)) == [missing_pipe_message(6, line)]
