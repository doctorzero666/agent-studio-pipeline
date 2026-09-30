# Validation evidence

Status: implementation and independent review in progress. A release must replace this section with the actual checked commit, counts, cloud check links and clean-install evidence before publication.

Automated tests use temporary repositories and fake CLI executables. They exercise claims, byte-exact rollback, path validation, independent worktrees, checkpoint boundaries, failure handling, explicit quota fallback and timeout behavior without calling paid APIs.

Original local live tests used Claude/Codex/Hermes versions available to the maintainer. Hermes' revised fixed dispatcher has offline native-runtime evidence; a live model rerun is a separate acceptance gate. No current release claims exhaustive integration across every provider version.
