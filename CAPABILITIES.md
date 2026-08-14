# CAPABILITIES

Honest operational matrix. Heuristic ≠ computed.

| Surface | Status | Notes |
|---------|--------|--------|
| Markov loop PLAN…DONE | works | Illegal transitions raise |
| pin.json floors / lexicon | works | Human-commit only |
| syntax / import / API / circular / lexicon gates | works | Hard gates fail-closed |
| MaxOp aggregate | works | Pin floor 0.99 |
| .maxop ledger + hashes | works | Fixed in workspace; full SHA-256 |
| audit CLI / ledger_audit MCP | works | HASH_DRIFT detected |
| prereg_freeze | works | SHA256 goal+spec |
| harness_run MCP | works | Staged, gated, controlled-failure rollback; not crash-atomic |
| fs_read/list/grep MCP | works | Workspace-scoped, control paths excluded |
| raw fs_write MCP | default off | Explicit sandbox-only opt-in |
| selftest + adversarial suite | works | Linux/Windows, Python 3.10/3.12/3.13 CI |
| doctor | works | pin + selftest + audit |
| LLM coder agent | not included | Deterministic stubs only |
| Full MCP SDK / OAuth | not included | JSON-RPC subset |
| Sheaf cohomology / zeta | not claimed | Cocycle-lite only |

Conformance: `python -m maxop_harness.cli selftest` → exit 0.
