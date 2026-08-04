from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .audit import audit_ledger
from .loop import MaxOpHarness, mcp_list_tools
from .pin import load_pin
from .selftest import main as selftest_main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MaxOp MCP-shaped gated code agent harness")
    p.add_argument("--workspace", default="./ws", help="agent workspace root")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tools", help="list MCP-shaped tool specs")
    sub.add_parser("pin", help="print locked pin invariants")
    sub.add_parser("selftest", help="run planted-fixture gates G1–G11")
    sub.add_parser("audit", help="re-verify latest ledger hashes + hard gates")
    sub.add_parser("doctor", help="pin load + selftest + optional workspace audit")
    sub.add_parser("mcp", help="run MCP stdio server (MAXOP_WORKSPACE=...)")
    s_run = sub.add_parser("run", help="run Markov gated loop")
    s_run.add_argument("--goal", required=True)
    s_run.add_argument(
        "--spec",
        default="{}",
        help='JSON: {"touch_files":[...],"required_api":[...]}',
    )
    s_run.add_argument(
        "--body",
        default=None,
        help="JSON map path→source to write instead of stubs",
    )

    args = p.parse_args(argv)

    if args.cmd == "pin":
        print(json.dumps(load_pin(), indent=2))
        return 0

    if args.cmd == "selftest":
        return selftest_main()

    if args.cmd == "doctor":
        from . import __version__

        report = {"version": __version__, "pin": None, "selftest": None, "audit": None}
        try:
            report["pin"] = {"ok": True, "pin_version": load_pin().get("pin_version")}
        except Exception as e:  # noqa: BLE001
            report["pin"] = {"ok": False, "error": str(e)}
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = selftest_main()
        report["selftest"] = {"ok": rc == 0, "log_tail": buf.getvalue().strip().splitlines()[-5:]}
        ws = Path(args.workspace)
        if (ws / ".maxop" / "ledger_latest.json").exists():
            report["audit"] = audit_ledger(ws)
        else:
            report["audit"] = {"skipped": True, "reason": "no ledger_latest"}
        print(json.dumps(report, indent=2))
        ok = report["pin"].get("ok") and report["selftest"].get("ok")
        if isinstance(report.get("audit"), dict) and report["audit"].get("AUDIT") == "FAIL":
            ok = False
        return 0 if ok else 1

    if args.cmd == "audit":
        result = audit_ledger(Path(args.workspace))
        print(json.dumps(result, indent=2))
        return 0 if result.get("AUDIT") == "PASS" else 1

    if args.cmd == "mcp":
        from .mcp_server import serve

        os.environ.setdefault("MAXOP_WORKSPACE", str(Path(args.workspace).resolve()))
        return serve()

    ws = Path(args.workspace)
    ws.mkdir(parents=True, exist_ok=True)

    if args.cmd == "tools":
        print(json.dumps(mcp_list_tools(str(ws)), indent=2))
        return 0

    if args.cmd == "run":
        spec = json.loads(args.spec)
        body = json.loads(args.body) if args.body else None
        harness = MaxOpHarness(ws)
        ledger = harness.run(args.goal, spec=spec, body=body)
        print(json.dumps(ledger, indent=2))
        return 0 if ledger.get("final") == "DONE" else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
