# Validation evidence — 0.1.0a1

Checked on 2026-09-30. Release source is the merge of [implementation PR #2](https://github.com/doctorzero666/agent-studio-pipeline/pull/2); its Checks tab identifies the final tested SHA. Product-code revision `cc3b40f` passed local `just ci`: **349 tests**, Ruff format/lint and full Git-history Gitleaks scan. An independent non-author review passed after four findings were fixed (process-group cleanup, rejected-claim writes, per-app hook context and task-creation rollback). Follow-up reviews passed for Git-hook test isolation and the generated application's pytest import path.

## What was exercised

- Temporary repositories and synthetic CLI executables: committed claims, byte-preserving rollback, invalid/missing/path-boundary inputs, independent worktrees, wrong-task rejection, explicit takeover, quota-only opt-in fallback, timeouts and process-group cleanup. No model API is called by these tests.
- Actual pre-push hook: the full suite passes with Git's repository environment variables present. A fixture-isolation regression found during publication was fixed without relaxing product guards.
- Built wheel installed without dependencies in a fresh Python 3.12 environment, outside the source tree. Workspace/app/task initialization, status, checker and dry-run launch passed. The generated app's real `just check` passed, including **2 example tests**.
- Both the private control repository and generated app were independently bundled, verified and cloned; restored HEADs matched. An earlier tree comparison also matched. Ignored/uncommitted files and credentials are outside Git backup scope.
- [Initial Linux CI](https://github.com/doctorzero666/agent-studio-pipeline/actions/runs/36660226305) passed checks and package build. Final implementation checks remain visible in PR #2.
- Main ruleset requires a PR and successful `ci` from GitHub Actions, with no bypass actors and no force-push/deletion. [Acceptance PR #3](https://github.com/doctorzero666/agent-studio-pipeline/pull/3) injected a cloud-only failure. [The failing run](https://github.com/doctorzero666/agent-studio-pipeline/actions/runs/36660964488) caused the merge API to return **HTTP 405: Required status check "ci" is failing**. The injected fault is reverted on that disposable branch; it is not part of the release.
- npm's locked development install reported zero vulnerabilities. Runtime dependencies are standard-library only. Dedicated mypy, Bandit and pip-audit tools were unavailable locally; this release does not claim those checks ran.

## Live integrations and limits

The original local guard implementation was exercised with Claude Code, Codex and Hermes. The revised fixed-install Hermes dispatcher also passed one explicitly authorized live-model test: native runtime evidence recorded a blocked terminal call (exit 2) and the temporary remote received no refs. Private provider transcripts and user-level configuration are intentionally not distributed.

Those live checks are provenance evidence, not a promise that every provider version or every public-package adapter has been tested live. CI uses synthetic agents. Hooks are advisory, quota recognition is heuristic, runtime limits are not monetary limits, and same-user credentials are not independent authorization. See [security boundaries](../SECURITY.md).
