"""A fresh reviewer must decide the source that actually reaches completion."""
import json
import shlex
import subprocess
import sys
import time
import unittest

from test_concurrency import CommandFixture


class ReviewFreshness(CommandFixture):
    def git(self, path, *args):
        # Git's optional index refresh in a concurrent status call can briefly
        # hold index.lock. This fixture retries that native Git contention only.
        for _ in range(50):
            result = subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
                                    cwd=path, capture_output=True, text=True)
            if result.returncode == 0:
                return
            if "index.lock" not in result.stderr:
                self.fail(result.stderr)
            time.sleep(0.02)
        self.fail(result.stderr)

    def install_verifier(self, after=None, gate=False):
        ready, release, calls = (self.base / n for n in ("review-ready", "review-release", "review-calls"))
        self.releases.append(release)
        script = self.base / "reviewer.py"
        script.write_text("import sys,pathlib,json,time\n"
                          "req=json.load(open(sys.argv[1])); b=pathlib.Path(sys.argv[3])\n"
                          "with open(b/'review-calls','a') as f: f.write((pathlib.Path(req['target'])/'a.py').read_text().strip()+'\\n')\n"
                          "(b/'review-ready').touch()\n"
                          "while not (b/'review-release').exists(): time.sleep(.02)\n"
                          "json.dump({'artifact-type':'dwitbuk/review@1','verdict':'accept','findings':[]},open(sys.argv[2],'w'))\n")
        (self.project / "hunsu.lock.json").write_text(json.dumps({"roles": {"verifier": [
            sys.executable, str(script), "{request}", "{response}", str(self.base)]}}))
        (self.project / "a.py").write_text("value = 1\n")
        self.git(self.project, "add", "a.py")
        self.git(self.project, "commit", "-qm", "initial source")
        options = (["--after", after] if after else []) + (["--gate", "human"] if gate else [])
        self.call("add", "a", "--scope", "a.py", "--check", shlex.join([sys.executable, "-c", "pass"]), *options, code=0)
        return ready, release, calls

    def assert_stale_then_fresh(self, proc, release, calls):
        release.touch()
        out, err = proc.communicate(timeout=12)
        self.assertEqual(proc.returncode, 4, out + err)
        self.assertIn("source changed", out)
        self.assertEqual(self.task("a")["status"], "todo")
        self.assertNotIn("review", self.task("a"))
        self.assertEqual(len(self.task("a")["invalidated-reviews"]), 1)
        self.call("run", "a", code=0)
        self.assertEqual(self.task("a")["status"], "done")
        self.assertEqual(len(calls.read_text().splitlines()), 2)

    def test_edit_during_review_does_not_complete_with_the_old_accept(self):
        ready, release, calls = self.install_verifier()
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        (self.project / "a.py").write_text("value = BROKEN\n")
        self.assert_stale_then_fresh(proc, release, calls)
        self.assertEqual(calls.read_text().splitlines(), ["value = 1", "value = BROKEN"])

    def test_committed_dependency_edit_during_review_is_still_a_change(self):
        ready, release, calls = self.install_verifier()
        dependency = self.project / "dependency.py"
        dependency.write_text("value = 1\n")
        self.git(self.project, "add", "dependency.py")
        self.git(self.project, "commit", "-qm", "dependency")
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        dependency.write_text("value = 2\n")
        self.git(self.project, "commit", "-qam", "concurrent dependency edit")
        self.assert_stale_then_fresh(proc, release, calls)
        self.assertIn("dependency.py", self.task("a")["invalidated-reviews"][0]["changed"])

    def test_committed_nested_edit_during_review_is_still_a_change(self):
        ready, release, calls = self.install_verifier()
        (self.project / ".gitignore").write_text("/engine/\n")
        nested = self.project / "engine"
        nested.mkdir()
        self.git(nested, "init", "-q")
        source = nested / "dependency.py"
        source.write_text("value = 1\n")
        self.git(nested, "add", "dependency.py")
        self.git(nested, "commit", "-qm", "dependency")
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        source.write_text("value = 2\n")
        self.git(nested, "commit", "-qam", "concurrent nested edit")
        self.assert_stale_then_fresh(proc, release, calls)
        self.assertIn("engine/dependency.py", self.task("a")["invalidated-reviews"][0]["changed"])

    def test_record_write_or_committing_identical_source_does_not_invalidate(self):
        ready, release, calls = self.install_verifier()
        # This edit precedes review. Committing it changes git's dirty set but
        # does not change a byte of the source the reviewer read.
        (self.project / "a.py").write_text("value = 2\n")
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        (self.project / ".chongdae" / "unrelated-record.json").write_text('{"observation":true}')
        self.git(self.project, "commit", "-qam", "same source, committed")
        release.touch()
        self.finish(proc)
        self.assertEqual(self.task("a")["status"], "done")
        self.assertNotIn("invalidated-reviews", self.task("a"))
        self.assertEqual(len(calls.read_text().splitlines()), 1)

    def test_pending_review_keeps_its_original_source_across_calls(self):
        ready, release, calls = self.install_verifier()
        self.env["CHONGDAE_WAIT"] = "1"
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        out, err = proc.communicate(timeout=8)
        self.assertEqual(proc.returncode, 4, out + err)
        (self.project / "a.py").write_text("value = 2\n")
        self.git(self.project, "commit", "-qam", "edit while review detached")
        release.touch()
        self.env["CHONGDAE_WAIT"] = "20"
        result = self.call("run", "a", code=4)
        self.assertIn("source changed", result.stdout)
        self.assertEqual(self.task("a")["status"], "todo")
        self.call("run", "a", code=0)
        self.assertEqual(len(calls.read_text().splitlines()), 2)

    def test_source_changed_during_initial_check_is_rechecked_before_done(self):
        source = self.project / "a.py"
        source.write_text("good\n")
        ready, release = self.base / "check-ready", self.base / "check-release"
        self.releases.append(release)
        script = self.base / "read-then-wait.py"
        script.write_text("import sys,pathlib,time\n"
                          "good=pathlib.Path(sys.argv[1]).read_text()=='good\\n'\n"
                          "pathlib.Path(sys.argv[2]).touch()\n"
                          "while not pathlib.Path(sys.argv[3]).exists(): time.sleep(.02)\n"
                          "sys.exit(0 if good else 1)\n")
        check = shlex.join([sys.executable, str(script), str(source), str(ready), str(release)])
        self.call("add", "a", "--check", check, code=0)
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        source.write_text("bad\n")
        self.git(self.project, "add", "a.py")
        self.git(self.project, "commit", "-qm", "concurrent committed source")
        release.touch()
        out, err = proc.communicate(timeout=12)
        self.assertEqual(proc.returncode, 2, out + err)
        self.assertEqual(self.task("a")["status"], "todo")
        self.assertNotIn("checks-passed", self.task("a"))

    def test_change_while_after_observer_runs_invalidates_checks_and_both_reviews(self):
        _, release, calls = self.install_verifier(after="observer")
        release.touch()   # the verifier accepts before the after observer starts
        ready, after_release, after_calls = (self.base / n for n in ("after-ready", "after-release", "after-calls"))
        self.releases.append(after_release)
        observer = self.base / "observer.py"
        observer.write_text("import sys,pathlib,json,time\n"
                            "r=json.load(open(sys.argv[1])); b=pathlib.Path(sys.argv[3])\n"
                            "with open(b/'after-calls','a') as f: f.write((pathlib.Path(r['target'])/'a.py').read_text().strip()+'\\n')\n"
                            "(b/'after-ready').touch()\n"
                            "while not (b/'after-release').exists(): time.sleep(.02)\n"
                            "json.dump({'status':'done','findings':[]},open(sys.argv[2],'w'))\n")
        lockfile = self.project / "hunsu.lock.json"
        lock = json.loads(lockfile.read_text())
        lock["roles"]["observer"] = [sys.executable, str(observer), "{request}", "{response}", str(self.base)]
        lockfile.write_text(json.dumps(lock))
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        (self.project / "a.py").write_text("value = 2\n")
        self.assert_stale_then_fresh(proc, after_release, calls)
        self.assertEqual(after_calls.read_text().splitlines(), ["value = 1", "value = 2"])
        self.assertIn("observer", self.task("a")["invalidated-reviews"][0]["after"])

    def test_dirty_recursive_submodule_work_is_part_of_the_reviewed_source(self):
        ready, release, calls = self.install_verifier()
        # Register local nested repos as gitlinks: this is the layout of an
        # initialized submodule without needing a remote clone or file transport.
        module = self.project / "module"
        module.mkdir()
        self.git(module, "init", "-q")
        nested = module / "nested"
        nested.mkdir()
        self.git(nested, "init", "-q")
        source = nested / "dependency.py"
        source.write_text("value = 1\n")
        self.git(nested, "add", "dependency.py")
        self.git(nested, "commit", "-qm", "dependency")
        self.git(module, "add", "nested")
        self.git(module, "commit", "-qm", "nested gitlink")
        self.git(self.project, "add", "module")
        self.git(self.project, "commit", "-qm", "gitlink")
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        source.write_text("value = 2\n")   # submodule HEAD remains unchanged
        self.assert_stale_then_fresh(proc, release, calls)
        self.assertIn("module/nested/dependency.py", self.task("a")["invalidated-reviews"][0]["changed"])

    def test_confirm_rejects_changed_produced_source_then_requires_fresh_run(self):
        _, release, calls = self.install_verifier(gate=True)
        release.touch()
        self.call("run", "a", code=2)
        self.assertEqual(self.task("a")["status"], "produced")
        (self.project / "a.py").write_text("value = 2\n")
        self.call("confirm", "a", "--by", "Test", code=2)
        self.assertEqual(self.task("a")["status"], "todo")
        self.assertNotIn("confirmed", self.task("a"))
        self.assertNotIn("review", self.task("a"))
        self.call("run", "a", code=2)
        self.call("confirm", "a", "--by", "Test", code=0)
        self.assertEqual(self.task("a")["status"], "done")
        self.assertEqual(len(calls.read_text().splitlines()), 2)

    def test_produced_run_rechecks_changed_source_before_repeating_the_human_gate(self):
        _, release, calls = self.install_verifier(gate=True)
        release.touch()
        self.call("run", "a", code=2)
        (self.project / "a.py").write_text("value = 2\n")
        self.call("run", "a", code=2)
        self.assertEqual(self.task("a")["status"], "todo")
        self.call("run", "a", code=2)
        self.assertEqual(self.task("a")["status"], "produced")
        self.assertEqual(len(calls.read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
