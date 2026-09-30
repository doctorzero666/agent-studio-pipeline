# Agent Studio Pipeline

Local-first task handoffs and isolated Git worktrees for Claude Code, Codex and Hermes.

[中文说明](README.zh-CN.md) · [How it works](docs/workflow.md) · [Security boundaries](SECURITY.md) · [Release and recovery](docs/release-and-recovery.md)

**Early alpha.** A practical CLI and workflow extracted from a single-Mac studio. This is not an autonomous software company, a sandbox, or a hosted model service. You own the files, Git history, accounts and final release decisions.

## What you get

- A private workspace for task intent, acceptance criteria and checkpoints; independent application repositories for code.
- One writer per task, isolated worktrees, committed claims, explicit takeover and byte-preserving failure recovery.
- CLI checkpoints with the real branch, commit and dirty state. Wrong-task and detached-HEAD checkpoints are rejected.
- Bounded foreground runs, metadata-only receipts and **opt-in, one-attempt quota fallback**. Unknown failures and timeouts stop for reconciliation.
- Tested advisory command guards for Claude Code/Codex and a fixed-install Hermes dispatcher; no global configuration is installed automatically.
- A sample Python application, CI template, PR template, human/non-author review protocol and recovery procedure.

## Install

Supported baseline: **macOS or Linux/WSL, Python 3.11+, Git**. Native Windows is not supported yet (`fcntl` is used for local locks). `uv` and `just` are needed for the supplied development workflow. Install the agent CLIs separately and sign in with your own accounts.

Download the wheel from [Releases](https://github.com/doctorzero666/agent-studio-pipeline/releases), verify its SHA-256 against the release manifest, then:

```sh
uv tool install ./agent_studio_pipeline-0.1.0a1-py3-none-any.whl
```

From a source checkout:

```sh
uv sync --locked
uv run studio --help
just check
```

Do not assume the package is published to PyPI. This project distributes GitHub source and release wheels.

## First workspace

Configure your Git name/email first. The destination must not exist; initialization never overwrites another workspace.

```sh
studio init "$HOME/my-agent-workspace"
export STUDIO_DIR="$HOME/my-agent-workspace/studio"
studio app greeting
studio task greeting DEMO-001 --goal 'Add a greeting with invalid-input tests'
studio doctor
studio status
studio-check "$STUDIO_DIR"
studio-launch codex --dry-run greeting DEMO-001
```

Edit and commit the task card acceptance criteria before starting a real agent. Launching consumes the selected CLI's configured plan; no model subscription is included.

```sh
studio-launch codex greeting DEMO-001
# Alternatives: studio-launch claude ... / studio-launch hermes ...
```

The task card lives at `studio/项目/应用/greeting/tasks/DEMO-001/task.md`. The Chinese field names and paths are the stable v0.1 schema; the CLI and this guide are available in English. Agent launch commits the claim before starting the CLI. A failed launch retains the claim for diagnosis.

In another terminal, after confirming the previous writer has stopped:

```sh
studio-launch claude --takeover greeting DEMO-001
```

Takeover reuses the existing task worktree and branch, including a previous agent's branch prefix. It does not replay conversations or transfer credentials. Check files and external-operation state first.

## Checkpoint and bounded run

```sh
cd "$STUDIO_DIR/../greeting/.claude/worktrees/DEMO-001"
studio-checkpoint DEMO-001 'Implemented greeting; next: independent review'   --test-tail '2 passed'
```

`--test-tail` is a caller-supplied note, **not proof that the tool ran a test**. Run `just check` yourself and record actual evidence. Checkpoints do not automatically set tasks to done or release a writer.

For a noninteractive bounded run, put the exact task prompt in a local text file:

```sh
studio-run codex greeting DEMO-001 --timeout 900 --prompt-file task-prompt.txt
# Optional, explicit authorization for ONE alternate CLI after a recognized quota error:
# studio-run codex greeting DEMO-001 --fallback claude --prompt-file task-prompt.txt
```

Receipts are stored in the application's Git common directory under `studio-runs/`. No raw prompt/output is stored in receipts. An exit code of zero is not acceptance. The supervisor's runtime limit is **not a token or dollar cap**; the CLI's account and provider settings still determine charges. No fallback is enabled by default. See [the limitations](docs/workflow.md).

## Orca

Worktrees created by external CLIs may be hidden. In the application project's menu, open **Show hidden worktrees → Claude Code source → Show**. This includes any agent using `.claude/worktrees/*`. Select a task worktree to browse its files and Source Control; the parent workspace's `main` view is a different checkout.

## GitHub and review

Use a public repository for a free-plan pilot, or a plan that supports protected branches for your private repositories. Configure required PRs and the `ci` check, disallow force pushes/deletions and keep bypass actors empty. Protect secrets separately. Agent CLIs sharing your administrator credential are **not** technically separated from you.

Never publish your private studio's original Git history. The supplied source distribution was assembled from an explicit file allowlist; see [provenance](docs/provenance.md).

## Development

```sh
just setup  # uv dependencies, commitlint, local lefthook installation
just check # format, lint, isolated offline tests
just ci    # plus full Git history secret scanning; requires gitleaks
uv build
```

CI runs synthetic agents; it never requires model credentials. Live provider integration evidence is distinguished from mocked adapter tests in [validation](docs/validation.md).

MIT licensed. Contributions welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
