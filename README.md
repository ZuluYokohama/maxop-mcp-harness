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
IDLE → PLAN → DELEGATE → STAGED ACT → VERIFY → COCYCLE → MAXOP → COMMIT → DONE
                                         ↘ ABSTAIN / FAIL
```

**COCYCLE:** syntax · import restriction · API surface · lexicon · circular imports  
**COMMIT:** apply staged files with controlled-failure rollback, then store full SHA-256 hashes + `pin_version` under `.maxop/`

## Safety boundary

- Candidate files are written to an isolated staging copy. Controlled ABSTAIN, FAIL, gate
  exceptions, and ledger-persistence failures are compensated before return; if exact
  restoration cannot be established, the run fails as recovery-required.
- One cooperative workspace lock serializes harness runs. Multi-file replacement is not
  crash-atomic; a process/host crash during COMMIT requires manual inspection before a
  stale `transaction.lock` is removed. An uncertain rollback deliberately retains that
  lock and marks the ledger `NEEDS_MANUAL_RECOVERY`.
- Paths must be relative and remain below the resolved workspace. Parent traversal,
  absolute/drive-relative paths, links/reparse points, `.git`, and `.maxop` are rejected.
- Raw MCP `fs_write` is not advertised and is denied by default. Set
  `MAXOP_ALLOW_RAW_WRITE=1` only for a separately sandboxed workspace; the same path
  confinement still applies.
- The state directory is fixed at `<workspace>/.maxop`; `MAXOP_STATE_DIR` may only name
  that same resolved directory.
- This remains a source-level gate, not a substitute for a target repository's native
  tests, build, domain certificate, or human review.
- Replacement preserves ordinary POSIX mode bits, but extended ACLs, xattrs, and Windows
  DACLs are outside the current transaction contract and require downstream review.

## Docs

- [CAPABILITIES.md](./CAPABILITIES.md) — works / not included  
- [PORTFOLIO.md](./PORTFOLIO.md) — residual stack across labs  
- [CHANGELOG.md](./CHANGELOG.md)

## License

MIT
