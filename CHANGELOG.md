# Changelog

## 0.4.0 (unreleased)
- bump the ledger/pin contract to v2 for full hashes, preregistration, and integrity markers
- stage ACT in an isolated workspace and apply only after every gate passes
- reject traversal, absolute/drive-relative, control, and link/reparse paths
- default-deny raw MCP filesystem writes
- bind preregistration in the persisted ledger and use full SHA-256 content hashes
- constrain `.maxop` state files and add controlled-failure group rollback
- add cross-platform adversarial transaction, rollback, path, MCP, and audit tests

## 0.3.1
- `gate_circular_imports` in COCYCLE (touch-set local graph)
- `doctor` CLI: pin + selftest + optional audit
- G11 circular path

## 0.3.0
- `.maxop/` state dir, ledger persist, `runs.jsonl`
- `audit` CLI + `ledger_audit` MCP tool
- G10 hash-drift detection

## 0.2.1
- `harness_run` + `prereg_freeze` MCP tools
- host config example

## 0.2.0
- pin.json floors + lexicon gate
- MCP stdio server
- content hashes + pin_version on ledger
- selftest G1–G7

## 0.1.0
- Markov loop, subagents, syntax/import/API gates
