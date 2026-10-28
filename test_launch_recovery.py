"""Crash injection at detached dispatch boundaries; only local fake workers are run."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

import chongdae
from test_concurrency import CommandFixture, ENGINE


class LaunchRecovery(CommandFixture):
    def exercise_crash(self, stage, moment):
        ready, release, calls = (self.base / n for n in ("ready", "release", "calls"))
        self.releases.append(release)
        worker = self.base / "worker.py"
        worker.write_text(
            "import json,pathlib,sys,time\n"
            "with pathlib.Path(sys.argv[1]).open('a') as f: f.write('started\\n')\n"
            "pathlib.Path(sys.argv[2]).touch()\n"
            "while not pathlib.Path(sys.argv[3]).exists(): time.sleep(.02)\n"
            "if len(sys.argv)>4: pathlib.Path(sys.argv[4]).write_text(json.dumps({'artifact-type':'dwitbuk/review@1','verdict':'accept','findings':[]}))\n"
        )
        argv = [sys.executable, str(worker), str(calls), str(ready), str(release)]
        if stage == "verify":
            (self.project / "hunsu.lock.json").write_text(json.dumps({"roles": {"verifier": argv + ["{response}"]}}))
            check = shlex.join([sys.executable, "-c", "pass"])
        else:
            check = shlex.join(argv)
        self.call("add", "a", "--role", "session", "--check", check, code=0)
        suffix = "a.%s.pending.json" % stage
        injector = self.base / "crash.py"
        injector.write_text(
            "import os,sys,subprocess\n"
            "sys.path.insert(0,sys.argv[1])\n"
            "import chongdae as c\n"
            "suffix=sys.argv[3]\n"
            "if sys.argv[4]=='before':\n"
            " original=c.save\n"
            " def save(path,data):\n"
            "  original(path,data)\n"
            "  if str(path).endswith(suffix): os._exit(77)\n"
            " c.save=save\n"
            "else:\n"
            " original=subprocess.Popen\n"
            " def popen(argv,*a,**kw):\n"
            "  p=original(argv,*a,**kw)\n"
            "  if '_launch' in argv and any(str(x).endswith(suffix) for x in argv): os._exit(77)\n"
            "  return p\n"
            " subprocess.Popen=popen\n"
            "sys.exit(c.main(['run','a','--target',sys.argv[2]]))\n"
        )
        crash = subprocess.run([sys.executable, str(injector), str(ENGINE.parent), str(self.project), suffix, moment],
                               env=self.env, text=True, capture_output=True, timeout=12)
        self.assertEqual(crash.returncode, 77, crash.stdout + crash.stderr)
        pending_path = next((self.project / ".chongdae").glob("run-*/local/" + suffix))
        pending = json.loads(pending_path.read_text())
        self.assertIn("token", pending["launch"])
        if moment == "before":
            self.assertEqual(pending["launch-state"], "launching")
            self.assertNotIn("pid", pending)
            self.assertFalse(ready.exists(), "the saved intent must precede worker creation")
        resumed = self.start("run", "a")
        self.wait_for(ready, resumed)
        self.assertEqual(calls.read_text().splitlines(), ["started"])
        # A delayed duplicate launcher can arrive even after another one registered; it must never exec again.
        delayed = subprocess.run([sys.executable, str(ENGINE), "_launch", str(pending_path), pending["launch"]["token"]],
                                 env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(delayed.returncode, 0, delayed.stdout + delayed.stderr)
        release.touch()
        self.finish(resumed)
        self.assertEqual(calls.read_text().splitlines(), ["started"])
        self.assertEqual(self.task("a")["status"], "done")
        self.assertFalse(pending_path.exists())

    def test_verifier_recovers_intent_saved_before_popen(self):
        self.exercise_crash("verify", "before")

    def test_verifier_recovers_parent_death_immediately_after_popen(self):
        self.exercise_crash("verify", "after")

    def test_checks_recover_intent_saved_before_popen(self):
        self.exercise_crash("checks", "before")

    def test_checks_recover_parent_death_immediately_after_popen(self):
        self.exercise_crash("checks", "after")

    def test_zero_and_negative_ids_are_not_workers(self):
        self.assertFalse(chongdae.pid_alive(0))
        self.assertFalse(chongdae.pid_alive(-1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
