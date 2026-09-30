# Security boundaries

Do not disclose real credentials, private task records or customer information in public issues. For a suspected vulnerability, use the repository's private vulnerability reporting feature when available; otherwise contact the maintainer without exploit secrets.

This tool is for a trusted local user. Task locks are advisory between cooperating processes on one host. An administrator, a separate Git client or an agent with equivalent filesystem access can change files outside those locks. The supervisor lock coordinates `studio-run` instances only; direct `studio-launch`/other terminals still require one-writer coordination.

Hooks parse common command forms and provide fast feedback. Shell aliases, dynamically generated commands, `cd`/Git configuration, alternate tools and interactive sessions can escape this limited inspection. **Hooks are not a sandbox or complete authorization boundary.** Use OS sandboxing, least-privilege credentials and server-side branch protection.

Codex project hooks need explicit user trust at each applicable path. Hermes hooks require reviewing and installing fixed local copies; never globally execute guard code discovered in an arbitrary repository. No global hook installer runs during package installation.

Agent processes inherit the user's provider configuration. The supervisor does not read balances or enforce currency budgets. Only explicitly configure fallbacks you authorize to consume their configured plan; do not use fallback for financial, production or other non-idempotent actions without reconciling external state.

Private prompts and CLI output are not included in run receipts. CLI output is captured in an OS temporary file, deleted on normal exit; it may contain private data and must not be exported. Abrupt OS failure, provider-owned logs and child processes have separate retention policies. Configure full-disk protection appropriately.

The first release uses POSIX file locks/process groups and supports macOS/Linux/WSL. It does not provide multi-host scheduling, strong tenant isolation, an encrypted credential vault or unattended production deployment.
