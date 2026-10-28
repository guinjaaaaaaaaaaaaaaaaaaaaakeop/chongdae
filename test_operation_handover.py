"""A replacement session can inspect an abandoned operation without replaying its effects."""
import json
import os
import subprocess
import sys
import unittest

import chongdae as c
import test_operation_recovery as recovery
from test_concurrency import CommandFixture, ENGINE


class OperationHandover(CommandFixture):
    crash = recovery.OperationRecovery.crash
    did = recovery.OperationRecovery.did
    pending = recovery.OperationRecovery.pending
    command = recovery.OperationRecovery.command

    def setUp(self):
        super().setUp()
        self.call("add", "a", "--brief", "local operation", code=0)
        self.calls = self.base / "effects"
        self.worker = self.base / "effect.py"
        self.worker.write_text("import pathlib,sys\nwith pathlib.Path(sys.argv[1]).open('a') as f: f.write(sys.argv[2]+'\\n')\n")

    def assert_handover(self, done=False):
        if done:
            self.call("run", "a", code=0)
        journal = self.crash("effect")
        pending_bytes = self.pending().read_bytes()
        before = self.task("a")
        self.env["CHONGDAE_SESSION"] = "replacement"
        self.did("--reconcile", journal["id"], "--why", "inspected", code=2)
        result = self.call("take", "a", "--why", "the previous session ended; inspect its interrupted operation", code=0)
        self.assertIn("recovery only", result.stdout)
        self.assertEqual(self.pending().read_bytes(), pending_bytes)
        after = self.task("a")
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after.get("attempts"), before.get("attempts"))
        self.assertEqual(after.get("response"), before.get("response"))
        self.assertEqual(after.get("did", []), before.get("did", []))
        self.assertEqual(after["handoffs"][-1]["purpose"], "operation-recovery")
        self.assertEqual(after["handoffs"][-1]["operation"], journal["id"])
        for argv in (("run", "a"), ("drop", "a", "--why", "done"), ("close", "--anyway", "--why", "done")):
            result = self.call(*argv)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.did("--reconcile", journal["id"], "--why", "effect file inspected; process ended", code=0)
        self.assertEqual(self.calls.read_text().splitlines(), ["one"])
        self.assertEqual(self.task("a")["status"], before["status"])
        self.assertEqual(self.task("a")["did"][-1]["outcome"], "unknown")

    def test_replacement_recovers_open_task_without_replaying(self):
        self.assert_handover()

    def test_replacement_recovers_done_task_without_reopening(self):
        self.assert_handover(done=True)

    def test_recovery_handover_also_supports_plan_tasks_without_local_def(self):
        task_path = next((self.project / ".chongdae").glob("run-*/tasks/a.json"))
        task = json.loads(task_path.read_text())
        plan_path = task_path.parent.parent / "plan.json"
        plan = json.loads(plan_path.read_text())
        plan["kind"] = "plan"
        plan["tasks"] = [task.pop("def")]
        plan_path.write_text(json.dumps(plan))
        task_path.write_text(json.dumps(task))
        self.assert_handover()

    def test_record_claim_owner_can_release_idle_operation_for_handover(self):
        self.env["CHONGDAE_USER"] = "bob"
        self.call("claim", "a", code=0)
        journal = self.crash("effect")
        self.env.update(CHONGDAE_SESSION="replacement", CHONGDAE_USER="test")
        self.call("take", "a", "--why", "recover", code=2)
        self.call("claim", "a", "--release", code=1)
        original_owner = dict(self.env, CHONGDAE_USER="bob", CHONGDAE_SESSION="parent")
        self.call("claim", "a", "--release", env=original_owner, code=0)
        self.call("take", "a", "--why", "original claimant released recovery", code=0)
        self.did("--reconcile", journal["id"], "--why", "effect checked", code=0)
        self.assertEqual(self.calls.read_text().splitlines(), ["one"])

    def test_recovery_handover_refuses_checks_live_operation_and_native_worker(self):
        journal = self.crash("effect")
        original = self.pending().read_bytes()
        before = self.task("a")
        self.env["CHONGDAE_SESSION"] = "replacement"
        marker = self.base / "checked"
        check = c.shlex.join([sys.executable, "-c", "from pathlib import Path; Path(%r).touch()" % str(marker)])
        for option in ("--checked", "--checked-red"):
            result = self.call("take", "a", "--why", "recover", option, check)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ownership only", result.stderr + result.stdout)
        self.assertFalse(marker.exists())
        journal["operation-pid"] = os.getpid()
        self.pending().write_text(json.dumps(journal))
        result = self.call("take", "a", "--why", "recover", code=2)
        self.assertIn("running process", result.stdout)
        self.pending().write_bytes(original)
        folder = self.pending().parent
        (folder / "a.verify.request.json").write_text(json.dumps({"task": "a"}))
        for pending in ({"native": True}, {"pid": os.getpid()}):
            (folder / "a.verify.pending.json").write_text(json.dumps(pending))
            result = self.call("take", "a", "--why", "recover", code=2)
            self.assertIn("work in flight", result.stdout)
        (folder / "a.verify.pending.json").unlink()
        self.assertEqual(self.task("a"), before)
        self.assertEqual(self.pending().read_bytes(), original)
        self.assertEqual(self.calls.read_text().splitlines(), ["one"])

    def test_expired_foreign_lease_is_reacquired_for_recovery(self):
        self.exercise_expired_lease_recovery()

    def test_plan_without_added_in_uses_live_and_expired_lease_ownership(self):
        task_path = next((self.project / ".chongdae").glob("run-*/tasks/a.json"))
        task = json.loads(task_path.read_text())
        run_dir = task_path.parent.parent
        plan_path = run_dir / "plan.json"
        plan = json.loads(plan_path.read_text())
        plan["kind"] = "plan"
        plan["tasks"] = [task.pop("def")]
        plan_path.write_text(json.dumps(plan))
        task_path.write_text(json.dumps(task))
        local_path = run_dir / "local" / "tasks" / "a.json"
        local = json.loads(local_path.read_text())
        local.pop("added-in", None)
        local_path.write_text(json.dumps(local))
        self.exercise_expired_lease_recovery()

    def exercise_expired_lease_recovery(self):
        config = self.project / "hunsu.json"
        config.write_text(json.dumps({"settings": {"chongdae": {"commit-records": False, "lease": "local", "lease-ttl": 60}}}))
        self.call("claim", "a", code=0)
        journal = self.crash("effect")
        before = self.pending().read_bytes()
        self.env["CHONGDAE_SESSION"] = "replacement"
        refused = self.call("take", "a", "--why", "recover", code=2)
        self.assertIn("held by another session", refused.stdout)
        self.assertEqual(self.pending().read_bytes(), before)
        argv = ["take", "a", "--why", "previous session ended and its hold expired", "--target", str(self.project)]
        script = "import sys,json;sys.path.insert(0,sys.argv[1]);import chongdae as c;clock=c.clock;c.clock=lambda:clock()+120;sys.exit(c.main(json.loads(sys.argv[2])))"
        result = subprocess.run([sys.executable, "-c", script, str(ENGINE.parent), json.dumps(argv)], env=self.env,
                                text=True, capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.pending().read_bytes(), before)
        self.did("--reconcile", journal["id"], "--why", "effect verified and no worker remains", code=0)
        self.assertEqual(self.calls.read_text().splitlines(), ["one"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
