"""
Minimal MCP-compatible stdio server (JSON-RPC 2.0 subset).

tools/list + tools/call for CodebaseTools and gated harness_run.
Workspace: MAXOP_WORKSPACE env (default cwd).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .loop import MaxOpHarness
from .mcp_tools import CodebaseTools
from .prereg import canonical_spec, prereg_sha256
from .audit import audit_ledger


def _workspace() -> Path:
    return Path(os.environ.get("MAXOP_WORKSPACE", os.getcwd())).resolve()


def _tools() -> CodebaseTools:
    allow_raw_write = os.environ.get("MAXOP_ALLOW_RAW_WRITE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return CodebaseTools(_workspace(), allow_writes=allow_raw_write)


def _harness_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "harness_run",
            "description": (
                "Run the gated MaxOp Markov loop (PLAN…COMMIT). "
                "Writes only if syntax/cocycle/API/lexicon clear MaxOp floors. "
                "Returns ledger JSON including content_hashes and pin_version."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "prereg_sha256": {
                        "type": "string",
                        "description": "Digest returned by prereg_freeze for this exact goal/spec",
                    },
                    "touch_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["agent_out/module.py"],
                    },
                    "required_api": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["run"],
                    },
                    "body": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Optional path→source map instead of stubs",
                    },
                    "notes": {"type": "string", "default": ""},
                },
                "required": ["goal", "prereg_sha256"],
            },
        },
        {
            "name": "prereg_freeze",
            "description": (
                "SHA256-freeze a goal+spec before work. Does not run the harness."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "spec": {"type": "object"},
                },
                "required": ["goal"],
            },
        },
        {
            "name": "ledger_audit",
            "description": "Re-verify latest .maxop ledger: pin version, content hashes, hard gates. AUDIT PASS/FAIL.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def _call_harness_run(arguments: dict[str, Any]) -> dict[str, Any]:
    goal = arguments["goal"]
    spec = canonical_spec(arguments)
    body = arguments.get("body")
    prereg = arguments.get("prereg_sha256")
    if not isinstance(prereg, str):
        raise ValueError("harness_run requires prereg_sha256 from prereg_freeze")
    t0 = time.perf_counter()
    harness = MaxOpHarness(_workspace())
    ledger = harness.run(goal, spec=spec, body=body, prereg_sha256=prereg)
    ledger["ms"] = (time.perf_counter() - t0) * 1e3
    return ledger


def _call_prereg_freeze(arguments: dict[str, Any]) -> dict[str, Any]:
    goal = arguments["goal"]
    spec = canonical_spec(arguments.get("spec"))
    digest = prereg_sha256(goal, spec)
    return {
        "prereg_sha256": digest,
        "goal": goal,
        "spec": spec,
        "frozen": True,
        "note": "criteria frozen; run harness_run separately — do not retune after freeze",
    }


def handle(msg: Any) -> dict[str, Any] | None:
    if not isinstance(msg, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request: object required"},
        }
    mid = msg.get("id")
    method = msg.get("method")
    raw_params = msg.get("params", {})
    if raw_params is None:
        raw_params = {}
    if not isinstance(raw_params, dict):
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "error": {"code": -32602, "message": "Invalid params: object required"},
        }
    params = raw_params

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "maxop-mcp-harness", "version": __version__},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        specs = [t.to_mcp() for t in _tools().list_tools()] + _harness_specs()
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": specs}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {
                    "code": -32602,
                    "message": "Invalid params: tool name string and arguments object required",
                },
            }
        try:
            if name == "harness_run":
                content = _call_harness_run(arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(content, default=str)}],
                        "isError": content.get("final") not in ("DONE",),
                    },
                }
            if name == "ledger_audit":
                content = audit_ledger(_workspace())
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(content)}],
                        "isError": content.get("AUDIT") != "PASS",
                    },
                }
            if name == "prereg_freeze":
                content = _call_prereg_freeze(arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(content)}],
                        "isError": False,
                    },
                }
            result = _tools().call(name, arguments)
            if result.ok:
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result.content, default=str)}],
                        "isError": False,
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": result.error or "error"}],
                    "isError": True,
                },
            }
        except Exception as e:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                    "isError": True,
                },
            }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            err = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
