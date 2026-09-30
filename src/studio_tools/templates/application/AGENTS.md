# Application rules

Read your task card in the sibling studio before editing. Claim one task per writer.
Work in `.claude/worktrees/<TASK-ID>` on `agent/<agent>/<TASK-ID>`.
Run `just check`; record actual results and next steps with studio-checkpoint.
A non-author must review before merge. Human owns merge and deployment decisions.
Never bypass hooks, publish secrets, silently switch paid providers or retry unknown external actions.
Hooks provide feedback, not a security boundary. Review hook definitions before trusting them.
