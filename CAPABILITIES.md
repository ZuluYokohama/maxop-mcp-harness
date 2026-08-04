# CAPABILITIES

Honest operational matrix. Heuristic ≠ computed.

| Surface | Status | Notes |
|---------|--------|--------|
| Markov loop PLAN…DONE | works | Illegal transitions raise |
| pin.json floors / lexicon | works | Human-commit only |
| syntax / import / API / circular / lexicon gates | works | Hard gates fail-closed |
| MaxOp aggregate | works | Pin floor 0.99 |
| .maxop ledger + hashes | works | Never /tmp |
| audit CLI / ledger_audit MCP | works | HASH_DRIFT detected |
| prereg_freeze | works | SHA256 goal+spec |
| harness_run MCP | works | Gated write |
| fs_* MCP tools | works | Workspace-scoped |
| selftest G1–G11 | works | Exit 1 on fail |
| doctor | works | pin + selftest + audit |
| LLM coder agent | not included | Deterministic stubs only |
| Full MCP SDK / OAuth | not included | JSON-RPC subset |
| Sheaf cohomology / zeta | not claimed | Cocycle-lite only |

Conformance: `python -m maxop_harness.cli selftest` → exit 0.
