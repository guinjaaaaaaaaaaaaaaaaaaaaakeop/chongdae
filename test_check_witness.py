"""Contract C: a verdict stands on what it decided on, a check is not run twice on one tree, and check evidence keeps the answer.

Found in a sibling project's day of real work, where more than half of the session's active time was spent blocked in
`chongdae run`: a verifier's accept of one task was thrown away because, while it read, the session edited a file inside
another open task's `--scope` (a file `run` itself said was left for that task); the same check command was run once per
task, serialized, on a tree that had not changed between them; and a check's record kept as its tail six lines of
`sys:1: ResourceWarning: unclosed file <…>` and no summary.

C1 — a verdict is voided only by a change to what it decided on; a change elsewhere in the source tree reruns the checks
and keeps the verdict. C2 — one check command, one tree, one run: an earlier pass in this run on an identical tree is
reused, never a failure, a `--checked-red` run, a `repeat-checks` task, another run's or another tree's. C3 — every check
record carries `summary`/`failures`, the tail leaves interpreter warnings out, and the common runners' summaries are
recognized. C4 — the README says so.

Every test goes through the CLI the way a session meets it — a temporary git project, fake verifiers and checks that are
small scripts (the checks' counters kept outside the project), no network, no model — except the direct calls of
`kept_tail` and `checked_results` the contract names. Run with ``python3 -m unittest test_check_witness``.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from test_chongdae import Project, run, write, UNCOMMITTED
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PASS_CHECK = shlex.join([PY, "-c", "pass"])
BLOCKED = {"status": "blocked", "summary": "the worker could not finish here", "verified": [], "decisions": [], "non-claims": []}
RECORDS = {"record-paths": {"model": ["model/"]}}
WARNING = "sys:1: ResourceWarning: unclosed file <_io.TextIOWrapper name=63 encoding='UTF-8'>"

# a check: appends one line to the counter file beside it (outside the project; never an argument, so the check's recorded
# outside files do not change when it runs) and exits 0 — or, with `fail-first`, exits 1 on its first call and 0 after (a
# flaky test, a service not yet up: the machine's, not the tree's)
COUNTER_CHECK = textwrap.dedent("""\
    import os, sys
    counter = os.path.join(os.path.dirname(os.path.abspath(__file__)), "counter")
    with open(counter, "a", encoding="utf-8") as fh:
        fh.write("ran\\n")
    n = sum(1 for _ in open(counter, encoding="utf-8"))
    print("Ran 1 test in 0.001s")
    print("")
    if len(sys.argv) > 1 and sys.argv[1] == "fail-first" and n == 1:
        print("FAILED (failures=1)")
        sys.exit(1)
    if len(sys.argv) > 1 and sys.argv[1] == "needs-b" and open(sys.argv[2], encoding="utf-8").read() != "b = 1\\n":
        print("FAILED (failures=1)")
        sys.exit(1)
    if len(sys.argv) > 1 and sys.argv[1] == "slow":
        import time
        time.sleep(float(sys.argv[2]))
    print("OK")
    """)

# a unittest-style run whose interpreter prints six ResourceWarning lines at exit
NOISY_CHECK = textwrap.dedent("""\
    import sys
    sys.stderr.write("...\\n")
    sys.stderr.write("----------------------------------------------------------------------\\n")
    sys.stderr.write("Ran 3 tests in 0.01s\\n")
    sys.stderr.write("\\n")
    sys.stderr.write("OK\\n")
    for _ in range(6):
        sys.stderr.write(%r + "\\n")
    """ % WARNING)


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True)


def readme(*parts):
    with open(os.path.join(HERE, "plugin", *parts), encoding="utf-8") as fh:
        return fh.read()


class Base(unittest.TestCase):
    """A temporary git project with a base commit, the fakes directory ignored; a directory outside it for counters."""

    def setUp(self):
        self.pj = Project()
        self.pj.__enter__()
        self.dir = self.pj.dir
        self.addCleanup(self.pj.__exit__, None, None, None)
        self.outside = tempfile.mkdtemp(prefix="chongdae-witness-")
        self.addCleanup(shutil.rmtree, self.outside, True)
        for key in ("CHONGDAE_USER",):
            old = os.environ.pop(key, None)
            if old is not None:
                self.addCleanup(os.environ.__setitem__, key, old)
        old_budget = c.WAIT_BUDGET
        self.addCleanup(setattr, c, "WAIT_BUDGET", old_budget)
        self.checker = os.path.join(self.outside, "count.py")
        write(self.checker, COUNTER_CHECK)
        self.counter = os.path.join(self.outside, "counter")

    # -- the project ----------------------------------------------------------------------------------------------------

    def prepare(self, roles, files=(("a.py", "a = 0\n"), ("b.py", "b = 0\n")), **more):
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        write(os.path.join(self.dir, ".gitignore"), "fakes/\n")
        write(os.path.join(self.dir, "hunsu.lock.json"), {"roles": roles, **more})
        for path, text in files:
            write(os.path.join(self.dir, path), text)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "base")
        code, out = self.cli("init", "--session", "--goal", "g")
        self.assertEqual(code, 0, out)

    def cli(self, *argv):
        return run(*argv, "--target", self.dir)

    def put(self, path, text):
        write(os.path.join(self.dir, path), text)

    def task(self, tid):
        tasks = self.pj.state()["tasks"]
        self.assertIn(tid, tasks, "no task %s in the run: %s" % (tid, sorted(tasks)))
        return tasks[tid]

    def add(self, tid, *more):
        code, out = self.cli("add", tid, "--brief", "the work of %s" % tid, *more)
        self.assertEqual(code, 0, out)

    # -- the checks -----------------------------------------------------------------------------------------------------

    def count_command(self, *extra):
        """The shared check command: the counter script outside the project, its counter beside it."""
        return shlex.join([PY, self.checker, *extra])

    def runs(self):
        if not os.path.exists(self.counter):
            return 0
        with open(self.counter, encoding="utf-8") as fh:
            return sum(1 for _ in fh)

    def check_record(self, tid, i=0):
        ts = self.task(tid)
        self.assertIn("checks-passed", ts, "%s keeps no checks-passed: %s" % (tid, sorted(ts)))
        ran = ts["checks-passed"].get("ran") or []
        self.assertGreater(len(ran), i, ts["checks-passed"])
        return ran[i]

    # -- the verifier ---------------------------------------------------------------------------------------------------

    def fake_verifier(self, edit=None, when_task=None, sleep=0):
        """A verifier command: copies every request it gets to `seen.jsonl` beside it (the run's local/), optionally sleeps,
        and — when asked about `when_task` (any task when None) — edits one file under the request's target once
        (`edit` = (path, text)); then accepts."""
        script = os.path.join(self.dir, "fakes", "eyes.py")
        write(script,
              "import json, os, sys, time\n"
              "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
              "with open(os.path.join(os.path.dirname(sys.argv[1]), 'seen.jsonl'), 'a', encoding='utf-8') as fh:\n"
              "    fh.write(json.dumps(req) + '\\n')\n"
              "time.sleep(%r)\n"
              "edit, when = json.loads(%r), %r\n"
              "if edit and (when is None or req.get('task') == when):\n"
              "    path = os.path.join(req['target'], edit[0])\n"
              "    if not os.path.exists(path) or open(path, encoding='utf-8').read() != edit[1]:\n"
              "        open(path, 'w', encoding='utf-8').write(edit[1])\n"
              "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept', 'findings': []}, open(sys.argv[2], 'w', encoding='utf-8'))\n"
              % (sleep, json.dumps(list(edit) if edit else None), when_task))
        return [PY, script, "{request}", "{response}"]

    def seen(self, tid=None):
        path = os.path.join(c.run_dir(self.dir), "local", "seen.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            reqs = [json.loads(line) for line in fh if line.strip()]
        return [r for r in reqs if tid is None or r.get("task") == tid]

    def blocked_provider(self):
        script = os.path.join(self.dir, "fakes", "blocked.py")
        write(script, "import json, sys\njson.dump(json.loads(%r), open(sys.argv[2], 'w', encoding='utf-8'))\n" % json.dumps(BLOCKED))
        return [PY, script, "{request}", "{response}"]

    # -- two open session tasks, alpha (a.py) and beta (b.py) -----------------------------------------------------------

    def two_tasks(self, verifier, alpha_check=None, beta_check=PASS_CHECK, gate=()):
        self.prepare({"verifier": verifier})
        self.add("alpha", "--scope", "a.py", "--check", alpha_check or PASS_CHECK, "--allow-outside", *gate)
        self.add("beta", "--scope", "b.py", "--check", beta_check, "--allow-outside")
        self.put("a.py", "a = 1\n")
        self.put("b.py", "b = 1\n")


# ====================================================================== C1: a verdict is voided only by what it decided on

class C1_VerdictWitness(Base):

    def test_C1_1_a_change_in_another_open_tasks_scope_while_the_verifier_reads_does_not_void_the_verdict(self):
        """The verifier, while answering alpha's request, edits b.py — a file beta's `--scope` holds and alpha's does not:
        alpha is finished on that one verdict, no second request, no invalidated review."""
        self.two_tasks(self.fake_verifier(edit=("b.py", "b = 2\n"), when_task="alpha"))
        code, out = self.cli("run", "alpha")
        self.assertEqual(len(self.seen("alpha")), 1, "the verifier was asked about alpha %d times:\n%s" % (len(self.seen("alpha")), out))
        ts = self.task("alpha")
        self.assertNotIn("invalidated-reviews", ts, "a change in beta's scope voided alpha's verdict: %s\n%s" % (ts.get("invalidated-reviews"), out))
        self.assertEqual(code, 0, out)
        self.assertEqual(ts["status"], "done", out)
        self.assertEqual((ts.get("review") or {}).get("verdict"), "accept", ts.get("review"))

    def test_C1_1_a_change_to_the_tasks_own_file_while_the_verifier_reads_still_voids_it(self):
        """Kept as today: the verifier edits a.py, alpha's own file — invalidated, and the next `run alpha` asks again."""
        self.two_tasks(self.fake_verifier(edit=("a.py", "a = 2\n"), when_task="alpha"))
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, c.WAITING, "a verdict on older source of alpha's own file completed it:\n" + out)
        ts = self.task("alpha")
        self.assertTrue(ts.get("invalidated-reviews"), sorted(ts))
        self.assertIn("a.py", ts["invalidated-reviews"][0].get("changed") or [], ts["invalidated-reviews"])
        self.assertNotEqual(ts["status"], "done")
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.seen("alpha")), 2, "fresh eyes were not asked")
        self.assertEqual(self.task("alpha")["status"], "done")

    def test_C1_1_a_change_to_a_file_no_scope_holds_while_the_verifier_reads_still_voids_it(self):
        """Kept as today: the verifier writes c.py, a file no open task's scope holds — invalidated, asked again."""
        self.two_tasks(self.fake_verifier(edit=("c.py", "c = 1\n"), when_task="alpha"))
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, c.WAITING, "a verdict on older source completed alpha:\n" + out)
        ts = self.task("alpha")
        self.assertTrue(ts.get("invalidated-reviews"), sorted(ts))
        self.assertIn("c.py", ts["invalidated-reviews"][0].get("changed") or [], ts["invalidated-reviews"])
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.seen("alpha")), 2)

    def test_C1_1_the_left_out_entries_are_fixed_with_the_witness_so_the_other_tasks_finish_does_not_void_it(self):
        """alpha waits at a human gate after a verdict the verifier gave while editing b.py (beta's); beta is then finished.
        b.py now lies in no open task's scope, yet alpha's verdict stood on a witness that left it out when it was asked:
        the confirm finishes alpha on that verdict."""
        self.two_tasks(self.fake_verifier(edit=("b.py", "b = 2\n"), when_task="alpha"), gate=("--gate", "human"))
        code, out = self.cli("run", "alpha")
        ts = self.task("alpha")
        self.assertNotIn("invalidated-reviews", ts, out)
        self.assertEqual(ts["status"], "produced", out)
        code, out = self.cli("run", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("beta")["status"], "done", out)
        code, out = self.cli("confirm", "alpha", "--by", "kim")
        self.assertEqual(code, 0, "finishing beta voided alpha's verdict:\n" + out)
        ts = self.task("alpha")
        self.assertEqual(ts["status"], "done")
        self.assertNotIn("invalidated-reviews", ts)
        self.assertEqual(len(self.seen("alpha")), 1)

    def test_C1_1_a_change_in_another_tasks_scope_after_produced_and_before_the_gate_keeps_the_verdict(self):
        """alpha is produced (gate human) on one verdict; the session then edits b.py (beta's). The checks may run again
        before alpha is done, but its verdict stands: no second verifier request, no invalidated review."""
        self.two_tasks(self.fake_verifier(), gate=("--gate", "human"))
        code, out = self.cli("run", "alpha")
        self.assertEqual(self.task("alpha")["status"], "produced", out)
        self.put("b.py", "b = 3\n")
        code, out = self.cli("confirm", "alpha", "--by", "kim")
        if self.task("alpha")["status"] != "done":
            code, out = self.cli("run", "alpha")
            if self.task("alpha")["status"] == "produced":
                code, out = self.cli("confirm", "alpha", "--by", "kim")
        ts = self.task("alpha")
        self.assertNotIn("invalidated-reviews", ts, "an edit of beta's file voided alpha's verdict: %s\n%s" % (ts.get("invalidated-reviews"), out))
        self.assertEqual(len(self.seen("alpha")), 1, "the verifier was asked about alpha again:\n" + out)
        self.assertEqual(ts["status"], "done", out)

    def test_C1_1_a_record_inside_the_tasks_own_scope_written_while_the_verifier_reads_still_voids_it(self):
        """Kept as today: alpha's scope names model/, and the verifier writes a record there — a reviewed file changed."""
        self.prepare({"verifier": self.fake_verifier(edit=("model/x.json", "{\"v\": 2}\n"), when_task="alpha")},
                     files=(("a.py", "a = 0\n"), ("b.py", "b = 0\n"), ("model/x.json", "{\"v\": 0}\n")), **RECORDS)
        self.add("alpha", "--scope", "a.py", "--scope", "model", "--check", PASS_CHECK)
        self.add("beta", "--scope", "b.py", "--check", PASS_CHECK)
        self.put("a.py", "a = 1\n")
        self.put("model/x.json", "{\"v\": 1}\n")
        self.put("b.py", "b = 1\n")
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, c.WAITING, out)
        self.assertTrue(self.task("alpha").get("invalidated-reviews"), out)

    def test_C1_2_checks_run_again_and_the_verdict_is_kept_when_only_another_tasks_file_changed(self):
        """alpha has a check (a counter outside the project); the verifier edits b.py while reading alpha: the tree the check
        passed on is gone, so the check runs again — twice in all — and the verifier is still asked only once."""
        self.two_tasks(self.fake_verifier(edit=("b.py", "b = 2\n"), when_task="alpha"), alpha_check=self.count_command())
        code, out = self.cli("run", "alpha")
        self.assertEqual(len(self.seen("alpha")), 1, "the verifier was asked about alpha again:\n" + out)
        self.assertNotIn("invalidated-reviews", self.task("alpha"), out)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("alpha")["status"], "done", out)
        self.assertEqual(self.runs(), 2, "the check did not run again on the changed tree (counter %d):\n%s" % (self.runs(), out))

    def test_C1_2_checks_that_fail_after_the_other_tasks_change_stop_the_task_for_its_checks(self):
        """The same, with alpha's check reading b.py and failing once the verifier changed it: alpha stops for its checks
        (a decision for the session), not for a stale verdict, and the verifier is not asked again."""
        b = os.path.join(self.dir, "b.py")
        self.two_tasks(self.fake_verifier(edit=("b.py", "b = 2\n"), when_task="alpha"), alpha_check=self.count_command("needs-b", b))
        code, out = self.cli("run", "alpha")
        self.assertEqual(len(self.seen("alpha")), 1, out)
        self.assertNotIn("invalidated-reviews", self.task("alpha"), out)
        self.assertEqual(code, c.DECISION, "alpha did not stop for its failing checks:\n" + out)
        ts = self.task("alpha")
        self.assertNotEqual(ts["status"], "done")
        self.assertNotIn("checks-passed", ts)
        self.assertEqual(self.runs(), 2, out)

    def test_C1_3_a_pending_verifiers_still_working_line_says_what_voids_the_verdict(self):
        """A verifier that sleeps past the call's budget: `still working:` names beta (or b.py) as not voiding alpha's verdict
        and says a change to alpha's own files does; the next call finishes alpha."""
        self.two_tasks(self.fake_verifier(sleep=3))
        c.WAIT_BUDGET = 1
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, c.WAITING, out)
        lines = [l for l in out.splitlines() if l.startswith("still working:")]
        self.assertTrue(lines, out)
        said = " ".join(out.split())
        self.assertTrue("beta" in said or "b.py" in said, "the still-working line does not name the other open task's scope:\n" + out)
        self.assertRegex(said, r"(?i)\bvoid", "the still-working line does not say what voids the verdict:\n" + out)
        self.assertRegex(said, r"(?i)alpha'?s? own files|own files", "it does not say a change to alpha's own files voids it:\n" + out)
        self.assertRegex(said, r"(?i)(do(es)? not|never|n't) void", "it does not say which changes do not void it:\n" + out)
        time.sleep(3)
        c.WAIT_BUDGET = 30
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("alpha")["status"], "done")
        self.assertEqual(len(self.seen("alpha")), 1)

    def test_C1_3_a_pending_checks_still_working_line_says_a_change_while_they_run_reruns_them(self):
        self.two_tasks(self.fake_verifier(), alpha_check=self.count_command("slow", "3"))
        c.WAIT_BUDGET = 1
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, c.WAITING, out)
        said = " ".join(out.split())
        self.assertIn("its checks", said, out)
        self.assertRegex(said, r"(?i)any change[^.;]*(source|tree)[^.;]*(run|rerun)s?[^.;]*again|any change[^.;]*rerun",
                         "the checks' still-working line does not say a change while they run reruns them:\n" + out)
        time.sleep(3)
        c.WAIT_BUDGET = 30
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)


# ====================================================================== C2: one check command, one tree, one run

class C2_OneRunPerTree(Base):

    def same_check_pair(self, *beta_more, roles=None, **more):
        self.prepare(roles or {}, **more)
        cmd = self.count_command()
        self.add("alpha", "--scope", "a.py", "--check", cmd, "--allow-outside")
        self.add("beta", "--scope", "b.py", "--check", cmd, "--allow-outside", *beta_more)
        self.put("a.py", "a = 1\n")
        self.put("b.py", "b = 1\n")
        return cmd

    def assert_reused_from(self, tid, source, out, cmd):
        rec = self.check_record(tid)
        self.assertIn("reused", rec, "%s's check record does not say it was reused: %s" % (tid, rec))
        self.assertEqual(rec["reused"].get("task"), source, rec["reused"])
        self.assertTrue(rec["reused"].get("at"), rec["reused"])
        lines = [l for l in out.splitlines() if l.startswith("  %s: " % tid) and "reused" in l and "not run again" in l]
        self.assertTrue(lines, "run's output does not say %s's check was reused and not run again:\n%s" % (tid, out))
        self.assertIn("(%s)" % source, lines[0], lines[0])
        self.assertIn("identical tree", lines[0], lines[0])

    def test_C2_1_two_tasks_sharing_one_command_on_one_tree_run_it_once(self):
        cmd = self.same_check_pair()
        code, out = self.cli("run", "alpha", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("alpha")["status"], "done", out)
        self.assertEqual(self.task("beta")["status"], "done", out)
        self.assertEqual(self.runs(), 1, "the same command ran %d times on one tree:\n%s" % (self.runs(), out))
        self.assertNotIn("reused", self.check_record("alpha"))
        self.assert_reused_from("beta", "alpha", out, cmd)

    def test_C2_1_one_run_call_after_another_with_no_change_between_reuses_the_pass(self):
        cmd = self.same_check_pair()
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        code, out = self.cli("run", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 1, "the same command ran again on an unchanged tree:\n" + out)
        self.assert_reused_from("beta", "alpha", out, cmd)

    def test_C2_2_a_source_change_between_runs_the_command_again(self):
        self.same_check_pair()
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.put("c.py", "c = 1\n")
        code, out = self.cli("run", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, "a pass on another tree was reused:\n" + out)
        self.assertNotIn("reused", self.check_record("beta"))
        # and the next task on this (new, unchanged) tree reuses beta's pass
        self.add("gamma", "--check", self.count_command(), "--allow-outside")
        code, out = self.cli("run", "gamma")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, out)
        self.assertEqual((self.check_record("gamma").get("reused") or {}).get("task"), "beta")

    def test_C2_2_a_record_file_change_between_runs_the_command_again(self):
        self.same_check_pair(**RECORDS)
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.put("model/x.json", "{\"v\": 1}\n")
        code, out = self.cli("run", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, "a pass on a tree with another record file was reused:\n" + out)
        self.assertNotIn("reused", self.check_record("beta"))
        self.add("gamma", "--check", self.count_command(), "--allow-outside")
        code, out = self.cli("run", "gamma")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, out)
        self.assertEqual((self.check_record("gamma").get("reused") or {}).get("task"), "beta")

    def test_C2_2_a_failed_check_is_run_again_on_the_same_tree(self):
        """A check that fails on its first call and passes on its second: `run alpha` twice runs it twice on one tree and
        alpha is done; beta, on the same tree, then reuses the pass and never the failure."""
        self.prepare({})
        cmd = self.count_command("fail-first")
        self.add("alpha", "--scope", "a.py", "--check", cmd, "--allow-outside")
        self.add("beta", "--scope", "b.py", "--check", cmd, "--allow-outside")
        self.put("a.py", "a = 1\n")
        self.put("b.py", "b = 1\n")
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, c.DECISION, out)
        self.assertEqual(self.runs(), 1)
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, "the failure was not run again:\n" + out)
        self.assertEqual(self.task("alpha")["status"], "done")
        code, out = self.cli("run", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, out)
        self.assertEqual((self.check_record("beta").get("reused") or {}).get("task"), "alpha")

    def test_C2_2_a_task_with_repeat_checks_always_runs_its_command(self):
        """alpha, beta (`--repeat-checks`) and gamma share one command on one tree: alpha runs it, beta runs it again,
        gamma reuses a pass — two runs in all."""
        self.same_check_pair("--repeat-checks")
        self.add("gamma", "--check", self.count_command(), "--allow-outside")
        code, out = self.cli("run", "alpha", "beta", "gamma")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, "counter %d: beta's repeat or gamma's reuse is wrong:\n%s" % (self.runs(), out))
        self.assertNotIn("reused", self.check_record("beta"))
        self.assertIn("reused", self.check_record("gamma"))

    def test_C2_2_a_checked_run_at_take_is_reused_by_the_tasks_own_check_on_the_same_tree(self):
        self.prepare({"implementer": self.blocked_provider()})
        cmd = self.count_command()
        self.add("alpha", "--role", "implementer", "--check", cmd, "--allow-outside")
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        self.put("a.py", "a = 1\n")
        code, out = self.cli("take", "alpha", "--why", "the worker could not finish here", "--checked", cmd)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 1, out)
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("alpha")["status"], "done", out)
        self.assertEqual(self.runs(), 1, "the task's own check ran again after the identical `--checked` run:\n" + out)
        self.assert_reused_from("alpha", "--checked", out, cmd)

    def test_C2_2_a_checked_red_run_is_never_reused(self):
        """A `--checked-red` run that happens to pass is not a pass to reuse: the task's own check runs. The task's own pass
        is then reused by another task on the same tree."""
        self.prepare({"implementer": self.blocked_provider()})
        cmd = self.count_command()
        self.add("alpha", "--role", "implementer", "--check", cmd, "--allow-outside")
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        self.put("a.py", "a = 1\n")
        self.cli("take", "alpha", "--why", "the worker could not finish here", "--checked-red", cmd)
        before = self.runs()
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), before + 1, "a --checked-red run was reused as a pass:\n" + out)
        self.assertNotIn("reused", self.check_record("alpha"))
        self.add("beta", "--role", "session", "--why", "latency: the session runs it itself", "--check", cmd, "--allow-outside")
        code, out = self.cli("run", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), before + 1, out)
        self.assertEqual((self.check_record("beta").get("reused") or {}).get("task"), "alpha")

    def test_C2_2_a_result_from_another_run_is_never_reused(self):
        self.prepare({})
        cmd = self.count_command()
        self.add("alpha", "--check", cmd, "--allow-outside")
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 1)
        code, out = self.cli("close", *UNCOMMITTED)
        self.assertEqual(code, 0, out)
        code, out = self.cli("init", "--session", "--goal", "g2")
        self.assertEqual(code, 0, out)
        self.add("beta", "--check", cmd, "--allow-outside")
        self.add("gamma", "--check", cmd, "--allow-outside")
        code, out = self.cli("run", "beta", "gamma")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 2, "counter %d: another run's pass was reused, or this run's was not:\n%s" % (self.runs(), out))
        self.assertNotIn("reused", self.check_record("beta"))
        self.assertEqual((self.check_record("gamma").get("reused") or {}).get("task"), "beta")

    def test_C2_3_the_verifiers_request_carries_the_reused_result_under_checked(self):
        self.same_check_pair(roles={"verifier": self.fake_verifier()})
        code, out = self.cli("run", "alpha", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(), 1, out)
        reqs = self.seen("beta")
        self.assertEqual(len(reqs), 1, out)
        checked = reqs[0].get("checked") or []
        hits = [r for r in checked if isinstance(r, dict) and isinstance(r.get("reused"), dict)]
        self.assertTrue(hits, "beta's request does not carry the reused result under `checked`: %s" % checked)
        self.assertEqual(hits[0]["reused"].get("task"), "alpha")
        self.assertEqual(hits[0].get("exit"), 0, hits[0])


# ====================================================================== C3: check evidence keeps the answer

class C3_CheckEvidence(Base):

    def test_C3_1_a_tasks_check_record_carries_summary_and_a_tail_without_interpreter_warnings(self):
        self.prepare({})
        noisy = os.path.join(self.outside, "noisy.py")
        write(noisy, NOISY_CHECK)
        self.add("alpha", "--check", shlex.join([PY, noisy]), "--allow-outside")
        self.put("a.py", "a = 1\n")
        code, out = self.cli("run", "alpha")
        self.assertEqual(code, 0, out)
        rec = self.check_record("alpha")
        self.assertIn("summary", rec, "the task's check record keeps no summary: %s" % rec)
        self.assertTrue(any("OK" == s or s.startswith("Ran 3 tests") for s in rec["summary"]), rec["summary"])
        self.assertIn("failures", rec, rec)
        self.assertEqual(rec["failures"], [])
        tail = rec.get("tail") or []
        self.assertIn("OK", tail, "the tail lost the runner's answer: %s" % tail)
        self.assertFalse([l for l in tail if "ResourceWarning" in l], "the tail keeps interpreter warnings: %s" % tail)

    def test_C3_1_a_checked_runs_record_tail_leaves_the_warnings_out(self):
        self.prepare({"implementer": self.blocked_provider()})
        noisy = os.path.join(self.outside, "noisy.py")
        write(noisy, NOISY_CHECK)
        self.add("alpha", "--role", "implementer", "--check", PASS_CHECK)
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        code, out = self.cli("take", "alpha", "--why", "the worker could not finish here", "--checked", shlex.join([PY, noisy]))
        self.assertEqual(code, 0, out)
        rec = self.task("alpha")["checked"]["ran"][0]
        self.assertTrue(rec.get("summary"), rec)
        self.assertIn("OK", rec.get("tail") or [], rec)
        self.assertFalse([l for l in rec.get("tail") or [] if "ResourceWarning" in l], rec.get("tail"))

    def test_C3_2_kept_tail_drops_a_python_warning_and_its_indented_source_line(self):
        text = ("Ran 2 tests in 0.02s\n\nOK\n"
                "/usr/lib/python3/site-packages/pkg/mod.py:12: DeprecationWarning: datetime.utcnow() is deprecated\n"
                "  now = datetime.datetime.utcnow()\n")
        tail = c.kept_tail(text)
        self.assertIn("OK", tail, tail)
        self.assertFalse([l for l in tail if "DeprecationWarning" in l], tail)
        self.assertFalse([l for l in tail if "utcnow()" in l and "Warning" not in l], "the warning's source line was kept: %s" % tail)

    def test_C3_2_kept_tail_drops_a_node_warning_and_its_use_trace_warnings_line(self):
        text = ("ℹ tests 5\nℹ pass 5\nℹ fail 0\n"
                "(node:123) ExperimentalWarning: VM Modules is an experimental feature and might change at any time\n"
                "(Use `node --trace-warnings ...` to show where the warning was created)\n")
        tail = c.kept_tail(text)
        self.assertIn("ℹ fail 0", tail, tail)
        self.assertFalse([l for l in tail if "ExperimentalWarning" in l or "--trace-warnings" in l], tail)

    def test_C3_2_a_tail_keeps_the_summary_when_many_warnings_follow_it(self):
        text = "line one\nline two\nRan 3 tests in 0.01s\n\nOK\n" + "\n".join([WARNING] * 10) + "\n"
        tail = c.kept_tail(text)
        self.assertIn("OK", tail, tail)
        self.assertIn("Ran 3 tests in 0.01s", tail, tail)
        self.assertFalse([l for l in tail if "ResourceWarning" in l], tail)


SAMPLES = {
    "unittest": ("...\n----------------------------------------------------------------------\nRan 3 tests in 0.004s\n\nOK (skipped=1)\n", "OK (skipped=1)"),
    "unittest-failed": ("F..\nFAIL: test_a (m.T.test_a)\nRan 3 tests in 0.004s\n\nFAILED (failures=1)\n", "FAILED (failures=1)"),
    "pytest-rules": ("collected 4 items\n\ntest_x.py ...F\n========================= 3 passed, 1 failed in 0.12s ==========================\n", "3 passed, 1 failed in 0.12s"),
    "pytest-bare": ("collected 4 items\n\ntest_x.py ...F\n3 passed, 1 failed in 0.12s\n", "3 passed, 1 failed in 0.12s"),
    "node": ("✔ adds (0.5ms)\nℹ tests 5\nℹ suites 0\nℹ pass 5\nℹ fail 0\nℹ cancelled 0\nℹ duration_ms 41.2\n", "ℹ tests 5"),
    "tap": ("TAP version 13\nok 1 - adds\n1..5\n# tests 5\n# pass 5\n# fail 0\n", "# tests 5"),
    "jest": ("PASS src/a.test.js\nFAIL src/b.test.js\nTest Suites: 1 failed, 1 passed, 2 total\nTests:       1 failed, 5 passed, 6 total\nSnapshots:   0 total\nTime:        1.2 s\n", "Tests:       1 failed, 5 passed, 6 total"),
    "vitest": (" ✓ src/a.test.ts (5)\n\n Test Files  1 passed (1)\n      Tests  5 passed (5)\n   Start at  10:00:00\n   Duration  300ms\n", "Tests  5 passed (5)"),
    "mocha": ("  adds\n    ✓ one\n\n  5 passing (20ms)\n  1 failing\n", "5 passing (20ms)"),
    "go-ok": ("=== RUN   TestAdd\n--- PASS: TestAdd (0.00s)\nok  \texample.com/pkg\t0.012s\n", "example.com/pkg"),
    "go-fail": ("=== RUN   TestAdd\n--- FAIL: TestAdd (0.00s)\n    add_test.go:9: got 3\nFAIL\texample.com/pkg\t0.012s\n", "example.com/pkg"),
    "go-bare-pass": ("=== RUN   TestAdd\n--- PASS: TestAdd (0.00s)\nPASS\n", "PASS"),
    "go-bare-fail": ("=== RUN   TestAdd\n--- FAIL: TestAdd (0.00s)\nFAIL\n", "FAIL"),
    "cargo": ("running 5 tests\ntest a ... ok\n\ntest result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n", "test result: ok. 5 passed"),
}


class C3_3_Runners(unittest.TestCase):

    def recognized(self, name):
        sample, needle = SAMPLES[name]
        got = c.checked_results(sample)
        self.assertNotIn("result", got, "%s's output is not recognized: %s" % (name, got))
        self.assertTrue(got.get("summary"), "%s: no summary: %s" % (name, got))
        self.assertTrue(any(needle in s for s in got["summary"]), "%s: the summary does not hold %r: %s" % (name, needle, got["summary"]))
        self.assertLessEqual(len(got["summary"]), 5)

    def test_C3_3_unittest_summaries_keep_working(self):
        self.recognized("unittest")
        self.recognized("unittest-failed")

    def test_C3_3_pytest_with_rules(self):
        self.recognized("pytest-rules")

    def test_C3_3_pytest_without_rules(self):
        self.recognized("pytest-bare")

    def test_C3_3_node_test_runner(self):
        self.recognized("node")

    def test_C3_3_tap(self):
        self.recognized("tap")

    def test_C3_3_jest(self):
        self.recognized("jest")

    def test_C3_3_vitest(self):
        self.recognized("vitest")

    def test_C3_3_mocha(self):
        self.recognized("mocha")

    def test_C3_3_go_ok_and_fail_lines(self):
        self.recognized("go-ok")
        self.recognized("go-fail")

    def test_C3_3_go_bare_pass_and_fail(self):
        self.recognized("go-bare-pass")
        self.recognized("go-bare-fail")

    def test_C3_3_cargo(self):
        self.recognized("cargo")

    def test_C3_3_red_refusal_keeps_working(self):
        said = "F\nFAIL: test_a (m.T.test_a)\nRan 1 test in 0.001s\n\nFAILED (failures=1)\n"
        self.assertIsNone(c.red_refusal(1, said, c.checked_results(said)))
        usage = "usage: x [-h]\nx: error: unrecognized arguments: --nope\n"
        self.assertEqual(c.red_refusal(2, usage, c.checked_results(usage)), "usage error before tests")


# ====================================================================== C4: documentation

class C4_Documentation(unittest.TestCase):

    def paragraphs(self, *parts):
        return [" ".join(p.split()) for p in re.split(r"\n\s*\n", readme(*parts))]

    def test_C4_the_readme_says_what_voids_a_verdict(self):
        hits = [p for p in self.paragraphs("README.md")
                if re.search(r"(?i)\bvoid", p) and "scope" in p and re.search(r"(?i)another open task|other open task", p)]
        self.assertTrue(hits, "no README passage says a change in another open task's scope does not void a verdict")
        self.assertTrue(any(re.search(r"(?i)checks?[^.]*(again|rerun)", p) for p in hits),
                        "the passage on what voids a verdict does not say what reruns the checks")

    def test_C4_the_readme_says_a_check_is_not_run_twice_on_an_identical_tree(self):
        hits = [p for p in self.paragraphs("README.md") if "`reused`" in p and re.search(r"(?i)identical tree|same tree", p)]
        self.assertTrue(hits, "no README passage says a check is not run twice on an identical tree within a run (`reused`)")

    def test_C4_the_readme_says_interpreter_warnings_are_left_out_of_a_checks_tail(self):
        hits = [p for p in self.paragraphs("README.md") if re.search(r"(?i)warning", p) and "tail" in p]
        self.assertTrue(hits, "no README passage says interpreter warnings are left out of a check's tail")
        records = [p for p in self.paragraphs("README.md") if "`summary`" in p and "`failures`" in p and "check" in p]
        self.assertTrue(records, "the README does not name `summary`/`failures` on a check record")

    def test_C4_the_run_skill_says_what_still_working_means_for_a_verdict(self):
        hits = [p for p in self.paragraphs("skills", "run", "SKILL.md") if "still working" in p and re.search(r"(?i)\bvoid", p)]
        self.assertTrue(hits, "the run skill does not say, where it describes `still working`, what voids a pending verdict")



# ====================================================================== C1.4: the review witness keeps the task's own files

class C1_4_OwnFilesStay(Base):
    """T has no `--scope`; another open task U scopes one of T's own files. The verifier, while answering T's request,
    edits that file once: the verdict reviewed it, so it is voided and the verifier asked again — whatever U's scope says."""

    def assert_voided(self, path, out):
        ts = self.task("T")
        self.assertTrue(ts.get("invalidated-reviews"),
                        "a change to %s, one of T's own files, while the verifier read did not void T's verdict (keys %s):\n%s"
                        % (path, sorted(ts), out))
        changed = [f for entry in ts["invalidated-reviews"] for f in (entry.get("changed") or [])]
        self.assertIn(path, changed, ts["invalidated-reviews"])
        self.assertNotEqual(ts["status"], "done", out)
        if len(self.seen("T")) < 2:
            code, out = self.cli("run", "T")
        self.assertEqual(len(self.seen("T")), 2, "the verifier was not asked about T again:\n" + out)

    def test_C1_4_a_protected_tests_file_another_task_scopes_stays_in_the_witness(self):
        """T protects t_test.py (`--tests`), an existing test file; U's `--scope` is t_test.py. The verifier edits it while
        reading T: invalidated, asked again."""
        self.prepare({"verifier": self.fake_verifier(edit=("t_test.py", "def test_t():\n    assert 2\n"), when_task="T")},
                     files=(("a.py", "a = 0\n"), ("b.py", "b = 0\n"), ("t_test.py", "def test_t():\n    assert 1\n")))
        self.add("T", "--check", PASS_CHECK, "--tests", "t_test.py")
        self.add("U", "--scope", "t_test.py", "--check", PASS_CHECK)
        self.put("a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertTrue(self.seen("T"), "the verifier was never asked about T:\n" + out)
        self.assertIn("t_test.py", self.seen("T")[0].get("tests") or [], "T's request does not protect t_test.py")
        self.assert_voided("t_test.py", out)

    def test_C1_4_a_held_at_start_file_another_task_scopes_stays_in_the_witness(self):
        """src/x.py, named by T's brief, was changed before T was added; U's `--scope` is src. The verifier edits it while
        reading T: invalidated, asked again."""
        self.prepare({"verifier": self.fake_verifier(edit=("src/x.py", "x = 3\n"), when_task="T")},
                     files=(("a.py", "a = 0\n"), ("b.py", "b = 0\n"), ("src/x.py", "x = 0\n")))
        self.put("src/x.py", "x = 1\n")
        code, out = self.cli("add", "T", "--brief", "src/x.py: make x one", "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        self.add("U", "--scope", "src", "--check", PASS_CHECK)
        self.put("a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertTrue(self.seen("T"), "the verifier was never asked about T:\n" + out)
        self.assertIn("src/x.py", (self.seen("T")[0].get("attribution") or {}).get("held-at-start") or [],
                      "T's request does not send src/x.py as held at start")
        self.assert_voided("src/x.py", out)

    def test_C1_4_an_adopted_file_inside_another_tasks_scope_stays_in_the_witness(self):
        """A judgment (`adopt T f.py`) gave T f.py, a file inside U's `--scope`. The verifier edits it while reading T:
        invalidated, asked again."""
        self.prepare({"verifier": self.fake_verifier(edit=("f.py", "f = 3\n"), when_task="T")},
                     files=(("a.py", "a = 0\n"), ("b.py", "b = 0\n"), ("f.py", "f = 0\n")))
        self.add("T", "--check", PASS_CHECK)
        self.add("U", "--scope", "f.py", "--check", PASS_CHECK)
        self.put("f.py", "f = 1\n")
        code, out = self.cli("adopt", "T", "f.py", "--why", "written for T while U was open")
        self.assertEqual(code, 0, out)
        adopted = [f for e in (self.task("T").get("adopted") or []) for f in (e.get("files") or [])]
        self.assertIn("f.py", adopted, "the adopt did not give T f.py:\n" + out)
        code, out = self.cli("run", "T")
        self.assert_voided("f.py", out)

    def test_C1_4_a_file_another_task_scopes_that_is_none_of_ts_own_stays_out(self):
        """Unchanged (C1.1): T has no `--scope`, U's `--scope` is b.py, none of T's own. The verifier edits b.py while
        reading T: one request, no invalidated review."""
        self.prepare({"verifier": self.fake_verifier(edit=("b.py", "b = 2\n"), when_task="T")})
        self.add("T", "--check", PASS_CHECK)
        self.add("U", "--scope", "b.py", "--check", PASS_CHECK)
        self.put("a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        ts = self.task("T")
        self.assertNotIn("invalidated-reviews", ts, "an edit of U's file voided T's verdict: %s\n%s" % (ts.get("invalidated-reviews"), out))
        self.assertEqual(len(self.seen("T")), 1, out)
        self.assertEqual(code, 0, out)
        self.assertEqual(ts["status"], "done", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
