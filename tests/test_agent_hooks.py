"""Codex CLI 与 Hermes Agent 复用 guard_bash.py 的接入测试（TOOLS-008）。

每个测试函数名都含 ``codex`` 或 ``hermes``，便于 ``pytest -k codex`` / ``-k hermes`` 分别选中。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / ".claude" / "hooks" / "guard_bash.py"
CODEX_HOOKS = REPO / ".codex" / "hooks.json"
AGENT_HOOKS_DIR = REPO / "scripts" / "agent-hooks"
HERMES_SNIPPET = AGENT_HOOKS_DIR / "hermes-hooks.yaml"
HERMES_ALLOWLIST = AGENT_HOOKS_DIR / "hermes-shell-hooks-allowlist.json"
GUARD_TAG = "[studio-tools guard]"

BLOCKED = [
    "git push origin main",
    "git push origin HEAD:master",
    "gh pr merge 12 --squash",
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "bash -c 'git push origin main'",
]
ALLOWED = [
    "git status",
    "git push origin agent/codex/TOOLS-008",
    "git log main",
    "gh pr view 1",
    "just check",
]


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def isolated_env(tmp_path: Path) -> dict[str, str]:
    """不让 git 向上找到 tmp_path 之外的仓库。"""

    return {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)}


def make_repo(tmp_path: Path, name: str, branch: str, with_guard: bool = False) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", branch)
    if with_guard:
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        shutil.copy2(GUARD, hooks / "guard_bash.py")
    return repo


@pytest.fixture
def feature_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path, "feature", "agent/codex/TOOLS-008")


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path, "mainrepo", "main")


def codex_payload(command: object, cwd: Path) -> dict:
    """Codex CLI PreToolUse 的 stdin 字段（shell 与 unified exec 都以 Bash 名义出现）。"""

    return {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "transcript_path": None,
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "model": "gpt-5-codex",
        "permission_mode": "default",
        "turn_id": "turn-1",
        "tool_name": "Bash",
        "tool_use_id": "call-1",
        "tool_input": {"command": command},
    }


def hermes_payload(command: object, cwd: Path, workdir: Path | None = None) -> dict:
    """Hermes pre_tool_call shell hook 的 stdin 字段（terminal 工具）。"""

    tool_input: dict = {"command": command, "background": False, "timeout": 180}
    if workdir is not None:
        tool_input["workdir"] = str(workdir)
    return {
        "hook_event_name": "pre_tool_call",
        "tool_name": "terminal",
        "tool_input": tool_input,
        "session_id": "20260930_000000_abcdef",
        "cwd": str(cwd),
        "profile": "default",
        "extra": {"task_id": "t-1", "tool_call_id": "call-1"},
    }


def run_guard(payload: dict, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
        check=False,
    )


def load_guard_module():
    spec = importlib.util.spec_from_file_location("guard_bash_under_test", GUARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def codex_hook() -> dict:
    config = json.loads(CODEX_HOOKS.read_text(encoding="utf-8"))
    groups = config["hooks"]["PreToolUse"]
    assert len(groups) == 1
    assert len(groups[0]["hooks"]) == 1
    return {"matcher": groups[0]["matcher"], **groups[0]["hooks"][0]}


def hermes_snippet_command() -> str:
    """取 YAML 片段里 command 的双引号串；YAML 双引号串的转义在这里与 JSON 相同。"""

    text = HERMES_SNIPPET.read_text(encoding="utf-8")
    matches = re.findall(r'^\s+command: (".*")\s*$', text, re.M)
    assert len(matches) == 1, matches
    return json.loads(matches[0])


# ---- 直接喂 guard_bash.py：Codex 负载 ----


@pytest.mark.parametrize("command", BLOCKED)
def test_codex_payload_blocked(command: str, feature_repo: Path) -> None:
    result = run_guard(codex_payload(command, feature_repo), feature_repo)
    assert result.returncode == 2, result
    assert GUARD_TAG in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("command", ALLOWED)
def test_codex_payload_allowed(command: str, feature_repo: Path) -> None:
    result = run_guard(codex_payload(command, feature_repo), feature_repo)
    assert result.returncode == 0, result
    assert result.stdout == "" and result.stderr == ""


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["git", "push", "origin", "main"], 2),
        (["bash", "-c", "git push origin main"], 2),
        (["git", "commit", "--no-verify", "-m", "x"], 2),
        (["git", "push", "origin", "agent/codex/TOOLS-008"], 0),
        (["git", "status"], 0),
    ],
)
def test_codex_payload_command_as_list(argv: list[str], code: int, feature_repo: Path) -> None:
    assert run_guard(codex_payload(argv, feature_repo), feature_repo).returncode == code


@pytest.mark.parametrize("command", [["bash", "-lc", "git push origin main"], "bash -lc 'git push origin main'"])
def test_codex_bash_lc_wrapper_blocked(command: object, feature_repo: Path) -> None:
    """Codex 的 shell 命令常以 bash -lc '<cmd>' 出现，包裹内的命令要展开检查。"""

    result = run_guard(codex_payload(command, feature_repo), feature_repo)
    assert result.returncode == 2, result
    assert GUARD_TAG in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        ["bash", "-l", "-c", "git push origin main"],
        ["bash", "--login", "-c", "gh pr merge 1"],
        ["bash", "-o", "pipefail", "-c", "git push origin main"],
        ["zsh", "-ic", "git commit -n -m x"],
        ["sh", "-ec", "git push origin HEAD:master"],
        "/bin/bash -xc 'git push --all origin'",
    ],
)
def test_codex_shell_option_clusters_blocked(command: object, feature_repo: Path) -> None:
    assert run_guard(codex_payload(command, feature_repo), feature_repo).returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        ["bash", "-lc", "git status"],
        "bash -lc 'git push origin agent/codex/TOOLS-008'",
        ["zsh", "-ic", "just check"],
        ["bash", "-l", "script.sh", "-c", "git push origin main"],
    ],
)
def test_codex_shell_option_clusters_allowed(command: object, feature_repo: Path) -> None:
    assert run_guard(codex_payload(command, feature_repo), feature_repo).returncode == 0


def test_codex_bare_push_on_main_blocked(main_repo: Path) -> None:
    assert run_guard(codex_payload("git push", main_repo), main_repo).returncode == 2


def test_codex_other_tool_names_allowed(feature_repo: Path) -> None:
    payload = codex_payload("git push origin main", feature_repo)
    payload["tool_name"] = "apply_patch"
    assert run_guard(payload, feature_repo).returncode == 0


def test_codex_missing_tool_name_defaults_to_bash(feature_repo: Path) -> None:
    payload = codex_payload("git push origin main", feature_repo)
    del payload["tool_name"]
    assert run_guard(payload, feature_repo).returncode == 2


# ---- 直接喂 guard_bash.py：Hermes 负载 ----


@pytest.mark.parametrize("command", BLOCKED)
def test_hermes_payload_blocked(command: str, feature_repo: Path) -> None:
    result = run_guard(hermes_payload(command, feature_repo), feature_repo)
    assert result.returncode == 2, result
    assert GUARD_TAG in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("command", ALLOWED)
def test_hermes_payload_allowed(command: str, feature_repo: Path) -> None:
    result = run_guard(hermes_payload(command, feature_repo), feature_repo)
    assert result.returncode == 0, result
    assert result.stdout == "" and result.stderr == ""


def test_hermes_payload_command_as_list(feature_repo: Path) -> None:
    assert run_guard(hermes_payload(["git", "push", "origin", "main"], feature_repo), feature_repo).returncode == 2
    assert run_guard(hermes_payload(["git", "status"], feature_repo), feature_repo).returncode == 0


def test_hermes_workdir_on_main_blocks_bare_push(feature_repo: Path, main_repo: Path) -> None:
    """Hermes 进程 cwd 在任务分支，但 terminal 的 workdir 指向 main 分支仓库：按 workdir 判定。"""

    result = run_guard(hermes_payload("git push", feature_repo, workdir=main_repo), feature_repo)
    assert result.returncode == 2, result
    assert "当前分支是 main/master" in result.stderr


def test_hermes_workdir_on_feature_allows_bare_push(feature_repo: Path, main_repo: Path) -> None:
    result = run_guard(hermes_payload("git push", main_repo, workdir=feature_repo), main_repo)
    assert result.returncode == 0, result


def test_hermes_without_workdir_uses_payload_cwd(main_repo: Path) -> None:
    assert run_guard(hermes_payload("git push", main_repo), main_repo).returncode == 2


def test_hermes_other_tool_names_allowed(feature_repo: Path) -> None:
    payload = hermes_payload("git push origin main", feature_repo)
    payload["tool_name"] = "execute_code"
    assert run_guard(payload, feature_repo).returncode == 0


# ---- 适配函数单元测试 ----


def test_codex_hermes_command_from_input() -> None:
    guard = load_guard_module()
    assert guard.command_from_input({"command": "git status"}) == "git status"
    assert guard.command_from_input({"command": ["git", "commit", "-m", "a b"]}) == "git commit -m 'a b'"
    assert guard.command_from_input({"command": None}) == ""
    assert guard.command_from_input({}) == ""
    assert guard.command_from_input(None) == ""
    assert guard.command_from_input({"command": 3}) == ""


def test_hermes_cwd_from_payload() -> None:
    guard = load_guard_module()
    assert guard.cwd_from_payload({"cwd": "/a", "tool_input": {"workdir": "/b"}}) == "/b"
    assert guard.cwd_from_payload({"cwd": "/a", "tool_input": {"workdir": "sub"}}) == "/a/sub"
    assert guard.cwd_from_payload({"cwd": "/a", "tool_input": {"workdir": ""}}) == "/a"
    assert guard.cwd_from_payload({"cwd": "/a", "tool_input": {"command": "x"}}) == "/a"
    assert guard.cwd_from_payload({"tool_input": {"workdir": "/b"}}) == "/b"
    assert guard.cwd_from_payload({"tool_input": None}) is None


def test_codex_hermes_shell_tool_names() -> None:
    assert load_guard_module().SHELL_TOOL_NAMES == {"Bash", "terminal"}


def test_codex_hermes_non_dict_payload_allowed(feature_repo: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GUARD)], input="[1, 2]", capture_output=True, text=True, cwd=feature_repo, check=False
    )
    assert result.returncode == 0


# ---- 配置端到端：Codex（hooks.json 的 command 经 shell 执行，cwd 为会话 cwd） ----


def run_codex_hook(command: str, payload: dict, cwd: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "-c", command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=isolated_env(tmp_path),
        timeout=60,
        check=False,
    )


def test_codex_hooks_json_shape() -> None:
    hook = codex_hook()
    assert hook["matcher"] == "^Bash$"
    assert re.fullmatch(hook["matcher"], "Bash")
    assert not re.fullmatch(hook["matcher"], "apply_patch")
    assert hook["type"] == "command"
    assert isinstance(hook["timeout"], int) and hook["timeout"] > 0
    assert ".claude/hooks/guard_bash.py" in hook["command"]
    assert hook["command"].rstrip().endswith("exit 0")


@pytest.mark.parametrize("command", BLOCKED)
def test_codex_config_blocks_in_guarded_repo(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "guarded", "agent/codex/TOOLS-008", with_guard=True)
    result = run_codex_hook(codex_hook()["command"], codex_payload(command, repo), repo, tmp_path)
    assert result.returncode == 2, result
    assert GUARD_TAG in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_codex_config_allows_in_guarded_repo(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "guarded", "agent/codex/TOOLS-008", with_guard=True)
    result = run_codex_hook(codex_hook()["command"], codex_payload(command, repo), repo, tmp_path)
    assert result.returncode == 0, result


def test_codex_config_from_subdirectory(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "guarded", "agent/codex/TOOLS-008", with_guard=True)
    sub = repo / "src" / "pkg"
    sub.mkdir(parents=True)
    result = run_codex_hook(codex_hook()["command"], codex_payload("git push origin main", sub), sub, tmp_path)
    assert result.returncode == 2, result


@pytest.mark.parametrize("command", ["git push origin main", "gh pr merge 1", "git status"])
def test_codex_config_passes_without_guard(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "plain", "main")
    result = run_codex_hook(codex_hook()["command"], codex_payload(command, repo), repo, tmp_path)
    assert result.returncode == 0, result


@pytest.mark.parametrize("command", ["git push origin main", "gh pr merge 1", "git status"])
def test_codex_config_passes_outside_git(command: str, tmp_path: Path) -> None:
    folder = tmp_path / "not-a-repo"
    folder.mkdir()
    result = run_codex_hook(codex_hook()["command"], codex_payload(command, folder), folder, tmp_path)
    assert result.returncode == 0, result


# ---- 配置端到端：Hermes（shlex.split 后 shell=False 执行，cwd 为 Hermes 进程 cwd） ----


def run_hermes_hook(command: str, payload: dict, cwd: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    installed = tmp_path / "trusted hook installation"
    installed.mkdir(exist_ok=True)
    shutil.copy2(GUARD, installed / "guard_bash.py")
    shutil.copy2(AGENT_HOOKS_DIR / "hermes_dispatch.py", installed / "hermes_dispatch.py")
    command = command.replace("__STUDIO_HOOK_DIR__", str(installed))
    return subprocess.run(
        shlex.split(command),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=isolated_env(tmp_path),
        shell=False,
        timeout=60,
        check=False,
    )


def test_hermes_snippet_shape() -> None:
    text = HERMES_SNIPPET.read_text(encoding="utf-8")
    assert re.search(r"^hooks:\s*$", text, re.M)
    assert re.search(r"^  pre_tool_call:\s*$", text, re.M)
    assert re.search(r'^    - matcher: "terminal"\s*$', text, re.M)
    assert re.search(r"^      fail_closed: true\s*$", text, re.M)
    assert re.search(r"^      timeout: \d+\s*$", text, re.M)
    command = hermes_snippet_command()
    assert shlex.split(command)[:2] == ["python3", "-I"]
    assert "__STUDIO_HOOK_DIR__/guard_bash.py" in command


def test_hermes_allowlist_matches_snippet() -> None:
    allowlist = json.loads(HERMES_ALLOWLIST.read_text(encoding="utf-8"))
    assert allowlist == {"approvals": [{"event": "pre_tool_call", "command": hermes_snippet_command()}]}


def test_codex_hermes_dispatch_uses_reviewed_guard() -> None:
    """Hermes 调用固定安装副本；安装内容来自同一个版本化守卫。"""
    assert shlex.split(hermes_snippet_command())[-1] == "__STUDIO_HOOK_DIR__/guard_bash.py"
    assert "git rev-parse" not in hermes_snippet_command()


@pytest.mark.parametrize("command", BLOCKED)
def test_hermes_config_blocks_in_guarded_repo(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "guarded", "agent/hermes/TOOLS-008", with_guard=True)
    result = run_hermes_hook(hermes_snippet_command(), hermes_payload(command, repo), repo, tmp_path)
    assert result.returncode == 2, result
    assert GUARD_TAG in result.stderr
    assert result.stdout == ""  # Hermes 在 exit 2 时优先解析 stdout，必须保持为空


@pytest.mark.parametrize("command", ALLOWED)
def test_hermes_config_allows_in_guarded_repo(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "guarded", "agent/hermes/TOOLS-008", with_guard=True)
    result = run_hermes_hook(hermes_snippet_command(), hermes_payload(command, repo), repo, tmp_path)
    assert result.returncode == 0, result
    assert result.stdout == ""  # fail_closed 下非空且非 JSON 的 stdout 会被当成阻断


def test_hermes_config_workdir_on_main(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "guarded", "agent/hermes/TOOLS-008", with_guard=True)
    other = make_repo(tmp_path, "other", "main")
    result = run_hermes_hook(hermes_snippet_command(), hermes_payload("git push", repo, workdir=other), repo, tmp_path)
    assert result.returncode == 2, result


@pytest.mark.parametrize("command", ["git push origin main", "gh pr merge 1", "git status"])
def test_hermes_config_passes_without_guard(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "plain", "main")
    result = run_hermes_hook(hermes_snippet_command(), hermes_payload(command, repo), repo, tmp_path)
    assert result.returncode == 0, result
    assert result.stdout == ""


@pytest.mark.parametrize("command", ["git push origin main", "gh pr merge 1", "git status"])
def test_hermes_config_passes_outside_git(command: str, tmp_path: Path) -> None:
    folder = tmp_path / "not-a-repo"
    folder.mkdir()
    result = run_hermes_hook(hermes_snippet_command(), hermes_payload(command, folder), folder, tmp_path)
    assert result.returncode == 0, result
    assert result.stdout == ""


# ---- 规则单一来源 ----

RULE_MARKERS = ["PROTECTED = ", r"--no-verify\b", '"merge"]', "-[a-zA-Z]*n[a-zA-Z]*", '"--all", "--mirror"']
SKIP_DIRS = {"tests", ".venv", "node_modules", ".git", "worktrees", "__pycache__", ".pytest_cache", ".ruff_cache"}


def repo_python_files() -> list[Path]:
    files = []
    for root, dirs, names in os.walk(REPO):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        files.extend(Path(root) / name for name in names if name.endswith(".py"))
    assert GUARD in files
    return files


@pytest.mark.parametrize("marker", RULE_MARKERS)
def test_codex_hermes_rules_single_source(marker: str) -> None:
    generated = REPO / "src/studio_tools/templates/application/.claude/hooks/guard_bash.py"
    if generated.exists():
        assert generated.read_bytes() == GUARD.read_bytes(), "packaged guard differs from authoritative source"
    holders = [
        path.relative_to(REPO).as_posix()
        for path in repo_python_files()
        if path != generated and marker in path.read_text("utf-8")
    ]
    assert holders == [".claude/hooks/guard_bash.py"], holders


def test_codex_hermes_configs_hold_no_rules() -> None:
    texts = [
        CODEX_HOOKS.read_text(encoding="utf-8"),
        hermes_snippet_command(),
        HERMES_ALLOWLIST.read_text(encoding="utf-8"),
    ]
    for text in texts:
        for word in ("main", "master", "merge", "no-verify"):
            assert word not in text, (word, text)


def test_hermes_does_not_execute_foreign_repository_script(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "foreign", "main", with_guard=True)
    marker = tmp_path / "executed"
    (repo / ".claude/hooks/guard_bash.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
    )
    result = run_hermes_hook(hermes_snippet_command(), hermes_payload("git status", repo), repo, tmp_path)
    assert result.returncode == 0
    assert not marker.exists()


def test_hermes_protects_workdir_from_outside_git(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = make_repo(tmp_path, "guarded", "main", with_guard=True)
    result = run_hermes_hook(
        hermes_snippet_command(), hermes_payload("git push", outside, workdir=repo), outside, tmp_path
    )
    assert result.returncode == 2
    assert GUARD_TAG in result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"tool_name": "terminal", "tool_input": []},
        {"tool_name": "terminal", "tool_input": {}, "cwd": 1},
        {"tool_name": "terminal", "tool_input": {"workdir": []}, "cwd": "/tmp"},
    ],
)
def test_hermes_dispatch_rejects_malformed_payload(payload: dict, tmp_path: Path) -> None:
    result = run_hermes_hook(hermes_snippet_command(), payload, tmp_path, tmp_path)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
