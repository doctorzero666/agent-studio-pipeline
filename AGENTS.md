# Agent Studio Pipeline contributor rules

Read the task card before editing. One writer per task, isolated worktrees under `.claude/worktrees/<ID>`.
Use `just check` for local verification and `just ci` before release. Never bypass hooks or relax tests.
Independent non-author review is required. Do not read credentials or customer data. Model output is untrusted.
Do not auto-merge, publish, change permissions, or call paid providers without explicit task authorization.
No original workspace history, task records, personal paths or customer files may be included. Review the export allowlist.
Runtime hooks are advisory feedback, not an enforcement boundary. Do not modify global provider configuration by default.
