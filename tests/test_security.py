from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maxop_harness.audit import audit_ledger
from maxop_harness.loop import MaxOpHarness
from maxop_harness.mcp_server import handle
from maxop_harness.mcp_tools import CodebaseTools
from maxop_harness.prereg import prereg_sha256
from maxop_harness.state import WorkspaceLock, state_dir
from maxop_harness.transaction import WorkspaceTransaction


class MaxOpSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.workspace = self.base / "ws"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_sibling_prefix_and_parent_escape_rejected(self) -> None:
        tools = CodebaseTools(self.workspace, allow_writes=True)
        outside = self.base / "ws-escape" / "pwn.py"
        result = tools.call(
            "fs_write", {"path": "../ws-escape/pwn.py", "content": "owned = True\n"}
        )
        self.assertFalse(result.ok)
        self.assertFalse(outside.exists())

    def test_absolute_control_and_windows_alias_paths_rejected(self) -> None:
        tools = CodebaseTools(self.workspace, allow_writes=True)
        cases = [
            str((self.workspace / "inside.py").resolve()),
            ".git/config",
            ".maxop/ledger_latest.json",
            r"C:drive-relative.py",
            r"\\server\share\file.py",
            "file.py:stream",
            ".git./config",
            "NUL",
        ]
        for rel in cases:
            with self.subTest(path=rel):
                result = tools.call("fs_write", {"path": rel, "content": "x = 1\n"})
                self.assertFalse(result.ok)

    def test_raw_write_is_default_deny_and_explicit_opt_in_is_scoped(self) -> None:
        readonly = CodebaseTools(self.workspace)
        self.assertNotIn("fs_write", {tool.name for tool in readonly.list_tools()})
        denied = readonly.call("fs_write", {"path": "ok.py", "content": "x = 1\n"})
        self.assertFalse(denied.ok)
        self.assertFalse((self.workspace / "ok.py").exists())

        writable = CodebaseTools(self.workspace, allow_writes=True)
        allowed = writable.call("fs_write", {"path": "ok.py", "content": "x = 1\n"})
        self.assertTrue(allowed.ok)
        self.assertTrue((self.workspace / "ok.py").is_file())

    def test_opt_in_raw_write_breaks_hard_link_instead_of_mutating_outside(self) -> None:
        outside = self.base / "outside.py"
        outside.write_text("outside = True\n", encoding="utf-8")
        inside = self.workspace / "linked.py"
        try:
            os.link(outside, inside)
        except OSError as exc:
            self.skipTest(f"hard-link creation unavailable: {exc}")
        result = CodebaseTools(self.workspace, allow_writes=True).call(
            "fs_write", {"path": "linked.py", "content": "inside = True\n"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside = True\n")
        self.assertEqual(inside.read_text(encoding="utf-8"), "inside = True\n")

    def test_read_limit_is_validated_and_streamed(self) -> None:
        target = self.workspace / "large.txt"
        target.write_bytes(b"a" * 2_000_000)
        tools = CodebaseTools(self.workspace)
        limited = tools.call("fs_read", {"path": "large.txt", "max_bytes": 17})
        oversized = tools.call(
            "fs_read", {"path": "large.txt", "max_bytes": 1_000_001}
        )
        self.assertTrue(limited.ok)
        self.assertEqual(limited.content["bytes"], 17)
        self.assertFalse(oversized.ok)

    def test_symlink_or_reparse_escape_rejected(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        link = self.workspace / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        result = CodebaseTools(self.workspace, allow_writes=True).call(
            "fs_write", {"path": "link/pwn.py", "content": "x = 1\n"}
        )
        self.assertFalse(result.ok)
        self.assertFalse((outside / "pwn.py").exists())

    def test_unplanned_workspace_link_stops_staging(self) -> None:
        outside = self.base / "external.py"
        outside.write_text("external = True\n", encoding="utf-8")
        link = self.workspace / "external.py"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        ledger = MaxOpHarness(self.workspace).run(
            "safe link check",
            spec={"touch_files": ["out.py"], "required_api": ["run"]},
        )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertFalse((self.workspace / "out.py").exists())

    def test_api_abstain_preserves_existing_bytes(self) -> None:
        target = self.workspace / "mod.py"
        original = b"original = True\r\n"
        target.write_bytes(original)
        ledger = MaxOpHarness(self.workspace).run(
            "missing API",
            spec={"touch_files": ["mod.py"], "required_api": ["run", "health"]},
            body={"mod.py": "def run():\n    return 1\n"},
        )
        self.assertEqual(ledger["final"], "ABSTAIN")
        self.assertEqual(target.read_bytes(), original)

    def test_syntax_fail_and_lexicon_abstain_leave_no_new_file(self) -> None:
        bad = MaxOpHarness(self.workspace).run(
            "syntax candidate",
            spec={"touch_files": ["bad.py"], "required_api": ["run"]},
            body={"bad.py": "def run(\n"},
        )
        self.assertEqual(bad["final"], "FAIL")
        self.assertFalse((self.workspace / "bad.py").exists())

        abstain = MaxOpHarness(self.workspace).run(
            "breakthrough that proves everything",
            spec={"touch_files": ["claim.py"], "required_api": ["run"]},
        )
        self.assertEqual(abstain["final"], "ABSTAIN")
        self.assertFalse((self.workspace / "claim.py").exists())

    def test_partial_multifile_failure_applies_nothing(self) -> None:
        ledger = MaxOpHarness(self.workspace).run(
            "two files",
            spec={"touch_files": ["good.py", "bad.py"], "required_api": ["run"]},
            body={"good.py": "def run():\n    return 1\n", "bad.py": "def run(\n"},
        )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertFalse((self.workspace / "good.py").exists())
        self.assertFalse((self.workspace / "bad.py").exists())

    def test_second_replace_failure_rolls_back_first_file_and_directories(self) -> None:
        real_replace = os.replace
        second = self.workspace / "nested" / "two.py"

        def flaky_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            if Path(target) == second:
                raise OSError("injected second-target failure")
            real_replace(source, target)

        with patch("maxop_harness.transaction.os.replace", side_effect=flaky_replace):
            ledger = MaxOpHarness(self.workspace).run(
                "commit rollback",
                spec={
                    "touch_files": ["nested/one.py", "nested/two.py"],
                    "required_api": ["run"],
                },
            )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertFalse((self.workspace / "nested" / "one.py").exists())
        self.assertFalse(second.exists())
        self.assertFalse((self.workspace / "nested").exists())

    def test_rollback_failure_is_reported_as_uncertain(self) -> None:
        first = self.workspace / "one.py"
        first.write_text("original = True\n", encoding="utf-8")
        second = self.workspace / "two.py"
        real_replace = os.replace
        first_replacements = 0

        def fail_commit_and_restore(
            source: str | os.PathLike[str], target: str | os.PathLike[str]
        ) -> None:
            nonlocal first_replacements
            target_path = Path(target)
            if target_path == first:
                first_replacements += 1
                if first_replacements == 2:
                    raise OSError("injected restore failure")
            if target_path == second:
                raise OSError("injected second-target failure")
            real_replace(source, target)

        with patch("maxop_harness.transaction.os.replace", side_effect=fail_commit_and_restore):
            ledger = MaxOpHarness(self.workspace).run(
                "uncertain rollback",
                spec={"touch_files": ["one.py", "two.py"], "required_api": ["run"]},
            )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertIn("rollback_error", ledger)
        self.assertIn("one.py", ledger["rollback_error"])
        self.assertEqual(ledger["integrity_status"], "NEEDS_MANUAL_RECOVERY")
        persisted = json.loads(
            (self.workspace / ".maxop" / "ledger_latest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(persisted["integrity_status"], "NEEDS_MANUAL_RECOVERY")
        self.assertIn("one.py", persisted["rollback_error"])
        blocked = MaxOpHarness(self.workspace).run(
            "blocked pending recovery",
            spec={"touch_files": ["blocked.py"], "required_api": ["run"]},
        )
        self.assertEqual(blocked["final"], "FAIL")
        self.assertIn("lock_error", blocked)
        self.assertFalse((self.workspace / "blocked.py").exists())

    def test_gate_exception_and_live_drift_do_not_apply_candidate(self) -> None:
        original = self.workspace / "mod.py"
        original.write_text("old = True\n", encoding="utf-8")
        with patch("maxop_harness.loop.gate_syntax", side_effect=RuntimeError("gate crash")):
            ledger = MaxOpHarness(self.workspace).run(
                "gate crash",
                spec={"touch_files": ["mod.py"], "required_api": ["run"]},
            )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertEqual(original.read_text(encoding="utf-8"), "old = True\n")

        real_commit = WorkspaceTransaction.commit

        def drift_then_commit(transaction: WorkspaceTransaction) -> list[str]:
            original.write_text("concurrent = True\n", encoding="utf-8")
            return real_commit(transaction)

        with patch.object(WorkspaceTransaction, "commit", drift_then_commit):
            drift = MaxOpHarness(self.workspace).run(
                "drift",
                spec={"touch_files": ["mod.py"], "required_api": ["run"]},
            )
        self.assertEqual(drift["final"], "FAIL")
        self.assertEqual(original.read_text(encoding="utf-8"), "concurrent = True\n")

    def test_ledger_persistence_failure_rolls_back_successful_candidate(self) -> None:
        with patch("maxop_harness.loop.write_ledger", side_effect=OSError("disk full")):
            ledger = MaxOpHarness(self.workspace).run(
                "ledger failure",
                spec={"touch_files": ["new.py"], "required_api": ["run"]},
            )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertIn("ledger_path_error", ledger)
        self.assertFalse((self.workspace / "new.py").exists())

    def test_baseexception_during_compensating_rollback_retains_lock(self) -> None:
        with patch("maxop_harness.loop.write_ledger", side_effect=OSError("disk full")):
            with patch.object(
                WorkspaceTransaction,
                "rollback_committed",
                side_effect=KeyboardInterrupt("injected cancellation"),
            ):
                ledger = MaxOpHarness(self.workspace).run(
                    "rollback cancellation",
                    spec={"touch_files": ["uncertain.py"], "required_api": ["run"]},
                )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertEqual(ledger["integrity_status"], "NEEDS_MANUAL_RECOVERY")
        self.assertIn("KeyboardInterrupt", ledger["rollback_error"])
        self.assertTrue((self.workspace / ".maxop" / "transaction.lock").is_file())
        blocked = MaxOpHarness(self.workspace).run(
            "blocked after rollback cancellation",
            spec={"touch_files": ["blocked.py"], "required_api": ["run"]},
        )
        self.assertEqual(blocked["final"], "FAIL")
        self.assertIn("lock_error", blocked)

    def test_stage_cleanup_exception_still_releases_workspace_lock(self) -> None:
        real_exit = WorkspaceTransaction.__exit__

        def cleanup_then_raise(
            transaction: WorkspaceTransaction,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            real_exit(transaction, exc_type, exc, traceback)
            raise OSError("injected cleanup failure")

        with patch.object(
            WorkspaceTransaction,
            "__exit__",
            cleanup_then_raise,
        ):
            first = MaxOpHarness(self.workspace).run(
                "cleanup failure",
                spec={"touch_files": ["first.py"], "required_api": ["run"]},
            )
        self.assertEqual(first["final"], "DONE")
        self.assertIn("stage_cleanup_error", first)
        self.assertFalse((self.workspace / ".maxop" / "transaction.lock").exists())
        second = MaxOpHarness(self.workspace).run(
            "lock is available",
            spec={"touch_files": ["second.py"], "required_api": ["run"]},
        )
        self.assertEqual(second["final"], "DONE")

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics")
    def test_new_file_mode_respects_restrictive_umask(self) -> None:
        old_umask = os.umask(0o077)
        try:
            ledger = MaxOpHarness(self.workspace).run(
                "private generated file",
                spec={"touch_files": ["private.py"], "required_api": ["run"]},
            )
        finally:
            os.umask(old_umask)
        self.assertEqual(ledger["final"], "DONE")
        mode = stat.S_IMODE((self.workspace / "private.py").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_partial_state_write_restores_previous_ledger_and_candidate(self) -> None:
        first = MaxOpHarness(self.workspace).run(
            "first sealed run",
            spec={"touch_files": ["first.py"], "required_api": ["run"]},
        )
        self.assertEqual(first["final"], "DONE")
        latest = self.workspace / ".maxop" / "ledger_latest.json"
        previous = latest.read_bytes()
        real_replace = os.replace
        injected = False

        def fail_index_once(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            nonlocal injected
            if Path(target).name == "runs.jsonl" and not injected:
                injected = True
                raise OSError("injected index persistence failure")
            real_replace(source, target)

        with patch("maxop_harness.state.os.replace", side_effect=fail_index_once):
            second = MaxOpHarness(self.workspace).run(
                "second unsealed run",
                spec={"touch_files": ["second.py"], "required_api": ["run"]},
            )
        self.assertEqual(second["final"], "FAIL")
        self.assertFalse((self.workspace / "second.py").exists())
        self.assertEqual(latest.read_bytes(), previous)

    def test_uncertain_state_rollback_retains_recovery_lock(self) -> None:
        seed = MaxOpHarness(self.workspace).run(
            "state seed",
            spec={"touch_files": ["seed.py"], "required_api": ["run"]},
        )
        self.assertEqual(seed["final"], "DONE")
        real_replace = os.replace
        latest_replacements = 0
        index_failed = False

        def fail_index_and_latest_restore(
            source: str | os.PathLike[str], target: str | os.PathLike[str]
        ) -> None:
            nonlocal latest_replacements, index_failed
            target_path = Path(target)
            if target_path.name == "ledger_latest.json":
                latest_replacements += 1
                if latest_replacements == 2:
                    raise OSError("injected latest-ledger restore failure")
            if target_path.name == "runs.jsonl" and not index_failed:
                index_failed = True
                raise OSError("injected index write failure")
            real_replace(source, target)

        with patch("maxop_harness.state.os.replace", side_effect=fail_index_and_latest_restore):
            ledger = MaxOpHarness(self.workspace).run(
                "uncertain state",
                spec={"touch_files": ["candidate.py"], "required_api": ["run"]},
            )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertEqual(ledger["integrity_status"], "NEEDS_MANUAL_RECOVERY")
        self.assertIn("state persistence is uncertain", ledger["rollback_error"])
        self.assertFalse((self.workspace / "candidate.py").exists())
        self.assertTrue((self.workspace / ".maxop" / "transaction.lock").is_file())
        blocked = MaxOpHarness(self.workspace).run(
            "blocked after uncertain state",
            spec={"touch_files": ["blocked.py"], "required_api": ["run"]},
        )
        self.assertEqual(blocked["final"], "FAIL")
        self.assertIn("lock_error", blocked)

    def test_success_uses_full_hash_and_persisted_prereg(self) -> None:
        spec = {"touch_files": ["sealed.py"], "required_api": ["run"]}
        with patch.dict(
            os.environ,
            {"MAXOP_WORKSPACE": str(self.workspace), "MAXOP_ALLOW_RAW_WRITE": ""},
            clear=False,
        ):
            response = handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "harness_run",
                        "arguments": {
                            "goal": "sealed",
                            **spec,
                            "prereg_sha256": prereg_sha256("sealed", spec),
                        },
                    },
                }
            )
        assert response is not None
        returned = json.loads(response["result"]["content"][0]["text"])
        persisted = json.loads(
            (self.workspace / ".maxop" / "ledger_latest.json").read_text(encoding="utf-8")
        )
        digest = returned["content_hashes"]["sealed.py"]
        self.assertEqual(len(digest), 64)
        self.assertEqual(
            digest,
            hashlib.sha256((self.workspace / "sealed.py").read_bytes()).hexdigest(),
        )
        self.assertEqual(returned["prereg_sha256"], persisted["prereg_sha256"])
        self.assertEqual(returned["preregistration_mode"], "provided_frozen_digest")
        self.assertEqual(audit_ledger(self.workspace)["AUDIT"], "PASS")

    def test_mcp_rejects_retuning_after_preregistration(self) -> None:
        frozen_spec = {"touch_files": ["a.py"], "required_api": ["run"]}
        retuned_spec = {"touch_files": ["b.py"], "required_api": ["run"]}
        with patch.dict(
            os.environ,
            {"MAXOP_WORKSPACE": str(self.workspace), "MAXOP_ALLOW_RAW_WRITE": ""},
            clear=False,
        ):
            response = handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "harness_run",
                        "arguments": {
                            "goal": "frozen",
                            **retuned_spec,
                            "prereg_sha256": prereg_sha256("frozen", frozen_spec),
                        },
                    },
                }
            )
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        self.assertFalse((self.workspace / "a.py").exists())
        self.assertFalse((self.workspace / "b.py").exists())

    def test_mcp_raw_write_is_not_listed_or_callable_by_default(self) -> None:
        with patch.dict(
            os.environ,
            {"MAXOP_WORKSPACE": str(self.workspace), "MAXOP_ALLOW_RAW_WRITE": ""},
            clear=False,
        ):
            listed = handle(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            )
            called = handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "fs_write",
                        "arguments": {"path": "raw.py", "content": "x = 1\n"},
                    },
                }
            )
        assert listed is not None and called is not None
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertNotIn("fs_write", names)
        self.assertTrue(called["result"]["isError"])
        self.assertFalse((self.workspace / "raw.py").exists())

    def test_mcp_malformed_json_values_return_protocol_errors(self) -> None:
        not_an_object = handle([])
        bad_params = handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []}
        )
        bad_arguments = handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "harness_run", "arguments": []},
            }
        )
        assert not_an_object is not None
        assert bad_params is not None
        assert bad_arguments is not None
        self.assertEqual(not_an_object["error"]["code"], -32600)
        self.assertEqual(bad_params["error"]["code"], -32602)
        self.assertEqual(bad_arguments["error"]["code"], -32602)

    def test_state_override_is_confined_to_maxop(self) -> None:
        with patch.dict(os.environ, {"MAXOP_STATE_DIR": str(self.base / "outside")}, clear=False):
            with self.assertRaises(PermissionError):
                state_dir(self.workspace)
        with patch.dict(os.environ, {"MAXOP_STATE_DIR": "."}, clear=False):
            with self.assertRaises(PermissionError):
                state_dir(self.workspace)
        with patch.dict(os.environ, {"MAXOP_STATE_DIR": ".maxop/custom"}, clear=False):
            with self.assertRaises(PermissionError):
                state_dir(self.workspace)

    def test_concurrent_workspace_run_fails_closed_on_lock(self) -> None:
        with WorkspaceLock(self.workspace, "a" * 12):
            ledger = MaxOpHarness(self.workspace).run(
                "locked run",
                spec={"touch_files": ["locked.py"], "required_api": ["run"]},
            )
        self.assertEqual(ledger["final"], "FAIL")
        self.assertIn("lock_error", ledger)
        self.assertFalse((self.workspace / "locked.py").exists())

    def test_corrupt_and_malicious_ledgers_fail_closed(self) -> None:
        directory = state_dir(self.workspace)
        latest = directory / "ledger_latest.json"
        latest.write_text("{bad json", encoding="utf-8")
        self.assertEqual(audit_ledger(self.workspace)["AUDIT"], "FAIL")
        latest.write_text("[]", encoding="utf-8")
        self.assertEqual(audit_ledger(self.workspace)["AUDIT"], "FAIL")
        direct = audit_ledger(
            self.workspace,
            {
                "pin_version": "1",
                "final": "DONE",
                "content_hashes": {"../outside.py": "0" * 64},
            },
        )
        self.assertEqual(direct["AUDIT"], "FAIL")
        self.assertTrue(any(row["code"] == "UNSAFE_LEDGER_PATH" for row in direct["findings"]))

    def test_nested_malformed_ledger_values_never_crash_audit(self) -> None:
        sealed = MaxOpHarness(self.workspace).run(
            "audit seed",
            spec={"touch_files": ["seed.py"], "required_api": ["run"]},
        )
        self.assertEqual(sealed["final"], "DONE")
        malformed: list[dict[str, object]] = []
        bad_state = deepcopy(sealed)
        bad_state["states"][0] = {}
        malformed.append(bad_state)
        bad_verdict = deepcopy(sealed)
        bad_verdict["steps"][5]["verdicts"][0]["name"] = []
        malformed.append(bad_verdict)
        bad_spec = deepcopy(sealed)
        bad_spec["spec"]["touch_files"] = 1
        malformed.append(bad_spec)
        bad_hashes = deepcopy(sealed)
        bad_hashes["content_hashes"] = []
        malformed.append(bad_hashes)
        for index, candidate in enumerate(malformed):
            with self.subTest(index=index):
                self.assertEqual(audit_ledger(self.workspace, candidate)["AUDIT"], "FAIL")

    def test_audit_binds_sealed_files_to_preregistered_touch_set(self) -> None:
        sealed = MaxOpHarness(self.workspace).run(
            "file-set binding",
            spec={"touch_files": ["sealed.py"], "required_api": ["run"]},
        )
        self.assertEqual(sealed["final"], "DONE")
        forged = deepcopy(sealed)
        forged["spec"]["touch_files"] = ["other.py"]
        forged["prereg_sha256"] = prereg_sha256(forged["goal"], forged["spec"])
        result = audit_ledger(self.workspace, forged)
        self.assertEqual(result["AUDIT"], "FAIL")
        self.assertTrue(
            any(row["code"] == "SEALED_FILE_SET_MISMATCH" for row in result["findings"])
        )


if __name__ == "__main__":
    unittest.main()
