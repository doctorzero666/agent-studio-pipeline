# Provenance and licensing

This distribution is a clean extraction from the maintainer's local Studio tools. `export-manifest.json` records the source revisions and allowlisted source/test paths. Original Git history, personal task cards, customer folders, local model output, installation logs and user-level configuration were not imported.

The task-card protocol, worktree launcher, checkpoint logic and hook tests were exercised locally before extraction. Public-distribution changes add safe initialization, cross-task validation, Git environment isolation, configurable agent selection and bounded runs. The source task references such as TOOLS-008 in code/tests describe lineage, not public acceptance claims.

MIT covers this project's own code. The runtime uses Python's standard library. Development packages and external CLIs remain under their respective licenses; no third-party models, tokens or proprietary app binaries are included. GitHub Actions are referenced at pinned commits, not vendored.

The experimental CommonMark evaluation and its private corpus are not part of this first release. The inherited Markdown checker remains a pragmatic subset, not a complete CommonMark/GFM validator or security scanner.
