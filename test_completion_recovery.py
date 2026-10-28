"""Completed workers survive interruption until their outcomes are durably applied."""
import json
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

from test_concurrency import CommandFixture, ENGINE


class CompletionRecovery(CommandFixture):
    def setup_worker(self, stage):
        calls = self.base / "calls"
        source = self.project / "source.txt"
        source.write_text("good\n")
        worker = self.base / "worker.py"
        worker.write_text(
            "import json,pathlib,sys\n"
            "with pathlib.Path(sys.argv[1]).open('a') as f: f.write('called\\n')\n"
            "if len(sys.argv)>3:\n"
            " pathlib.Path(sys.argv[3]).write_text(json.dumps({'artifact-type':'dwitbuk/review@1','verdict':'accept','findings':[]}))\n"
            "else:\n"
            " sys.exit(0 if pathlib.Path(sys.argv[2]).read_text()=='good\\n' else 1)\n"
        )
        argv = [sys.executable, str(worker), str(calls), str(source)]
        if stage == "verify":
            (self.project / "hunsu.lock.json").write_text(json.dumps({"roles": {"verifier": argv + ["{response}"]}}))
            check = shlex.join([sys.executable, "-c", "pass"])
        else:
            check = shlex.join(argv)
        self.call("add", "a", "--role", "session", "--check", check, code=0)
        return calls, source

    def crash(self, stage, moment):
        injector = self.base / "crash-completion.py"
        injector.write_text(
            "import os,sys\n"
            "sys.path.insert(0,sys.argv[1])\n"
            "import chongdae as c\n"
            "suffix='a.'+sys.argv[3]+'.pending.json'\n"
            "if sys.argv[4]=='before-ack':\n"
            " original=c.retain_completion\n"
            " def retain(d,tid,path,*a,**kw):\n"
            "  original(d,tid,path,*a,**kw)\n"
            "  if str(path).endswith(suffix): os._exit(77)\n"
            " c.retain_completion=retain\n"
            "else:\n"
            " original=c.cleanup_completion_acks\n"
            " def cleanup(d,state):\n"
            "  if suffix in state.get('tasks',{}).get('a',{}).get('completion-acks',{}): os._exit(77)\n"
            "  original(d,state)\n"
            " c.cleanup_completion_acks=cleanup\n"
            "sys.exit(c.main(['run','a','--target',sys.argv[2]]))\n"
        )
        done = subprocess.run([sys.executable, str(injector), str(ENGINE.parent), str(self.project), stage, moment],
                              env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 77, done.stdout + done.stderr)
        path = next((self.project / ".chongdae").glob("run-*/local/a.%s.pending.json" % stage))
        pending = json.loads(path.read_text())
        self.assertEqual(pending["completed"]["token"], pending["launch"]["token"])
        return path

    def exercise_replay(self, stage, moment):
        calls, _ = self.setup_worker(stage)
        pending = self.crash(stage, moment)
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        self.call("run", "a", code=0)
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        self.assertEqual(self.task("a")["status"], "done")
        self.assertFalse(pending.exists())
        self.assertNotIn("completion-acks", self.task("a"), "local replay markers must stay out of the public record")

    def test_verifier_answer_replays_after_crash_before_acknowledgement(self):
        self.exercise_replay("verify", "before-ack")

    def test_verifier_acknowledgement_survives_crash_before_cleanup(self):
        self.exercise_replay("verify", "after-ack")

    def test_check_result_replays_after_crash_before_acknowledgement(self):
        self.exercise_replay("checks", "before-ack")

    def test_check_acknowledgement_survives_crash_before_cleanup(self):
        self.exercise_replay("checks", "after-ack")

    def test_recovered_verifier_answer_cannot_accept_changed_source(self):
        calls, source = self.setup_worker("verify")
        self.crash("verify", "before-ack")
        source.write_text("changed\n")
        self.call("run", "a", code=4)
        self.assertEqual(self.task("a")["status"], "todo")
        self.assertNotIn("review", self.task("a"))
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        self.call("run", "a", code=0)
        self.assertEqual(calls.read_text().splitlines(), ["called", "called"])

    def test_recovered_check_result_cannot_pass_changed_source(self):
        calls, source = self.setup_worker("checks")
        self.crash("checks", "before-ack")
        source.write_text("broken\n")
        self.call("run", "a", code=2)
        self.assertEqual(self.task("a")["status"], "todo")
        self.assertNotIn("checks-passed", self.task("a"))
        self.assertEqual(calls.read_text().splitlines(), ["called", "called"])

    def test_worker_without_response_is_not_repeated_before_outcome_is_retained(self):
        calls = self.base / "missing-response-calls"
        worker = self.base / "no-response.py"
        worker.write_text("from pathlib import Path\nwith Path(%r).open('a') as f: f.write('called\\n')\n" % str(calls))
        (self.project / "hunsu.lock.json").write_text(json.dumps({"roles": {"implementer": [sys.executable, str(worker)]}}))
        self.call("add", "a", "--check", shlex.join([sys.executable, "-c", "pass"]), code=0)
        injector = self.base / "crash-before-retain.py"
        injector.write_text(
            "import os,sys\nsys.path.insert(0,sys.argv[1])\nimport chongdae as c\n"
            "def crash(*a,**kw): os._exit(77)\nc.retain_completion=crash\n"
            "sys.exit(c.main(['run','a','--target',sys.argv[2]]))\n"
        )
        done = subprocess.run([sys.executable, str(injector), str(ENGINE.parent), str(self.project)],
                              env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 77, done.stdout + done.stderr)
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        self.call("run", "a", code=2)
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        self.assertEqual(self.task("a")["response"]["status"], "no-response")


if __name__ == "__main__":
    unittest.main(verbosity=2)
