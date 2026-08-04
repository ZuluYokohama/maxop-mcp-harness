# maxop-mcp-harness

**Gated MCP-shaped agentic code harness** — Markov loop, pinned floors, cocycle-lite gates, `.maxop` ledger, audit, stdio MCP tools.

Residual verification substrate. **Not** a claim about AGI, zeta, or "most capable agent of the future."

## Install (dev)

```bash
git clone https://github.com/ZuluYokohama/maxop-mcp-harness.git
cd maxop-mcp-harness
export PYTHONPATH=src
python -m maxop_harness.cli selftest
python -m maxop_harness.cli doctor
```

## Loop

```
IDLE → PLAN → DELEGATE → ACT → VERIFY → COCYCLE → MAXOP → COMMIT → DONE
                                         ↘ ABSTAIN / FAIL
```

**COCYCLE:** syntax · import restriction · API surface · lexicon · circular imports  
**COMMIT:** content hashes + `pin_version` under `.maxop/`

## CLI

| Command | Role |
|---------|------|
| `selftest` | G1–G11 planted fixtures |
| `pin` | Show locked invariants |
| `run` | Gated write loop |
| `audit` | Re-verify latest ledger |
| `doctor` | pin + selftest + audit |
| `mcp` | JSON-RPC stdio server |
| `tools` | List MCP tool specs |

```bash
python -m maxop_harness.cli --workspace /tmp/ws run \
  --goal "stub" \
  --spec '{"touch_files":["out/a.py"],"required_api":["run"]}'
python -m maxop_harness.cli --workspace /tmp/ws audit
```

## MCP

See `examples/mcp_host_config.json`. Tools include `fs_*`, `harness_run`, `prereg_freeze`, `ledger_audit`.

## Docs

- [CAPABILITIES.md](./CAPABILITIES.md) — works / not included  
- [CHANGELOG.md](./CHANGELOG.md)

## License

MIT
