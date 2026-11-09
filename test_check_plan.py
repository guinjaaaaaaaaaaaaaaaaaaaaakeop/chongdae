"""Contract C6: one execution plan for equivalent checks at a landing and in recheck.

The defect as a session meets it: two completed runs whose done tasks name the same check on unchanged source;
`recheck` (and a worktree run's landing at close) runs that check once per task. The check here is a script inside the
project that appends one line to a counter file OUTSIDE the project (inside, it would change the source digest), so the
counter says how many times it really ran.
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_chongdae
from test_chongdae import Project, run, write
import chongdae as c

PY = sys.executable
README = os.path.join(test_chongdae.PLUGIN, "README.md")
LAST = re.compile(r"^recheck: (\d+) green · (\d+) red · (\d+) without checks$")


def counting(counter, fail_if=None, writes=None, when=None):
    """A check program: appends a line to `counter` (outside the project); with `fail_if`, exits 1 when that project file
    exists; with `writes`, rewrites that tracked project file with the count so far (it changes the source every time) —
    only while the file `when` (outside the project) exists: `run` refuses a check that changes the source as it runs."""
    lines = ["import os, sys",
             "here = os.path.dirname(os.path.abspath(__file__))",
             "open(%r, 'a').write('ran\\n')" % counter]
    if writes:
        lines.append("if os.path.exists(%r):" % when)
        lines.append("    n = len(open(%r).read().splitlines())" % counter)
        lines.append("    open(os.path.join(here, %r), 'w').write('generated %%d\\n' %% n)" % writes)
    if fail_if:
        lines.append("if os.path.exists(os.path.join(here, %r)):" % fail_if)
        lines.append("    print('shared check broke: %s is here' % " + repr(fail_if) + ")")
        lines.append("    sys.exit(1)")
    return "\n".join(lines) + "\n"


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.out = os.path.realpath(tempfile.mkdtemp(prefix="chongdae-c6-counter-"))
        self.addCleanup(shutil.rmtree, self.out, True)
        self.pj = Project()
        self.addCleanup(self.pj.__exit__)
        git(self.pj.dir, "config", "user.email", "t@t")
        git(self.pj.dir, "config", "user.name", "t")

    # -- fixtures --------------------------------------------------------------------------------------------------
    def counter(self, name="count.txt"):
        return os.path.join(self.out, name)

    def count(self, name="count.txt"):
        path = self.counter(name)
        if not os.path.exists(path):
            return 0
        with open(path, encoding="utf-8") as fh:
            return len(fh.read().splitlines())

    def reset(self, name="count.txt"):
        open(self.counter(name), "w").close()

    def base(self, files):
        """The project's first commit: the check programs (and whatever else) tracked."""
        for rel, body in files.items():
            write(os.path.join(self.pj.dir, rel), body)
        git(self.pj.dir, "add", "-A")
        r = git(self.pj.dir, "commit", "-qm", "base")
        self.assertEqual(r.returncode, 0, r.stderr)

    def session_run(self, tasks, target=None, goal="c6", worktree=False):
        """One completed session run: init --session, add each (id, [check text...], extra flags), run, commit the work, close.
        Each task writes a file of its own, committed before close."""
        target = target or self.pj.dir
        init = ["init", "--session", "--goal", goal] + (["--worktree"] if worktree else []) + ["--target", target]
        code, out = run(*init)
        self.assertEqual(code, 0, out)
        if worktree:
            target = out.split("--target ")[-1].strip() if "--target " in out else None
            wt_root = os.path.join(self.pj.dir, c.RUNS, "wt")
            if not target or not os.path.isdir(target):
                target = os.path.join(wt_root, sorted(os.listdir(wt_root))[-1])
        for tid, checks, extra in tasks:
            argv = ["add", tid, "--why", "a test task: no check decides it"]
            for ch in checks:
                argv += ["--check", ch]
            if not checks:
                argv += ["--brief", "work with no check"]
            code, out = run(*argv, *extra, "--target", target)
            self.assertEqual(code, 0, out)
            write(os.path.join(target, "work-%s.txt" % tid), "work of %s\n" % tid)
            code, out = run("run", "--target", target)
            self.assertEqual(code, 0, out)
        git(target, "add", "-A", "--", ".", ":(exclude).chongdae")
        git(target, "commit", "-qm", "the work of " + goal)
        if worktree:
            return target
        code, out = run("close", "--target", target)
        self.assertEqual(code, 0, out)
        return target

    def recheck(self):
        return run("recheck", "--target", self.pj.dir)

    def assert_last(self, out, green, red, without=0):
        lines = out.rstrip("\n").splitlines()
        self.assertTrue(lines, out)
        self.assertEqual(lines[-1], "recheck: %d green · %d red · %d without checks" % (green, red, without), out)
        return lines

    def task_line(self, out, tid, word):
        lines = [ln for ln in out.splitlines() if ln.lstrip().startswith(word) and re.search(r"/%s(\s|$)" % re.escape(tid), ln)]
        self.assertTrue(lines, "no `%s` line for %s:\n%s" % (word, tid, out))
        return lines[0]

    def plan_line(self, lines, executions, task_checks):
        """The extra line before the last one: how many executions served how many task checks."""
        body = lines[:-1]
        cands = [ln for ln in body if not ln.lstrip().startswith(("still green", "RED"))
                 and re.search(r"\b%d\b.*\bchecks?\b.*\b%d\b.*\btask checks?\b" % (executions, task_checks), ln)]
        self.assertTrue(cands, "no line says %d execution(s) served %d task checks:\n%s" % (executions, task_checks, "\n".join(lines)))
        self.assertIn(cands[0], body[-3:], "the extra line comes just before the last line")
        return cands[0]


class C6_Recheck(Base):
    def test_C6_1_two_completed_runs_sharing_a_check_run_it_once_in_recheck(self):
        """The reproducer: two completed session runs whose done tasks name the same check; recheck runs it once."""
        self.base({"count.py": counting(self.counter())})
        check = shlex.join([PY, "count.py"])
        self.session_run([("t1", [check], [])], goal="first")
        self.session_run([("t2", [check], [])], goal="second")
        self.reset()
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count(), 1, "the equivalent check ran %d times on unchanged source:\n%s" % (self.count(), out))
        self.task_line(out, "t1", "still green")
        self.task_line(out, "t2", "still green")

    def test_C6_2_each_task_keeps_its_line_the_extra_line_and_the_last_line_exactly(self):
        self.base({"count.py": counting(self.counter())})
        check = shlex.join([PY, "count.py"])
        self.session_run([("t1", [check], [])], goal="first")
        self.session_run([("t2", [check], [])], goal="second")
        self.reset()
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        lines = self.assert_last(out, 2, 0)
        green = [ln for ln in lines if ln.lstrip().startswith("still green")]
        self.assertEqual(len(green), 2, out)
        self.plan_line(lines, 1, 2)
        self.assertEqual(self.count(), 1, out)

    def test_C6_2_no_extra_line_when_nothing_was_shared(self):
        """The extra line is said only when any check was shared — and two different checks still run once each."""
        self.base({"count.py": counting(self.counter()), "other.py": counting(self.counter("other.txt"))})
        self.session_run([("t1", [shlex.join([PY, "count.py"])], []), ("t2", [shlex.join([PY, "other.py"])], [])])
        self.reset(); self.reset("other.txt")
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        lines = self.assert_last(out, 2, 0)
        self.assertEqual((self.count(), self.count("other.txt")), (1, 1), out)
        extra = [ln for ln in lines[:-1] if re.search(r"task checks?", ln)]
        self.assertEqual(extra, [], "nothing was shared, yet: %s" % extra)
        # the same project with a third task sharing count.py: now the line appears (red now: no line is ever said)
        self.session_run([("t3", [shlex.join([PY, "count.py"])], [])], goal="third")
        self.reset(); self.reset("other.txt")
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.plan_line(self.assert_last(out, 3, 0), 2, 3)
        self.assertEqual((self.count(), self.count("other.txt")), (1, 1), out)

    def test_C6_3_a_check_that_changes_tracked_source_runs_again_and_a_pure_one_still_runs_once(self):
        """gen.py rewrites a tracked file each time (the source changes): two tasks naming it → two executions. pure.py,
        named by two later tasks, changes nothing → one execution on the source gen.py left."""
        flag = self.counter("writing-on")
        self.base({"gen.py": counting(self.counter("gen.txt"), writes="generated.txt", when=flag), "generated.txt": "generated 0\n",
                   "pure.py": counting(self.counter("pure.txt"))})
        gen, pure = shlex.join([PY, "gen.py"]), shlex.join([PY, "pure.py"])
        self.session_run([("g1", [gen], []), ("g2", [gen], []), ("p1", [pure], []), ("p2", [pure], [])])
        self.reset("gen.txt"); self.reset("pure.txt")
        write(flag, "on\n")   # from here gen.py rewrites generated.txt (tracked) on every execution
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count("gen.txt"), 2, "a check that changed the source makes the next equivalent one a new key:\n" + out)
        self.assertEqual(self.count("pure.txt"), 1, "the pure check on unchanged source ran %d times:\n%s" % (self.count("pure.txt"), out))
        lines = self.assert_last(out, 4, 0)
        self.plan_line(lines, 3, 4)

    def test_C6_3_records_do_not_count_as_source(self):
        """A check that writes only under .chongdae/ leaves the source digest as it was: the second task still shares."""
        rec = "import os; os.makedirs('.chongdae', exist_ok=True); open(os.path.join('.chongdae', 'scratch.txt'), 'a').write('x\\n')\n"
        self.base({"rec.py": counting(self.counter()) + rec})
        check = shlex.join([PY, "rec.py"])
        self.session_run([("t1", [check], [])], goal="first")
        self.session_run([("t2", [check], [])], goal="second")
        self.reset()
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count(), 1, "a write under the record changed the key:\n" + out)

    def test_C6_4_a_red_shared_check_is_red_for_every_task_that_shares_it(self):
        self.base({"count.py": counting(self.counter(), fail_if="broken")})
        check = shlex.join([PY, "count.py"])
        self.session_run([("t1", [check], [])], goal="first")
        self.session_run([("t2", [check], [])], goal="second")
        write(os.path.join(self.pj.dir, "broken"), "now\n")
        git(self.pj.dir, "add", "broken"); git(self.pj.dir, "commit", "-qm", "break it")
        self.reset()
        code, out = self.recheck()
        self.assertEqual(code, 1, out)
        self.task_line(out, "t1", "RED")
        self.task_line(out, "t2", "RED")
        self.assertGreaterEqual(out.count("shared check broke"), 2, "each RED task tells its failure lines:\n" + out)
        self.assert_last(out, 0, 2)
        self.assertEqual(self.count(), 1, "a red result is shared too:\n" + out)

    def test_C6_4_order_of_first_executions_follows_runs_then_tasks_then_checks(self):
        """Run 1: t1 [a, b]; run 2: t2 [b, c], t3 [a]. First executions in today's walk: a, b, c — each once."""
        log = self.counter("order.txt")
        prog = "import sys\nopen(%r, 'a').write(sys.argv[1] + '\\n')\n" % log
        self.base({"mark.py": prog})
        a, b, cc = (shlex.join([PY, "mark.py", x]) for x in "abc")
        self.session_run([("t1", [a, b], [])], goal="first")
        self.session_run([("t2", [b, cc], []), ("t3", [a], [])], goal="second")
        open(log, "w").close()
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        with open(log, encoding="utf-8") as fh:
            self.assertEqual(fh.read().split(), ["a", "b", "c"], out)

    def test_C6_5_a_repeat_checks_task_runs_on_its_own_and_shares_with_nobody(self):
        """[rep (--repeat-checks), t1, t2] all name the same check: rep runs its own, t1 does not take rep's, t2 takes t1's → 2."""
        self.base({"count.py": counting(self.counter())})
        check = shlex.join([PY, "count.py"])
        code, out = run("add", "--help")
        self.assertIn("--repeat-checks", out, "`add` has no --repeat-checks")
        self.session_run([("rep", [check], ["--repeat-checks"])], goal="first")
        self.session_run([("t1", [check], []), ("t2", [check], [])], goal="second")
        self.reset()
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count(), 2, "rep runs on its own, the other two share one execution:\n" + out)
        self.assert_last(out, 3, 0)

    def test_C6_5_repeat_checks_is_recorded_on_the_task_and_show_tells_it(self):
        self.base({"count.py": counting(self.counter())})
        check = shlex.join([PY, "count.py"])
        code, out = run("init", "--session", "--goal", "c6", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        code, out = run("add", "plain", "--check", check, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        code, out = run("show", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.assertNotRegex(out, r"(?i)repeat", "a task without the opt-out says nothing of it")
        code, out = run("add", "rep", "--check", check, "--repeat-checks", "--target", self.pj.dir)
        self.assertEqual(code, 0, "add --repeat-checks was refused: " + out)
        self.assertIs(self.pj.state()["tasks"]["rep"]["def"].get("repeat-checks"), True, self.pj.state()["tasks"]["rep"]["def"])
        self.assertFalse(self.pj.state()["tasks"]["plain"]["def"].get("repeat-checks"))
        code, out = run("show", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?i)repeat", "show does not tell the opt-out:\n" + out)
        blocks = show_blocks(out)
        self.assertIn("rep", blocks, out)
        self.assertIn("plain", blocks, out)
        self.assertRegex(blocks["rep"], r"(?i)repeat", "show does not tell the opt-out on the task:\n" + out)
        self.assertNotRegex(blocks["plain"], r"(?i)repeat", "the opt-out is told on the task that has it, not another")

    def test_C6_6_a_plugin_placeholder_and_the_path_it_resolves_to_are_one_key(self):
        tools = os.path.join(self.pj.dir, "tools")
        self.base({os.path.join("tools", "alpha", "check.py"): counting(self.counter()),
                   "hunsu.local.json": '{"links": {"alpha": %s}}\n' % _json_str(tools.replace(os.sep, "/"))})
        placeholder = [PY, "{plugin:alpha}/check.py"]
        resolved = c.resolve_argv(self.pj.dir, placeholder)
        self.assertNotEqual(resolved, placeholder)
        self.session_run([("t1", [shlex.join(placeholder)], [])], goal="first")
        self.session_run([("t2", [shlex.join(resolved)], [])], goal="second")
        self.assertEqual(self.pj.state()["tasks"]["t2"]["def"]["checks"], [resolved])
        self.reset()
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count(), 1, "different text, one resolved argv: one key:\n" + out)
        self.plan_line(self.assert_last(out, 2, 0), 1, 2)

    def test_C6_7_a_tasks_own_checks_at_run_are_unchanged(self):
        """At `run` each task's checks run as today (two tasks naming one check: two executions); recheck is the plan's."""
        self.base({"count.py": counting(self.counter())})
        check = shlex.join([PY, "count.py"])
        self.reset()
        self.session_run([("t1", [check], []), ("t2", [check], [])])
        self.assertEqual(self.count(), 2, "budget_checks at `run` changed")
        self.reset()
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count(), 1, out)


class C6_Landing(Base):
    def landed(self, fail_in_worktree=False):
        self.base({"count.py": counting(self.counter(), fail_if="broken")})
        check = shlex.join([PY, "count.py"])
        self.session_run([("t1", [check], [])], goal="first")
        self.session_run([("t2", [check], [])], goal="second")
        wt = self.session_run([("t3", [], [])], goal="landing", worktree=True)
        if fail_in_worktree:
            write(os.path.join(wt, "broken"), "now\n")
            git(wt, "add", "broken"); git(wt, "commit", "-qm", "break it")
        self.reset()
        code, out = run("close", "--target", wt)
        return wt, code, out

    def test_C6_1_the_landing_runs_a_shared_check_once(self):
        wt, code, out = self.landed()
        self.assertEqual(code, 0, out)
        self.assertIn("merged", out)
        self.assertFalse(os.path.isdir(wt), "a clean landing removes the worktree")
        self.assertEqual(self.count(), 1, "the landing ran the shared check %d times:\n%s" % (self.count(), out))

    def test_C6_4_a_shared_red_at_the_landing_keeps_the_worktree_and_runs_once(self):
        wt, code, out = self.landed(fail_in_worktree=True)
        self.assertNotEqual(code, 0, out)
        self.assertIn("shared check broke", out, "the landing tells the first failure lines")
        self.assertTrue(os.path.isdir(wt), "a red landing keeps the worktree")
        branches = git(self.pj.dir, "branch", "--list", "run/*").stdout
        self.assertIn(os.path.basename(wt), branches, "a red landing keeps the branch")
        self.assertEqual(self.count(), 1, "the shared red check ran %d times at the landing:\n%s" % (self.count(), out))


class C6_8_Readme(unittest.TestCase):
    def setUp(self):
        with open(README, encoding="utf-8") as fh:
            self.text = fh.read()

    def section(self, heading):
        m = re.search(r"^#+ %s[^\n]*\n(.*?)(?=^#+ )" % re.escape(heading), self.text, re.S | re.M)
        self.assertTrue(m, "no section " + heading)
        return m.group(1)

    def test_C6_8_recheck_says_equivalent_checks_run_once_the_key_the_opt_out_and_the_line(self):
        s = self.section("`/chongdae:recheck`")
        for needle in ("equivalent", "unchanged source", "once", "repeat-checks", "environment", "source digest"):
            self.assertIn(needle, s, "recheck's section does not say %r" % needle)
        self.assertRegex(s, r"resolved|resolve_argv|\{plugin:", "the key's resolved argv")
        self.assertRegex(s, r"working directory|real path", "the key's working directory")
        self.assertRegex(s, r"task checks", "the extra line")

    def test_C6_8_the_landing_in_runs_says_equivalent_checks_run_once(self):
        s = self.section("Runs")
        self.assertRegex(s, r"equivalent checks[^.]*once", "Runs (a worktree run's landing) does not say equivalent checks run once")


class C6_9_NoGit(Base):
    """C6.9: where `source_tree` gives None (not a git repository) the plan shares nothing."""

    def setUp(self):
        super().setUp()
        self.nogit = os.path.realpath(tempfile.mkdtemp(prefix="chongdae-c6-nogit-"))
        self.addCleanup(shutil.rmtree, self.nogit, True)
        r = git(self.nogit, "rev-parse", "--is-inside-work-tree")
        self.assertNotEqual(r.returncode, 0, "the fixture must not be inside a git work tree: " + self.nogit)
        self.assertIsNone(c.source_tree(self.nogit), "the fixture's source must be unmeasurable")

    def files(self, files):
        for rel, body in files.items():
            write(os.path.join(self.nogit, rel), body)

    def recheck_nogit(self):
        return run("recheck", "--target", self.nogit)

    def no_extra_line(self, lines):
        extra = [ln for ln in lines[:-1] if re.search(r"task checks?", ln)]
        self.assertEqual(extra, [], "nothing can be shared without git, yet: %s" % extra)

    def test_C6_9_a_generator_check_in_a_non_git_project_runs_for_each_task(self):
        """The eyes' case: two completed runs name one generator check; it rewrites a file inside the project on every
        run. Without git the source cannot be measured, so the second task must not get the first's cached result."""
        flag = self.counter("writing-on")
        self.files({"gen.py": counting(self.counter(), writes="generated.txt", when=flag), "generated.txt": "generated 0\n"})
        check = shlex.join([PY, "gen.py"])
        self.session_run([("t1", [check], [])], target=self.nogit, goal="first")
        self.session_run([("t2", [check], [])], target=self.nogit, goal="second")
        self.reset()
        write(flag, "on\n")   # from here gen.py rewrites generated.txt on every execution
        code, out = self.recheck_nogit()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count(), 2, "without git the generator ran %d time(s) for 2 tasks — a cached result over "
                         "changed source:\n%s" % (self.count(), out))
        with open(os.path.join(self.nogit, "generated.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "generated 2\n", "the second task's check did not run on the source the first left")
        lines = self.assert_last(out, 2, 0)
        self.task_line(out, "t1", "still green")
        self.task_line(out, "t2", "still green")
        self.no_extra_line(lines)

    def test_C6_9_without_git_even_a_pure_check_is_not_shared_and_a_git_project_still_shares(self):
        """Shares nothing means nothing: three tasks naming one pure check run it three times. The same check in the git
        project (C6.1) still runs once."""
        self.files({"count.py": counting(self.counter())})
        check = shlex.join([PY, "count.py"])
        self.session_run([("t1", [check], [])], target=self.nogit, goal="first")
        self.session_run([("t2", [check], []), ("t3", [check], [])], target=self.nogit, goal="second")
        self.reset()
        code, out = self.recheck_nogit()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count(), 3, "without git every check of every task runs on its own:\n" + out)
        self.no_extra_line(self.assert_last(out, 3, 0))
        # a git project is unchanged: the C6.1 assertion
        self.base({"count.py": counting(self.counter("git.txt"))})
        gcheck = shlex.join([PY, "count.py"])
        self.session_run([("g1", [gcheck], [])], goal="git-first")
        self.session_run([("g2", [gcheck], [])], goal="git-second")
        self.reset("git.txt")
        code, out = self.recheck()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.count("git.txt"), 1, "a git project's equivalent checks on unchanged source run once:\n" + out)

    def test_C6_9_a_red_check_without_git_is_not_handed_to_the_next_task(self):
        """Neither taken from nor given: a red first execution does not make the second task red without running."""
        self.files({"count.py": counting(self.counter(), fail_if="broken")})
        check = shlex.join([PY, "count.py"])
        self.session_run([("t1", [check], [])], target=self.nogit, goal="first")
        self.session_run([("t2", [check], [])], target=self.nogit, goal="second")
        write(os.path.join(self.nogit, "broken"), "now\n")
        self.reset()
        code, out = self.recheck_nogit()
        self.assertEqual(code, 1, out)
        self.task_line(out, "t1", "RED")
        self.task_line(out, "t2", "RED")
        self.assertEqual(self.count(), 2, "the red check ran %d time(s) for 2 tasks without git:\n%s" % (self.count(), out))
        self.no_extra_line(self.assert_last(out, 0, 2))


class C6_9_Readme(unittest.TestCase):
    setUp = C6_8_Readme.setUp
    section = C6_8_Readme.section

    def test_C6_9_recheck_says_sharing_needs_a_measurable_source_and_without_git_each_check_runs(self):
        s = self.section("`/chongdae:recheck`")
        self.assertRegex(s, r"(?i)\bgit\b", "recheck's section does not name git as the condition for sharing")
        self.assertRegex(s, r"(?i)(can be measured|cannot be measured|measurable)",
                         "recheck's section does not say sharing needs a source that can be measured")
        self.assertRegex(s, r"(?i)(without git|not a git|no git)[^.]*\b(each|every)\b[^.]*\bcheck\b[^.]*\bruns?\b",
                         "recheck's section does not say that without git each check runs")


def show_blocks(out):
    """`show`'s task blocks: an unindented `<id>  <status>` line and the indented lines under it, by id."""
    blocks, cur = {}, None
    for ln in out.splitlines():
        m = re.match(r"^(\S+)  \S", ln)
        if m and not ln.startswith(("run ", "goal:", "created ", "tasks ", "left open")):
            cur = m.group(1)
            blocks[cur] = ln + "\n"
        elif ln.startswith(" ") and cur:
            blocks[cur] += ln + "\n"
        else:
            cur = None
    return blocks


def _json_str(s):
    import json
    return json.dumps(s)


if __name__ == "__main__":
    unittest.main()
