# Changelog

## 0.1.0a1 — 2026-09-30

- Extracted local task/worktree/checkpoint workflow into an installable package.
- Added workspace, application and task scaffolding, status and tool availability diagnostics.
- Added bounded foreground runs with explicit quota-only fallback and metadata receipts.
- Added distribution checks, source provenance and release/recovery guidance.
- Verified 349 local tests, independent review, clean wheel installation, generated-app checks, Git backup restoration and server-side rejection of failed CI.
- Known limits: alpha, POSIX only, Chinese task schema, heuristic quota detection, advisory hooks, no currency enforcement or hosted deployment.
