# Statement of Exceptional Work (draft)

**Author context:** Independent residual systems work under ZuluYokohama.  
**Purpose:** External evaluation (research / eng hiring). Not a product pitch.

---

## What was built (verifiable)

### 1. Gated agent harness — [maxop-mcp-harness](https://github.com/ZuluYokohama/maxop-mcp-harness)

Markov agent loop where **commit is forbidden unless gates clear**:

- Locked `pin.json` floors (human-commit only)
- COCYCLE: syntax · import restriction · API surface · overclaim lexicon · circular imports
- MaxOp aggregate fail-closed on hard gates
- `.maxop/` ledger with content hashes; `audit` re-verifies HASH_DRIFT
- MCP stdio tools: `harness_run`, `prereg_freeze`, `ledger_audit`, workspace `fs_*`
- Planted selftest **G1–G11**; CI on `main`

**Clone check:** `PYTHONPATH=src python -m maxop_harness.cli selftest` → exit 0.

### 2. Restriction–projection operator series — [rplc-sheaf](https://github.com/ZuluYokohama/rplc-sheaf)

Design law in code: restrict → measure obstruction → audit vs controls → OPEN or STOP.  
Sheaf Laplacian path, certificates with verify/replay, domain payloads only.  
**RESIDUE:** sparse ALU at large n; calibrated audit margins.

### 3. Domain applications (same posture)

| Lab | OPEN | RESIDUE |
|-----|------|---------|
| [protein-rpl-validation](https://github.com/ZuluYokohama/protein-rpl-validation) | AF/PAE/MobiDB restriction authority; mini-set 5/5 | DisProt-scale ROC (#2) |
| [tt-brown-residue-lab](https://github.com/ZuluYokohama/tt-brown-residue-lab) | Claims ledger + sim DAQ path | Hardware vacuum residue (#1) |

---

## What this is *not*

- Not a proof of RH, consciousness-as-field, or ToE
- Not clinical diagnostics or gravity claims
- Not “Sheaf LLM replaces transformers” without matched baselines and effect sizes
- Not RogueGringo breadth — evaluation should weight **ZuluYokohama** residual labs

---

## Engineering thesis (one paragraph)

Most agent and model systems **narrate** success. These labs force **computed** success: pins, certificates, matched controls, and explicit ABSTAIN/NULL when structure does not survive audit. The scarce skill is not inventing another metaphor; it is refusing to promote residue.

---

## How to evaluate in 30 minutes

1. Clone `maxop-mcp-harness` → run `selftest` and `doctor`
2. Read `CAPABILITIES.md` and `PORTFOLIO.md`
3. Skim `rplc-sheaf` CLAIMS / smoke test
4. Ask: where does this stack **refuse** to open? (That is the product.)

---

## Contact

GitHub: [ZuluYokohama](https://github.com/ZuluYokohama)  
Portfolio index: [PORTFOLIO.md](./PORTFOLIO.md)
