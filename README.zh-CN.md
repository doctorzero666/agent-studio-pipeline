# Agent Studio Pipeline

一套从实际多 Agent 开发中整理出来的本地优先管线：任务卡、独立工作树、交接检查点、检查与评审、受限运行，以及 GitHub 协作模板。

**当前是早期 alpha。** 适用于 macOS、Linux/WSL；需要 Python 3.11+、Git。开发流程还需要 uv、just。各 Agent 的安装、账号、额度和费用由使用者自行管理。

## 开始

从 GitHub Releases 下载 wheel 并核对 SHA256SUMS，再用 `uv tool install ./agent_studio_pipeline-0.1.0a1-py3-none-any.whl` 安装。

```sh
studio init "$HOME/my-agent-workspace"
export STUDIO_DIR="$HOME/my-agent-workspace/studio"
studio app greeting
studio task greeting DEMO-001 --goal '实现问候函数和异常输入测试'
studio status
studio doctor
studio-launch codex --dry-run greeting DEMO-001
```

先填写、提交任务卡的验收标准，再执行 `studio-launch codex greeting DEMO-001`。同一任务只有一个写入者；多个任务各用独立分支和 worktree 并行。任务卡在 `studio/项目/应用/greeting/tasks/DEMO-001/task.md`。

确认原 Agent 已停止后，可用 `studio-launch claude --takeover greeting DEMO-001` 接替。接续的是代码、Git 状态与检查点，不是原会话的隐含记忆。

进入任务工作树后，用 `studio-checkpoint DEMO-001 '已做什么；已验证什么；下一步是什么'` 留记录。

`studio-run` 提供前台有界执行、超时停止和结果回执；默认没有备用供应商。显式 `--fallback` 最多允许一次识别到额度错误后的接替。未知错误和超时不会自动重试；时间限制不是金额上限。

## 边界

- 本地 hooks 只是辅助反馈，不是安全沙箱。共享管理员身份也不能保证“只有人能合并”。
- 不自动修改全局 Agent 设置，不自动信任 Codex 钩子，不包含任何密钥或模型订阅。
- Hermes 使用用户自己的配置，不写死付费供应商。
- 任务状态不会因为 CLI 退出码为零就变成 done；仍需测试、非作者评审和合并记录。
- Orca 默认可能隐藏 `.claude/worktrees/*`；项目菜单选择 Show hidden worktrees，再把 Claude Code 来源设为显示。
- 管理仓库与应用仓库各自备份；不要把带有私密历史的工作室仓库直接公开。

完整操作与验证范围见 [英文说明](README.md)、[工作流](docs/workflow.md)、[安全边界](SECURITY.md)、[发布与恢复](docs/release-and-recovery.md)。
