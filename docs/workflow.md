# Workflow and ownership

1. Define the task's goal, scope, acceptance, authorized data and cost boundaries in the private task card.
2. `studio-launch` checks a clean tracked card, creates/reuses its worktree, commits the claim, then launches the agent.
3. Each meaningful step saves actual code first, runs checks and records a checkpoint. Keep a quota reserve for this.
4. A different author reviews. Fix findings, rerun checks, and let the authorized maintainer merge.
5. Record the merge, tests, review and release receipt before marking done. Keep unresolved work explicit.

## Two parallel tasks

Create DEMO-001 and DEMO-002 and launch each separately. They share Git object history but have different working files. Conflicting changes may still need reconciliation when merged; test the final combined result.

## Recovery

A quota interruption is not permission for two writers. Confirm the old process stopped, inspect `git status`, recent commits and external operations, then `--takeover`. Existing task branches keep the old agent prefix; this avoids moving unfinished history. Detached HEAD and another task's branch are rejected.

## Supervisor contract

`studio-run` is foreground orchestration, not a persistent daemon. One selected CLI runs under a process-group timeout. A second `studio-run` for the same task is rejected by a nonblocking local lock. It does not stop agents launched elsewhere.

No alternate is attempted unless `--fallback` was explicitly supplied. At most two CLIs run. Fallback requires a nonzero exit, a recognized quota phrase in the CLI's final output and a successfully saved checkpoint. This phrase detection is heuristic, not an authenticated provider quota API; it can miss or misclassify errors. Use explicit manual takeover when accuracy matters. Unknown failures, interruption and timeout never trigger another writer.

An exit of zero means only that the CLI exited successfully. The card remains doing and claimed until an operator verifies completion. Failed checkpoint commits cause failure, not silent success. Receipts contain outcome, exit status, elapsed time and checkpoint status, not raw content. No hidden model calls, automatic API purchases or administrator permission upgrades occur.

The timeout bounds a supervised process group, not remote server jobs or detached processes that create another session. Reconcile external state before repeating any consequential action.

## Current schema

The v0.1 task fields and directory names are inherited from the original Chinese workflow. They are machine-read, not arbitrary translated labels. Keep task card field names intact. `STUDIO_DIR` must be an absolute initialized path; app names are safe lowercase names. Runtime Git calls strip inherited GIT_* redirection variables.
