from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .audit import audit_ledger
from .easy import HELP as EASY_HELP, easy_why, easy_write, plain_status
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
    s_easy = sub.add_parser("easy", help="plain-language front door (same gates)")
    s_easy.add_argument(
        "action", nargs="?", default="help", help="check | write | status | why | help"
    )
    s_easy.add_argument("name", nargs="?", help="module name for write")
    s_easy.add_argument("--fns", default="run", help="comma-separated required functions")
    s_easy.add_argument("--goal", default=None, help="optional goal text")
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
        import io
        from contextlib import redirect_stdout

        report = {"version": __version__, "pin": None, "selftest": None, "audit": None}
        try:
            report["pin"] = {"ok": True, "pin_version": load_pin().get("pin_version")}
        except Exception as e:  # noqa: BLE001
            report["pin"] = {"ok": False, "error": str(e)}
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = selftest_main()
        report["selftest"] = {
            "ok": rc == 0,
            "log_tail": buf.getvalue().strip().splitlines()[-5:],
        }
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

    if args.cmd == "easy":
        ws = Path(args.workspace)
        ws.mkdir(parents=True, exist_ok=True)
        act = (args.action or "help").lower()
        if act in ("help", "-h", "--help"):
            print(EASY_HELP)
            return 0
        if act == "why":
            print(easy_why())
            return 0
        if act == "check":
            import io
            from contextlib import redirect_stdout

            try:
                load_pin()
            except Exception as e:  # noqa: BLE001
                print(f"pin: FAIL ({e})")
                return 1
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = selftest_main()
            print("selftest:", "PASS" if rc == 0 else "FAIL")
            if (ws / ".maxop" / "ledger_latest.json").exists():
                print(plain_status(ws))
            else:
                print("workspace: no prior runs")
            return rc
        if act == "status":
            print(plain_status(ws))
            return 0
        if act == "write":
            if not args.name:
                print("usage: easy write NAME [--fns run,health]")
                return 2
            fns = [x.strip() for x in args.fns.split(",") if x.strip()]
            led = easy_write(ws, args.name, fns=fns, goal=args.goal)
            final = led.get("final")
            print(f"result: {final}")
            if final == "DONE":
                print(f"wrote: {list((led.get('content_hashes') or {}).keys())}")
                print(f"sealed under {ws / '.maxop'}")
                return 0
            print(f"refused: {led.get('abstain_reason') or final}")
            return 1
        print(EASY_HELP)
        return 2

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
