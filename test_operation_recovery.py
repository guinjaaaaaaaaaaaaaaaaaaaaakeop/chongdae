"""Interrupted external operations must never be replayed automatically; local effects only."""
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import unittest

import chongdae
from test_concurrency import CommandFixture, ENGINE


class OperationRecovery(CommandFixture):
    def setUp(self):
        super().setUp()
        self.call("add", "a", "--brief", "local operation", code=0)
        self.calls = self.base / "effects"
        self.worker = self.base / "effect.py"
        self.worker.write_text("import pathlib,sys\nwith pathlib.Path(sys.argv[1]).open('a') as f: f.write(sys.argv[2]+'\\n')\n")

    def tearDown(self):
        for path in self.base.glob("**/*.did.pending.json"):
            pid = json.loads(path.read_text()).get("operation-pid")
            if pid and chongdae.pid_alive(pid):
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        super().tearDown()

    def command(self, label="one"):
        return [sys.executable, str(self.worker), str(self.calls), label]

    def did(self, *options, command=None, code=None):
        argv = [sys.executable, str(ENGINE), "did", "a", "--target", str(self.project), *options]
        if command:
            argv += ["--", *command]
        result = subprocess.run(argv, env=self.env, text=True, capture_output=True, timeout=12)
        if code is not None:
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def pending(self):
        return next((self.project / ".chongdae").glob("run-*/local/a.did.pending.json"))

    def crash(self, moment, command=None, batch=None, item=1):
        args = ["did", "a", "--target", str(self.project)]
        args += ["--each", str(batch)] if batch else ["--", *(command or self.command())]
        injector = self.base / "interrupt.py"
        injector.write_text(
            "import os,sys,json\nsys.path.insert(0,sys.argv[1])\nimport chongdae as c\n"
            "moment=sys.argv[2]; item=int(sys.argv[3]); original=c.save\n"
            "def save(path,data):\n"
            " original(path,data)\n"
            " if not str(path).endswith('a.did.pending.json'): return\n"
            " entry=data['items'][item-1]\n"
            " if moment=='intent' and entry.get('status')=='started' and 'operation-pid' not in data: os._exit(77)\n"
            " if moment=='result' and 'result' in entry: os._exit(77)\n"
            " if moment=='pid' and entry.get('status')=='started' and 'operation-pid' in data: os._exit(77)\n"
            " if moment=='published' and data.get('status')=='finished': os._exit(77)\n"
            "c.save=save\n"
            "if moment=='effect':\n"
            " run=c.operation_argv; n=0\n"
            " def operation(*a):\n"
            "  global n\n"
            "  result=run(*a); n+=1\n"
            "  if n==item: os._exit(77)\n"
            "  return result\n"
            " c.operation_argv=operation\n"
            "sys.exit(c.main(json.loads(sys.argv[4])))\n"
        )
        result = subprocess.run([sys.executable, str(injector), str(ENGINE.parent), moment, str(item), json.dumps(args)],
                                env=self.env, text=True, capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 77, result.stdout + result.stderr)
        return json.loads(self.pending().read_text())

    def reconcile(self, journal):
        return self.did("--reconcile", journal["id"], "--why", "inspected local effect file; no operation remains running", code=0)

    def test_effect_without_result_is_not_repeated_and_unknown_is_preserved(self):
        journal = self.crash("effect")
        self.did(command=self.command(), code=2)
        self.assertEqual(self.calls.read_text().splitlines(), ["one"])
        self.assertEqual(self.task("a").get("did", []), [])
        self.did("--reconcile", journal["id"], code=1)
        self.did("--reconcile", "wrong", "--why", "checked", code=1)
        self.reconcile(journal)
        rec = self.task("a")["did"][0]
        self.assertIsNone(rec["exit"])
        self.assertEqual(rec["outcome"], "unknown")
        self.assertIn("inspected local effect", rec["why"])
        self.assertFalse(list((self.project / ".chongdae").glob("run-*/local/*.did.pending.json")))
        report = self.call("report", code=0)
        findings = [f for f in json.loads(report.stdout)["findings"] if f["kind"] == "did"]
        self.assertIsNone(findings[0].get("layer"))   # findings without observation layer remain objections
        self.assertIn("outcome unknown", findings[0]["text"])
        self.assertIn("exit unknown", findings[0]["text"])

    def test_saved_result_is_published_once_without_repeating(self):
        self.crash("result")
        self.did(command=self.command(), code=2)
        self.assertEqual(self.calls.read_text().splitlines(), ["one"])
        self.assertEqual(len(self.task("a")["did"]), 1)
        self.assertEqual(self.task("a")["did"][0]["exit"], 0)

    def test_published_result_is_not_appended_again_on_recovery(self):
        self.crash("published")
        self.assertEqual(len(self.task("a")["did"]), 1)
        self.did(code=2)
        self.assertEqual(self.calls.read_text().splitlines(), ["one"])
        self.assertEqual(len(self.task("a")["did"]), 1)

    def test_interrupted_operation_on_done_task_still_blocks_run_and_close(self):
        self.call("run", "a", code=0)
        self.assertEqual(self.task("a")["status"], "done")
        journal = self.crash("effect")
        self.call("run", "a", code=2)
        self.call("close", "--anyway", "--why", "finish", code=2)
        self.reconcile(journal)

    def test_batch_preserves_prior_result_and_never_starts_remaining_items(self):
        batch = self.base / "batch.txt"
        batch.write_text("\n".join(shlex.join(self.command(x)) for x in ("one", "two", "three")))
        journal = self.crash("effect", batch=batch, item=2)
        self.assertEqual([r["exit"] for r in self.task("a")["did"]], [0])
        self.did("--each", str(batch), code=2)
        self.assertEqual(self.calls.read_text().splitlines(), ["one", "two"])
        recovered = self.reconcile(journal)
        self.assertIn("items never started: 3", recovered.stdout)
        records = self.task("a")["did"]
        self.assertEqual([r["exit"] for r in records], [0, None])
        self.assertEqual([r["batch"]["n"] for r in records], [1, 2])
        self.assertEqual(self.calls.read_text().splitlines(), ["one", "two"])

    def test_pre_execution_intent_is_conservatively_unknown_and_blocks_other_mutations(self):
        journal = self.crash("intent")
        self.assertFalse(self.calls.exists())
        self.did(command=self.command(), code=2)
        for args in (("run", "a"), ("take", "a", "--why", "handover"),
                     ("drop", "a", "--why", "cancel"), ("close", "--anyway", "--why", "finish")):
            result = self.call(*args, code=2)
            self.assertTrue("operation" in result.stdout, result.stdout)
        self.assertEqual(self.task("a")["status"], "todo")
        self.reconcile(journal)
        self.assertFalse(self.calls.exists())

    def test_live_operation_cannot_be_reconciled_as_finished(self):
        ready, release = self.base / "ready", self.base / "release"
        self.releases.append(release)
        self.worker.write_text("import pathlib,sys,time\npathlib.Path(sys.argv[1]).touch()\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(.02)\n")
        journal = self.crash("pid", command=[sys.executable, str(self.worker), str(ready), str(release)])
        until = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < until:
            time.sleep(.02)
        self.assertTrue(ready.exists())
        result = self.did("--reconcile", journal["id"], "--why", "checked", code=2)
        self.assertIn("still has a running process", result.stdout)
        release.touch()
        until = time.monotonic() + 5
        while chongdae.pid_alive(journal["operation-pid"]) and time.monotonic() < until:
            time.sleep(.02)
        self.reconcile(journal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
