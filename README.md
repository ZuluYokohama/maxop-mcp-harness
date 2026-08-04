# maxop-mcp-harness

**Gated agentic code harness** with a plain-English front door.

Writes code only when syntax, imports, API, and claim-language clear the pin.  
Refusal is intentional. Residual verification substrate — **not** a claim about AGI or “most capable agent.”

## 60-second start

```bash
git clone https://github.com/ZuluYokohama/maxop-mcp-harness.git
cd maxop-mcp-harness
export PYTHONPATH=src
export MAXOP_WORKSPACE=./ws

python -m maxop_harness write demo with run and health
python -m maxop_harness am i ok
python -m maxop_harness what happened
python -m maxop_harness list
python -m maxop_harness why
```

Or: `bash bin/maxop write demo`

| You say | It does |
|---------|---------|
| `write NAME with a, b` | Sealed stub `NAME.py` requiring those functions |
| `am i ok` / `check` | Selftest + plain status |
| `what happened` | Last ledger + audit |
| `list` | Sealed files |
| `why` | What it refuses (and why) |

Unknown phrases → help + short suggestions. Nothing is sealed unless gates pass.

## Power CLI

```bash
python -m maxop_harness.cli selftest    # G1–G11
python -m maxop_harness.cli doctor
python -m maxop_harness.cli pin
python -m maxop_harness.cli --workspace /tmp/ws run \
  --goal "stub" \
  --spec '{"touch_files":["out/a.py"],"required_api":["run"]}'
python -m maxop_harness.cli --workspace /tmp/ws audit
python -m maxop_harness.cli mcp         # JSON-RPC stdio
```

## Loop

```
IDLE → PLAN → DELEGATE → ACT → VERIFY → COCYCLE → MAXOP → COMMIT → DONE
                                         ↘ ABSTAIN / FAIL
```

**COCYCLE:** syntax · import restriction · API surface · lexicon · circular imports  
**COMMIT:** content hashes + `pin_version` under `.maxop/`

## Docs

- [CAPABILITIES.md](./CAPABILITIES.md) — works / not included  
- [PORTFOLIO.md](./PORTFOLIO.md) — residual stack across labs  
- [CHANGELOG.md](./CHANGELOG.md)

## License

MIT
