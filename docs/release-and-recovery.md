# Release and recovery

## Before a release

- Commit reviewed code and run `just ci` on the final combined tree.
- Run `uv build`; install the wheel in a fresh environment, initialize a new Studio and application, and run the included example tests.
- Review every tracked file and `git log` for private data; secret scanning alone cannot recognize personal context.
- Update CHANGELOG with actual behavior and limits. Create a version tag pointing at the reviewed commit.
- Compute SHA-256 for the wheel and source archive; attach them and SHA256SUMS to a GitHub prerelease. Never upload .env, .venv, task logs or original private histories.

## Backup

A Studio control repository and each application are separate repositories. Back up or push each independently. Git does not back up uncommitted files, ignored data, installed credentials or untracked worktrees. Reconcile and commit unfinished work to task branches before backup. Keep sensitive runtime files in a separately protected backup.

For an offline Git backup: `git bundle create backup.bundle --all`. Verify with `git bundle verify backup.bundle` and test a restore using `git clone backup.bundle restored`. Do this independently for the control repository and every app. Task metadata alone cannot restore application code.

## Roll back a release

Install a previously verified wheel and retain its lockfile and checksums. Do not delete worktrees to downgrade. For repository changes, prefer a reviewed revert PR, preserving history and rerunning checks; no force-push or reset of others' work. Database or deployed-service rollback is application-specific and is not automated by this package.
