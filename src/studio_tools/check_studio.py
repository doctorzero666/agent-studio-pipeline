"""Validate the Studio directory without external dependencies.

Migrated verbatim from studio/scripts/check_studio.py (studio commit 11a7a32); the entry
point takes the Studio root as a CLI argument. TOOLS-001 added the six checks of 方案 9.3
(ADR 0003); rule 4 (stale claims) only warns and never changes the exit code.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_STUDIO_ROOT = Path("../studio")
REQUIRED_PATHS = (
    "START_HERE.md",
    "AGENTS.md",
    "CLAUDE.md",
    "studio.md",
    "STATUS.md",
    "config/agent与额度策略.md",
    "registry/项目索引.md",
    "registry/任务队列.md",
    "templates/任务与交接模板.md",
    "templates/业务立项与验收模板.md",
    "流程/agent交接.md",
    "流程/内容生产.md",
    "流程/客户交付.md",
    "bin/studio-claude",
    "bin/studio-codex",
    "bin/studio-hermes",
    "项目/内容/README.md",
    "客户项目/README.md",
    "工作室素材/README.md",
)
TASK_HEADINGS = ("## 目标与验收", "## 阅读入口", "## 当前检查点", "## 对外操作与授权")
ALLOWED_STATUSES = {"todo", "doing", "review", "blocked", "done"}
# 链接目标提取：行内链接可带标题（"…"、'…'、(…)）或用尖括号包目标；另识别尖括号自动链接与引用定义。
LINK_TITLE_PATTERN = re.compile(r"""^(<[^>]*>|\S+)\s+("[^"]*"|'[^']*'|\([^)]*\))$""")
AUTOLINK_PATTERN = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*)>")
# 引用定义；``[^...]:`` 是脚注定义，不是链接。
REFERENCE_DEFINITION_PATTERN = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*(<[^>]*>|\S+)", re.MULTILINE)
TASK_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]{3,}$")
STATUS_PATTERN = re.compile(r"^\| 状态 \|\s*`?([a-z]+)`?\s*\|$", re.MULTILINE)
QUEUE_PATH = "registry/任务队列.md"
STATUS_SUMMARY_PATH = "STATUS.md"
STATUS_FOCUS_HEADING = "## 当前重点"
QUEUE_SEPARATOR_PATTERN = re.compile(r"^\|[\s:|-]+\|$")
QUEUE_HEADER_FIRST_CELL = "任务编号"
# N4-a：队列表格的结束边界。表格从第一个以竖线开头的行开始；空行、不含竖线的行，或新的 Markdown 块级结构
# 都结束表格——块级结构行即使含竖线也结束表格，否则紧跟表格的标题会被当成漏写竖线的数据行误报。
# 传入的行已去掉两端空白。这里只认"按 GFM 确实是块级结构起始行"的写法：反引号围栏要校验起始行合法
# （GFM 规定反引号围栏的信息串里不得再有反引号，故写成 `` `{3,}[^`]*$ ``：同一行后面再出现反引号就
# 不是围栏），HTML 块交给 ``ends_queue_table`` 按条件 1～7 判定。
# 判定不了的行一律按漏写竖线的数据行报错，不静默跳过（评审 P2：首格用三个反引号行内代码的漏竖线行
# 曾被当成围栏起始行，于是整行从检查里消失）。
QUEUE_TABLE_END_PATTERN = re.compile(r"^(?:#{1,6}(?:\s|$)|>|[-+*](?:\s|$)|\d{1,9}[.)](?:\s|$)|`{3,}[^`]*$|~{3,})")
# GFM HTML 块起始条件 1：script/pre/style/textarea 后接空白、">" 或行尾。
HTML_RAW_TAG_START_PATTERN = re.compile(r"^<(?:script|pre|style|textarea)(?:[ \t]|>|$)", re.IGNORECASE)
# GFM HTML 块起始条件 2～5：注释、处理指令、声明、CDATA。
HTML_DECLARATION_START_PATTERN = re.compile(r"^(?:<!--|<\?|<![A-Za-z]|<!\[CDATA\[)")
# GFM HTML 块起始条件 6：块级标签名（可带 "/"）后接空白、">"、"/>" 或行尾。清单按 GFM 规范
# （=cmark-gfm，GitHub 实际用的渲染器，含 source、不含较新解析器才收录的 search），已对
# cmark-gfm 逐个标签验证。像 <search A | B 这样的行按数据行报错，不静默跳过。
HTML_BLOCK_TAG_START_PATTERN = re.compile(
    r"^</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|"
    r"dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|"
    r"html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|section|source|"
    r"summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:[ \t]|/?>|$)",
    re.IGNORECASE,
)
# GFM HTML 块起始条件 7：完整开标签或闭标签，其后只有空白（script/pre/style/textarea 由条件 1 覆盖）。
HTML_COMPLETE_TAG_START_PATTERN = re.compile(
    r"^</?[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[A-Za-z_:][A-Za-z0-9:._-]*"
    r"(?:[ \t]*=[ \t]*(?:[^\"'=<>`\s]+|'[^']*'|\"[^\"]*\"))?)*[ \t]*/?>[ \t]*$"
)
INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
# 规则 4：doing 任务的"最后更新时间"距今超过这么多天就报停滞警告（等于阈值不报）。
STALE_CLAIM_DAYS = 3
DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# 规则 3、5：字段值视为"空"：空白，或以"无""未运行"开头且其后是结尾、括号、标点或空白（如"无（CP-011 后释放）"）。
EMPTY_FIELD_PATTERN = re.compile(r"^(?:无|未运行)(?:$|[（(；;，,：:。.\s])")
# 规则 5：这些状态的代码任务必须写明 PR 与 CI 结果；"代码仓库"写作不适用即视为非代码任务。
CODE_REVIEW_STATUSES = ("review", "done")
CODE_RECORD_FIELDS = (("PR", "PR 记录"), ("CI 结果", "CI 结果"))
NOT_APPLICABLE_PATTERN = re.compile(r"^不适用")
# 规则 6：studio 内登记应用项目的目录；其下每个子目录名就是一个平级应用仓库名。
APP_PROJECTS_DIR = "项目/应用"


def markdown_files(root: Path) -> list[Path]:
    """Return checked Markdown files in a stable order."""

    return sorted(path for path in root.rglob("*.md") if ".git" not in path.parts)


def validate_required_paths(root: Path) -> list[str]:
    """Report required Studio files and directories that are missing."""

    return [f"缺少必要路径：{relative}" for relative in REQUIRED_PATHS if not (root / relative).exists()]


def matching_bracket(content: str, open_index: int, opener: str, closer: str) -> int | None:
    """Index of the bracket closing ``content[open_index]``, honouring nesting and backslash escapes.

    不跨越空行（Markdown 的段落边界）；找不到时返回 ``None``。
    """

    depth = 0
    index = open_index
    while index < len(content):
        char = content[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n" and content.startswith("\n\n", index):
            return None
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def inline_links(content: str) -> list[tuple[int, int, str]]:
    """Return ``(start, end, raw destination)`` of every inline link ``[文字](目标)``, nested ones included.

    链接文字可以为空或含成对方括号（``[a [b] c](目标)``）；徽章 ``[![i](图)](目标)`` 的外层与内层
    都会返回。以 ``[^`` 开头的是脚注引用，不算链接。
    """

    links: list[tuple[int, int, str]] = []
    for start, char in enumerate(content):
        if char != "[" or (start > 0 and content[start - 1] == "\\") or content.startswith("[^", start):
            continue
        close = matching_bracket(content, start, "[", "]")
        if close is None or not content.startswith("(", close + 1):
            continue
        end = matching_bracket(content, close + 1, "(", ")")
        if end is not None:
            links.append((start, end + 1, content[close + 2 : end]))
    return links


def link_targets(content: str) -> list[str]:
    """Return link destinations in document order, with titles and angle brackets removed.

    覆盖三种写法：行内链接 ``[x](目标 "标题")`` / ``[x](<目标>)``；尖括号自动链接
    ``<scheme:...>``；引用定义 ``[ref]: 目标 "标题"``（引用 ``[x][ref]`` 的目标就在定义里）。
    """

    found: list[tuple[int, str]] = []
    # 已被行内链接或引用定义覆盖的区间；其中的 <...> 是目标本身，不再按自动链接重复计入。
    covered: list[tuple[int, int]] = []
    for start, end, raw_destination in inline_links(content):
        covered.append((start, end))
        destination = raw_destination.strip()
        titled = LINK_TITLE_PATTERN.match(destination)
        if titled:
            destination = titled.group(1)
        found.append((start, destination.strip("<>")))
    for match in REFERENCE_DEFINITION_PATTERN.finditer(content):
        covered.append(match.span())
        found.append((match.start(), match.group(1).strip("<>")))
    for match in AUTOLINK_PATTERN.finditer(content):
        if not any(start <= match.start() < end for start, end in covered):
            found.append((match.start(), match.group(1)))
    return [target for _, target in sorted(found, key=lambda item: item[0])]


def validate_markdown_links(root: Path) -> list[str]:
    """Report broken relative links in Markdown files."""

    errors: list[str] = []
    for path in markdown_files(root):
        content = path.read_text(encoding="utf-8")
        for raw_target in link_targets(content):
            target = raw_target.strip().strip("<>")
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            file_target = unquote(target.split("#", maxsplit=1)[0])
            if not file_target:
                continue
            resolved = (path.parent / file_target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(root)}：链接越出 studio：{raw_target}")
                continue
            if not resolved.exists():
                errors.append(f"{path.relative_to(root)}：本地链接不存在：{raw_target}")
    return errors


def app_repo_names(root: Path) -> set[str]:
    """Names of sibling application repositories, one per directory under ``项目/应用/``."""

    projects = root / APP_PROJECTS_DIR
    if not projects.is_dir():
        return set()
    return {entry.name for entry in projects.iterdir() if entry.is_dir()}


def validate_app_links(root: Path) -> list[str]:
    """Rule 6: links into an application repository must be inline code paths or https links.

    应用仓库与 studio 平级（方案 B），目录名与 ``项目/应用/<app>/`` 相同。以下 Markdown 链接视为
    指向应用仓库并报错：``http://`` 或 ``file://`` 链接的路径中含应用仓库名；本地相对或绝对路径
    解析后落在 studio 外、且路径中含应用仓库名。studio 内的 ``项目/应用/<app>/...`` 是项目目录，不受影响。
    """

    apps = app_repo_names(root)
    if not apps:
        return []
    studio = root.resolve()
    errors: list[str] = []
    for path in markdown_files(root):
        content = path.read_text(encoding="utf-8")
        for raw_target in link_targets(content):
            target = raw_target.strip().strip("<>")
            if target.startswith(("https://", "mailto:", "#")):
                continue
            if target.startswith(("http://", "file://")):
                parsed = urlparse(target)
                parts: tuple[str, ...] = (parsed.netloc, *unquote(parsed.path).split("/"))
            else:
                file_target = unquote(target.split("#", maxsplit=1)[0])
                if not file_target:
                    continue
                resolved = (path.parent / file_target).resolve()
                if resolved.is_relative_to(studio):
                    continue
                parts = resolved.parts
            normalized_parts = {part.lower() for part in parts}
            hits = sorted(app for app in apps if app.lower() in normalized_parts)
            if hits:
                label = path.relative_to(root)
                errors.append(f"{label}：指向应用仓库 {hits[0]} 的链接须改为行内代码路径或 https 链接：{raw_target}")
    return errors


def validate_task(path: Path, root: Path) -> list[str]:
    """Validate one live task file."""

    errors: list[str] = []
    content = path.read_text(encoding="utf-8")
    task_id = path.parent.name
    label = str(path.relative_to(root))

    if not TASK_ID_PATTERN.fullmatch(task_id):
        errors.append(f"{label}：任务目录编号格式错误：{task_id}")
    if f"| 任务编号 | `{task_id}` |" not in content:
        errors.append(f"{label}：任务卡编号与目录不一致")
    for heading in TASK_HEADINGS:
        # 规则 1（方案 9.3）：按整行匹配，`### 目标与验收` 或带后缀的标题不算数；只容忍行尾空白。
        if re.search(rf"^{re.escape(heading)}[ \t]*$", content, re.MULTILINE) is None:
            errors.append(f"{label}：缺少章节：{heading}")

    status_match = STATUS_PATTERN.search(content)
    if status_match is None:
        errors.append(f"{label}：缺少可解析的状态字段")
    elif status_match.group(1) not in ALLOWED_STATUSES:
        errors.append(f"{label}：未知状态：{status_match.group(1)}")
    status = status_match.group(1) if status_match else None

    # 规则 3（方案 9.3）：进行中的任务必须有人认领。
    if status == "doing" and is_empty_field(task_field(content, "当前执行者")):
        errors.append(f"{label}：状态为 doing 但当前执行者为空")

    # 规则 5（方案 9.3）：进入评审或完成的代码任务要有可核对的 PR 与 CI 记录。
    if status in CODE_REVIEW_STATUSES and is_code_task(content):
        for field, description in CODE_RECORD_FIELDS:
            if is_empty_field(task_field(content, field)):
                errors.append(f"{label}：状态为 {status} 的代码任务缺少 {description}")
    return errors


def is_code_task(content: str) -> bool:
    """A task is a code task when its 代码仓库 field names a repository (not empty, not 不适用)."""

    repo = task_field(content, "代码仓库")
    return not is_empty_field(repo) and NOT_APPLICABLE_PATTERN.match((repo or "").strip("`")) is None


def task_field(content: str, name: str) -> str | None:
    """Return the value of ``| name | value |`` in a task card, or ``None`` when the row is absent."""

    match = re.search(rf"^\| {re.escape(name)} \|(.*)\|[ \t]*$", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def is_empty_field(value: str | None) -> bool:
    """True when a field is absent, blank, or written as 无／未运行 (optionally followed by a note)."""

    if value is None:
        return True
    text = value.strip().strip("`").strip()
    return not text or EMPTY_FIELD_PATTERN.match(text) is not None


def task_paths(root: Path) -> list[Path]:
    """Return live task cards in the same order ``validate_tasks`` checks them."""

    return sorted((root / "项目").glob("**/task.md")) + sorted((root / "客户项目").glob("**/task.md"))


def task_status(content: str) -> str | None:
    """Return the parsed status of a task card, or ``None`` when absent."""

    match = STATUS_PATTERN.search(content)
    return match.group(1) if match else None


def external_index_path(card_cell: str, root: Path) -> str | None:
    """Return the outside path when a queue row is an index row pointing outside studio.

    识别方式（规则 2 的放行条件）：任务卡一列没有 Markdown 链接，只有行内代码路径，
    路径以 ``/task.md`` 结尾，第一段不是 studio 顶层已有的目录或文件，并且把它当作平级仓库
    路径（相对 studio 的上级目录）规范化后确实落在 studio 之外（例如
    ``ai-channel/tasks/AICH-001/task.md``）。这样的行是"任务在别的仓库自管"的索引，
    studio 内不应再有同编号的 task.md。写成 ``项目/...`` 或经 ``..`` 绕回 studio 的路径
    （如 ``ai-channel/../studio/项目/...``）仍按 studio 内任务核对。
    """

    if inline_links(card_cell):
        return None
    studio = root.resolve()
    for candidate in INLINE_CODE_PATTERN.findall(card_cell):
        parts = Path(candidate).parts
        if len(parts) < 2 or parts[-1] != "task.md" or (root / parts[0]).exists():
            continue
        if (studio.parent / candidate).resolve().is_relative_to(studio):
            continue
        return candidate
    return None


def ends_queue_table(text: str) -> bool:
    """判断这一行是否是结束队列表格的 Markdown 块级结构起始行。

    标题、引用、列表项与围栏代码见 ``QUEUE_TABLE_END_PATTERN``（反引号围栏会校验起始行是否合法）；
    HTML 块按 GFM 的起始条件 1～7 判定（原始文本标签、注释、处理指令、声明、CDATA、块级标签名、
    完整标签独占一行）。像块级结构、但按 GFM 不是块级结构起始行的行返回 ``False``，
    由 ``queue_line_errors`` 按漏写开头竖线的数据行报错，不静默跳过。
    """

    return bool(
        QUEUE_TABLE_END_PATTERN.match(text)
        or HTML_RAW_TAG_START_PATTERN.match(text)
        or HTML_DECLARATION_START_PATTERN.match(text)
        or HTML_BLOCK_TAG_START_PATTERN.match(text)
        or HTML_COMPLETE_TAG_START_PATTERN.match(text)
    )


def queue_table_lines(content: str) -> list[tuple[int, str]]:
    """Return ``(行号, 取掉两端空白后的原文)`` of every line that belongs to a queue table.

    表格从第一个以 ``|`` 开头的行开始；空行、既不以 ``|`` 开头也不含 ``|`` 的行，或新的 Markdown
    块级结构（见 ``ends_queue_table``：标题、引用、列表项、围栏代码、HTML 块）结束表格——
    块级结构行即使含竖线也结束表格（评审阻塞项 1：紧跟表格的标题不是漏写竖线的数据行）。
    表格内漏写开头竖线的行（不以 ``|`` 开头却含 ``|``）仍算表格行，照样产出，交给调用方报错，
    不静默跳过（N4-a）。表格外的正文里出现竖线不算表格行。
    """

    lines: list[tuple[int, str]] = []
    in_table = False
    for number, line in enumerate(content.splitlines(), start=1):
        text = line.strip()
        if text.startswith("|"):
            in_table = True
        elif not in_table or "|" not in text or ends_queue_table(text):
            in_table = False
            continue
        lines.append((number, text))
    return lines


def queue_rows(content: str) -> list[tuple[str, str]]:
    """Return ``(first cell, last cell)`` for every data row of the queue tables.

    每个队列表格行都算数（编号写不写反引号、有没有开头竖线都一样），只跳过分隔行和首列为
    "任务编号"的表头行；首列无法识别为任务编号时由调用方报格式错误，不静默跳过。漏写开头竖线的
    行仍按数据行解析（它对应的任务卡照样核对），另行由 ``queue_line_errors`` 报错（N4-a）。
    """

    rows: list[tuple[str, str]] = []
    for _, text in queue_table_lines(content):
        if QUEUE_SEPARATOR_PATTERN.fullmatch(text):
            continue
        cells = [cell.strip() for cell in text.strip("|").split("|")]
        if cells[0] == QUEUE_HEADER_FIRST_CELL:
            continue
        rows.append((cells[0], cells[-1]))
    return rows


def queue_line_errors(content: str) -> list[str]:
    """返回每一行"在队列表格中间漏写开头竖线"的行的错误信息（N4-a）。

    这样的行 Markdown 仍可能渲染成表格行；报错之外，它仍按数据行解析（见 ``queue_rows``），
    所以不会再被静默跳过。信息含行号与原文，原文首格即该行的任务编号。
    """

    return [
        f"第 {number} 行在队列表格中缺少开头竖线：{text}"
        for number, text in queue_table_lines(content)
        if not text.startswith("|")
    ]


def validate_consistency(root: Path) -> list[str]:
    """Rule 2: the queue, STATUS focus and live task cards must agree.

    - 队列里每个任务编号都能找到 studio 内的 task.md（指向 studio 外的索引行除外）；
    - 每张 studio 任务卡都登记在队列里；
    - STATUS.md "当前重点"一节里的任务编号（行内代码写法）存在且不是 ``done``。
    文件缺失由 ``validate_required_paths`` 报告，这里跳过对应部分。
    """

    errors: list[str] = []
    cards: dict[str, Path] = {}
    for path in task_paths(root):
        cards.setdefault(path.parent.name, path)

    queue_path = root / QUEUE_PATH
    external: set[str] = set()
    if queue_path.is_file():
        queued: set[str] = set()
        queue_text = queue_path.read_text(encoding="utf-8")
        errors.extend(f"{QUEUE_PATH}：{message}" for message in queue_line_errors(queue_text))
        for first_cell, card_cell in queue_rows(queue_text):
            task_id = first_cell.strip("`").strip()
            if not TASK_ID_PATTERN.fullmatch(task_id):
                errors.append(f"{QUEUE_PATH}：队列行的任务编号格式无法识别：{first_cell}")
                continue
            queued.add(task_id)
            outside = external_index_path(card_cell, root)
            if outside is not None:
                external.add(task_id)
                if task_id in cards:
                    errors.append(
                        f"{QUEUE_PATH}：{task_id} 是指向 studio 外的索引行，但 studio 内仍有任务卡："
                        f"{cards[task_id].relative_to(root)}"
                    )
            elif task_id not in cards:
                errors.append(f"{QUEUE_PATH}：{task_id} 找不到对应的 task.md")
        for task_id, path in cards.items():
            if task_id not in queued:
                errors.append(f"{path.relative_to(root)}：任务未登记到任务队列：{task_id}")

    status_path = root / STATUS_SUMMARY_PATH
    if status_path.is_file():
        focus = markdown_section(status_path.read_text(encoding="utf-8"), STATUS_FOCUS_HEADING)
        if focus is None:
            errors.append(f"{STATUS_SUMMARY_PATH}：缺少章节：{STATUS_FOCUS_HEADING}")
        else:
            focus_ids = [code for code in INLINE_CODE_PATTERN.findall(focus) if TASK_ID_PATTERN.fullmatch(code)]
            if not focus_ids:
                errors.append(f"{STATUS_SUMMARY_PATH}：当前重点没有指向任何任务编号")
            for task_id in dict.fromkeys(focus_ids):
                if task_id in cards:
                    if task_status(cards[task_id].read_text(encoding="utf-8")) == "done":
                        errors.append(f"{STATUS_SUMMARY_PATH}：当前重点指向已完成的任务：{task_id}")
                elif task_id not in external:
                    errors.append(f"{STATUS_SUMMARY_PATH}：当前重点指向的任务不存在：{task_id}")
    return errors


def markdown_section(content: str, heading: str) -> str | None:
    """Return the body under an exact ``heading`` line up to the next heading of the same or higher level."""

    level = len(heading) - len(heading.lstrip("#"))
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() == heading:
            body: list[str] = []
            for following in lines[index + 1 :]:
                marks = len(following) - len(following.lstrip("#"))
                if 0 < marks <= level and following[marks : marks + 1] == " ":
                    break
                body.append(following)
            return "\n".join(body)
    return None


def stale_claim_warning(path: Path, root: Path, today: date) -> str | None:
    """Rule 4: warn when a ``doing`` card has not been updated for more than ``STALE_CLAIM_DAYS`` days."""

    content = path.read_text(encoding="utf-8")
    if task_status(content) != "doing":
        return None
    label = str(path.relative_to(root))
    updated = task_field(content, "最后更新时间") or ""
    match = DATE_PATTERN.search(updated)
    try:
        last = date(int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None
    except ValueError:
        last = None
    if last is None:
        return f"{label}：doing 任务的最后更新时间无法解析：{updated}"
    days = (today - last).days
    if days > STALE_CLAIM_DAYS:
        return (
            f"{label}：doing 已 {days} 天未更新（最后更新时间 {last.isoformat()}，"
            f"阈值 {STALE_CLAIM_DAYS} 天），请核实认领是否仍有效"
        )
    return None


def collect_warnings(root: Path, today: date | None = None) -> list[str]:
    """Run checks that only warn and never change the exit code (currently rule 4)."""

    current = today or date.today()
    warnings = [stale_claim_warning(path, root, current) for path in task_paths(root)]
    return [warning for warning in warnings if warning is not None]


def validate_tasks(root: Path) -> list[str]:
    """Validate every live task and reject duplicate task IDs."""

    errors: list[str] = []
    seen: dict[str, Path] = {}
    paths = task_paths(root)

    for path in paths:
        task_id = path.parent.name
        if task_id in seen:
            errors.append(f"重复任务编号 {task_id}：{seen[task_id].relative_to(root)} 与 {path.relative_to(root)}")
        else:
            seen[task_id] = path
        errors.extend(validate_task(path, root))
    if not paths:
        errors.append("没有找到任何实时任务卡")
    return errors


def run_checks(root: Path) -> list[str]:
    """Run all deterministic Studio checks."""

    errors: list[str] = []
    errors.extend(validate_required_paths(root))
    errors.extend(validate_markdown_links(root))
    errors.extend(validate_app_links(root))
    errors.extend(validate_tasks(root))
    errors.extend(validate_consistency(root))
    return errors


def main(argv: list[str] | None = None, today: date | None = None) -> int:
    """CLI entry point: ``studio-check [studio目录]`` (default ``../studio``).

    警告（停滞认领）先以 "Studio 检查警告：" 块写到 stderr，不影响退出码；``today`` 仅供测试注入。
    """

    parser = argparse.ArgumentParser(prog="studio-check", description="校验 studio 目录结构、链接与任务卡。")
    parser.add_argument(
        "studio_root",
        nargs="?",
        default=str(DEFAULT_STUDIO_ROOT),
        help="studio 目录路径，默认 ../studio",
    )
    args = parser.parse_args(argv)
    studio_root = Path(args.studio_root).resolve()

    warnings = collect_warnings(studio_root, today)
    if warnings:
        print("Studio 检查警告：", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)

    errors = run_checks(studio_root)
    if errors:
        print("Studio 检查失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    markdown_count = len(markdown_files(studio_root))
    task_count = len(list((studio_root / "项目").glob("**/task.md"))) + len(
        list((studio_root / "客户项目").glob("**/task.md"))
    )
    print(f"Studio 检查通过：{markdown_count} 个 Markdown 文件，{task_count} 个实时任务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
