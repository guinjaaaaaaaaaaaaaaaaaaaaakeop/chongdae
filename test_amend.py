"""Contract C2: a brief from a file or stdin, and an amend of an open task's brief or checks (with history)."""
import getpass
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_chongdae
from test_chongdae import Project, run, write, UNCOMMITTED
import chongdae as c

ENGINE = os.path.join(test_chongdae.PLUGIN, "chongdae.py")
REPO = os.path.dirname(os.path.abspath(__file__))
PASS = sys.executable + " -c pass"
PASS2 = sys.executable + " -c \"print('ok')\""
FAIL = sys.executable + " -c \"import sys; sys.exit(3)\""
SHELL_BRIEF = "say `whoami` here"


def argv(check):
    return shlex.split(check)


class Base(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.mkdtemp(prefix="chongdae-amend-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def session(self, pj):
        code, out = run("init", "--session", "--goal", "amend", "--target", pj.dir)
        self.assertEqual(code, 0, out)
        return c.run_dir(pj.dir)

    def add(self, pj, tid, *extra):
        code, out = run("add", tid, "--why", "a test task: no check decides it", *extra, "--target", pj.dir)
        self.assertEqual(code, 0, out)

    def task(self, pj, tid="t"):
        return pj.state()["tasks"][tid]

    def scratch(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def assert_amend_exists(self):
        code, out = run("amend", "--help")
        self.assertEqual(code, 0, "`amend` is not a command: %s" % out)
        self.assertIn("--why", out)

    def assert_brief_file_exists(self):
        code, out = run("add", "--help")
        self.assertEqual(code, 0, out)
        self.assertIn("--brief-file", out)

    def shell(self, line, stdin=None):
        env = dict(os.environ)
        for key in ("AGENT_WORKER", "PYTHONPATH"):
            env.pop(key, None)
        return subprocess.run(["sh", "-c", line], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env)


class C2_1_BriefFile(Base):
    def test_C2_1_shell_line_loses_backticks_but_brief_file_keeps_them_verbatim(self):
        with Project() as pj:
            self.session(pj)
            # the defect as a session meets it: the shell substitutes the backticked phrase before chongdae sees the brief
            line = "%s %s add lost --why 'a test task: no check decides it' --brief \"%s\" --target %s" % (shlex.quote(sys.executable), shlex.quote(ENGINE), SHELL_BRIEF, shlex.quote(pj.dir))
            res = self.shell(line)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            lost = self.task(pj, "lost")["def"]["brief"]
            self.assertNotIn("`whoami`", lost)
            self.assertIn(getpass.getuser(), lost)
            # the fix: the same text from a file reaches the record as written
            path = self.scratch("brief.txt", SHELL_BRIEF + "\n")
            line = "%s %s add kept --why 'a test task: no check decides it' --brief-file %s --target %s" % (shlex.quote(sys.executable), shlex.quote(ENGINE), shlex.quote(path), shlex.quote(pj.dir))
            res = self.shell(line)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertEqual(self.task(pj, "kept")["def"]["brief"], SHELL_BRIEF)

    def test_C2_1_brief_from_stdin_through_a_shell_is_verbatim(self):
        with Project() as pj:
            self.session(pj)
            text = "한글 brief: say `whoami` and $(id -u) and $HOME here\n"
            line = "%s %s add t --why 'a test task: no check decides it' --brief-file - --target %s" % (shlex.quote(sys.executable), shlex.quote(ENGINE), shlex.quote(pj.dir))
            res = self.shell(line, stdin=text)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertEqual(self.task(pj)["def"]["brief"], text[:-1])

    def test_C2_1_only_one_trailing_newline_is_removed_and_utf8_kept(self):
        with Project() as pj:
            self.session(pj)
            text = "첫 줄\n  indented `x` $(y)\n\n"
            path = self.scratch("b.txt", text)
            self.add(pj, "t", "--brief-file", path)
            self.assertEqual(self.task(pj)["def"]["brief"], "첫 줄\n  indented `x` $(y)\n")
            no_newline = self.scratch("c.txt", "no newline at end")
            self.add(pj, "u", "--brief-file", no_newline)
            self.assertEqual(self.task(pj, "u")["def"]["brief"], "no newline at end")

    def test_C2_1_the_path_is_not_recorded(self):
        with Project() as pj:
            d = self.session(pj)
            path = self.scratch("scratch-brief-name-xyz.txt", "the brief text\n")
            self.add(pj, "t", "--brief-file", path)
            self.assertEqual(self.task(pj)["def"]["brief"], "the brief text")
            for root, _, files in os.walk(d):
                for name in files:
                    with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                        self.assertNotIn("scratch-brief-name-xyz", fh.read(), name)

    def test_C2_1_brief_and_brief_file_together_are_refused_before_anything_is_written(self):
        self.assert_brief_file_exists()
        with Project() as pj:
            self.session(pj)
            before = pj.state()
            path = self.scratch("b.txt", "from file\n")
            code, out = run("add", "t", "--why", "a test task: no check decides it", "--brief", "inline", "--brief-file", path, "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertEqual(pj.state(), before)
            self.assertNotIn("t", pj.state().get("tasks", {}))

    def test_C2_1_an_empty_brief_file_is_refused(self):
        with Project() as pj:
            self.session(pj)
            before = pj.state()
            path = self.scratch("empty.txt", "")
            code, out = run("add", "t", "--why", "a test task: no check decides it", "--brief-file", path, "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertIn("the brief file is empty", out)
            self.assertEqual(pj.state(), before)

    def test_C2_1_an_empty_stdin_brief_is_refused(self):
        with Project() as pj:
            self.session(pj)
            before = pj.state()
            line = "%s %s add t --why 'a test task: no check decides it' --brief-file - --target %s" % (shlex.quote(sys.executable), shlex.quote(ENGINE), shlex.quote(pj.dir))
            res = self.shell(line, stdin="")
            self.assertNotEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("the brief file is empty", res.stdout + res.stderr)
            self.assertEqual(pj.state(), before)


class C2_2_Amend(Base):
    def test_C2_2_check_replaced_and_run_decided_by_the_new_check(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "make it", "--check", FAIL)
            code, out = run("run", "t", "--target", pj.dir)
            self.assertNotEqual(self.task(pj)["status"], "done", out)
            code, out = run("amend", "t", "--check", PASS, "--why", "the check was wrong", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj)
            self.assertEqual(ts["def"]["checks"], [argv(PASS)])
            entry = ts["amended"][0]
            self.assertEqual(entry["checks"], [argv(FAIL)])
            self.assertNotIn("brief", entry)
            self.assertEqual(entry["why"], "the check was wrong")
            self.assertIsInstance(entry.get("by"), dict)
            self.assertIn("agent", entry["by"])
            self.assertTrue(entry.get("at"))
            code, out = run("run", "t", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj)["status"], "done", out)

    def test_C2_2_repeated_check_replaces_the_whole_list(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--check", FAIL, "--check", PASS)
            code, out = run("amend", "t", "--check", PASS2, "--check", PASS, "--why", "two right ones", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj)
            self.assertEqual(ts["def"]["checks"], [argv(PASS2), argv(PASS)])
            self.assertEqual(ts["amended"][0]["checks"], [argv(FAIL), argv(PASS)])

    def test_C2_2_brief_amend_keeps_the_old_brief_in_history(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old words", "--check", FAIL)
            code, out = run("amend", "t", "--brief", "new words here", "--why", "lost a phrase", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj)
            self.assertEqual(ts["def"]["brief"], "new words here")
            self.assertEqual(ts["def"]["checks"], [argv(FAIL)])
            self.assertEqual(ts["amended"][0]["brief"], "old words")
            self.assertNotIn("checks", ts["amended"][0])
            # a second amend is a second entry
            path = self.scratch("b.txt", "third `version` $(x)\n")
            code, out = run("amend", "t", "--brief-file", path, "--why", "again", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj)
            self.assertEqual(ts["def"]["brief"], "third `version` $(x)")
            self.assertEqual([e["brief"] for e in ts["amended"]], ["old words", "new words here"])

    def test_C2_2_brief_and_checks_in_one_amend(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL)
            code, out = run("amend", "t", "--brief", "new", "--check", PASS, "--why", "both", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj)
            self.assertEqual((ts["def"]["brief"], ts["def"]["checks"]), ("new", [argv(PASS)]))
            self.assertEqual((ts["amended"][0]["brief"], ts["amended"][0]["checks"]), ("old", [argv(FAIL)]))

    def test_C2_2_by_and_delegated_sign_the_amendment(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old")
            code, out = run("amend", "t", "--brief", "new", "--why", "kim said", "--by", "kim", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj)["amended"][0]["by"], "kim")
            code, out = run("amend", "t", "--brief", "newer", "--why", "delegated", "--delegated", "owner: fix briefs", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj)["amended"][1]["delegated"], "owner: fix briefs")

    def test_C2_2_why_is_required(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old")
            before = pj.state()
            code, out = run("amend", "t", "--brief", "new", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertEqual(pj.state(), before)

    def test_C2_2_nothing_given_is_refused(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL)
            before = pj.state()
            code, out = run("amend", "t", "--why", "nothing", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertEqual(pj.state(), before)

    def test_C2_2_amend_never_changes_who_does_it_or_its_tests_scope_closes_gate(self):
        with Project() as pj:
            self.session(pj)
            write(os.path.join(pj.dir, "test_x.py"), "# an existing test\n")
            os.makedirs(os.path.join(pj.dir, "src"))
            self.add(pj, "t", "--brief", "old", "--check", FAIL, "--tests", "test_x.py", "--scope", "src",
                     "--closes", "Q-a", "--gate", "human", "--role", "session", "--why", "mine")
            old = dict(self.task(pj)["def"])
            code, out = run("amend", "t", "--brief", "new", "--check", PASS, "--why", "fix", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            new = dict(self.task(pj)["def"])
            for key in ("brief", "checks"):
                old.pop(key); new.pop(key)
            self.assertEqual(new, old)


class C2_3_Refusals(Base):
    def refused(self, pj, *amend, needle=None):
        before = pj.state()
        code, out = run("amend", *amend, "--target", pj.dir)
        self.assertNotEqual(code, 0, out)
        if needle:
            self.assertIn(needle, out)
        self.assertEqual(pj.state(), before)
        return out

    def test_C2_3_a_plan_runs_task_is_refused(self):
        self.assert_amend_exists()
        with Project() as pj:
            plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "providers": {"implementer": "session"},
                    "tasks": [{"id": "S1", "role": "implementer", "brief": "old", "checks": [[sys.executable, "check.py"]]}]}
            write(os.path.join(pj.dir, "plan.json"), plan)
            code, out = run("init", "--plan", os.path.join(pj.dir, "plan.json"), "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.refused(pj, "S1", "--brief", "new", "--why", "x")

    def test_C2_3_a_done_task_is_refused(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", PASS)
            code, out = run("run", "t", "--target", pj.dir)
            self.assertEqual(self.task(pj)["status"], "done", out)
            self.refused(pj, "t", "--brief", "new", "--why", "x")
            self.refused(pj, "t", "--check", PASS2, "--why", "x")

    def test_C2_3_a_dropped_task_is_refused(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL)
            self.assertEqual(run("drop", "t", "--why", "cancel", "--target", pj.dir)[0], 0)
            self.refused(pj, "t", "--brief", "new", "--why", "x")

    def test_C2_3_a_closed_run_is_refused(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old")
            self.assertEqual(run("drop", "t", "--why", "cancel", "--target", pj.dir)[0], 0)
            code, out = run("close", "--target", pj.dir, *UNCOMMITTED)
            self.assertEqual(code, 0, out)
            before = pj.state()
            code, out = run("amend", "t", "--brief", "new", "--why", "x", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertEqual(pj.state(), before)

    def test_C2_3_check_on_a_task_with_no_checks_is_refused_with_the_add_line(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old")
            self.refused(pj, "t", "--check", PASS, "--why", "x", needle="chongdae add t --check")

    def test_C2_3_an_unchanged_brief_is_refused_as_nothing_to_amend(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "same", "--check", FAIL)
            self.refused(pj, "t", "--brief", "same", "--why", "x", needle="nothing to amend")

    def test_C2_3_unchanged_checks_are_refused_as_nothing_to_amend(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "b", "--check", FAIL)
            self.refused(pj, "t", "--check", FAIL, "--why", "x", needle="nothing to amend")

    def test_C2_3_a_live_pending_check_is_refused(self):
        self.assert_amend_exists()
        with Project() as pj:
            d = self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL)
            write(c.work_path(d, "t.checks.pending.json"), {"pid": os.getpid()})
            out = self.refused(pj, "t", "--check", PASS, "--why", "x")
            self.assertIn("t.checks", out)
            # once the process is gone the same amend goes through
            write(c.work_path(d, "t.checks.pending.json"), {"pid": 2 ** 30})
            code, out = run("amend", "t", "--check", PASS, "--why", "x", "--target", pj.dir)
            self.assertEqual(code, 0, out)


class C2_4_Ownership(Base):
    def test_C2_4_another_sessions_task_is_refused_before_anything_is_written(self):
        self.assert_amend_exists()
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL)
            before = pj.state()
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            with patch.object(c, "commit_record") as commit:
                code, out = run("amend", "t", "--brief", "new", "--check", PASS, "--why", "mine now", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertIn("another session", out)
            self.assertEqual(pj.state(), before)
            commit.assert_not_called()


class C2_5_History(Base):
    def test_C2_5_evidence_of_the_old_contract_moves_under_superseded(self):
        with Project() as pj:
            d = self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL, "--before", "quibble")
            state = pj.state()
            ts = state["tasks"]["t"]
            evidence = {"checks-passed": [{"check": "x", "exit": 0}], "checks-tree": "abc123", "checks-source": "src",
                        "review": {"verdict": "accept"}, "verified_by": {"agent": "v"}, "verdict-given": "accept", "checked": ["y"]}
            ts.update(evidence)
            fp = c.contract_fingerprint(pj.dir, d, "t")
            quibble = {"when": "before", "contract-fingerprint": fp, "answer": {"status": "done"}}
            ts["stages"] = {"quibble": quibble}
            c.save_state(d, state)
            with patch.object(c, "commit_record", wraps=c.commit_record) as commit:
                code, out = run("amend", "t", "--check", PASS, "--why", "wrong check", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertTrue(commit.called, "the amendment is committed like other judgments")
            ts = self.task(pj)
            superseded = ts["amended"][-1]["superseded"]
            for key, value in evidence.items():
                self.assertEqual(superseded.get(key), value, key)
                self.assertNotIn(key, ts, key)
            self.assertEqual(superseded["stages"]["quibble"], quibble)
            self.assertNotIn("quibble", ts.get("stages", {}))

    def test_C2_5_no_check_non_claim_not_added_back_after_checks_amend(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL)
            code, out = run("amend", "t", "--check", PASS, "--why", "fix", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            run("run", "t", "--target", pj.dir)
            ts = self.task(pj)
            self.assertEqual(ts["status"], "done")
            self.assertFalse([n for n in ts.get("non-claims", []) if "no check decides" in n])


class C2_6_Output(Base):
    def test_C2_6_brief_amend_prints_the_character_counts_and_what_next(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "abcdef", "--check", FAIL)
            code, out = run("amend", "t", "--brief", "abcdefghi", "--why", "x", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("amended t: brief (6 → 9 characters)", out)
            self.assertIn("chongdae run", out)

    def test_C2_6_checks_amend_prints_old_and_new(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "b", "--check", FAIL)
            code, out = run("amend", "t", "--check", PASS, "--why", "x", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("amended t:", out)
            self.assertRegex(out, r"checks: `[^`]*sys\.exit\(3\)[^`]*` → `[^`]*-c pass`")
            self.assertIn("chongdae run", out)

    def test_C2_6_show_tells_each_amendment_with_reason_and_signer(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "old", "--check", FAIL)
            self.assertEqual(run("amend", "t", "--brief", "new", "--why", "reason-one-zq", "--by", "Ondalzq", "--target", pj.dir)[0], 0)
            self.assertEqual(run("amend", "t", "--check", PASS, "--why", "reason-two-zq", "--target", pj.dir)[0], 0)
            code, out = run("show", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("reason-one-zq", out)
            self.assertIn("Ondalzq", out)
            self.assertIn("reason-two-zq", out)
            self.assertIn("amend", out)

    def test_C2_6_help_lists_amend(self):
        code, out = run("--help")
        self.assertRegex(out, r"\{[^}]*\bamend\b[^}]*\}")
        self.assertRegex(out, r"(?m)^\s+amend\s")


class C2_7_Docs(unittest.TestCase):
    def read(self, *rel):
        path = os.path.join(REPO, "plugin", *rel)
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_C2_7_readme_documents_brief_file_and_amend(self):
        text = self.read("README.md")
        self.assertIn("--brief-file", text)
        self.assertIn("/chongdae:amend", text)

    def test_C2_7_command_adapter_is_the_one_engine_action(self):
        text = self.read("commands", "amend.md")
        self.assertIn('chongdae.py" amend $ARGUMENTS', text)
        self.assertTrue(text.startswith("---\ndescription:"))

    def test_C2_7_run_skill_says_brief_file_and_amend(self):
        text = self.read("skills", "run", "SKILL.md")
        lines = [ln for ln in text.splitlines() if "--brief-file" in ln]
        self.assertTrue(lines, "the run skill never names --brief-file")
        self.assertTrue(any("amend" in ln for ln in lines), "the sentence with --brief-file does not say a wrong brief or check is amended")


NITPICK_DONE = {"status": "done", "summary": "wrote", "non-claims": [], "tests": ["test_a.py"]}
IMPL_DONE = {"status": "done", "summary": "built", "verified": [], "decisions": [], "non-claims": []}


class C10_TestsRouting(Base):
    """C10: a task that writes tests goes to the lock's nitpick whether its test files exist or not."""

    def project(self, pj, roles=("implementer", "nitpick"), extra=None, commit=("test_a.py",)):
        lock = {}
        if "implementer" in roles:
            lock["implementer"] = pj.fake_provider(IMPL_DONE, "impl")
        if "nitpick" in roles:
            lock["nitpick"] = pj.fake_provider(NITPICK_DONE, "teujip")
        lock.update(extra or {})
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": lock})
        for f in commit:
            write(os.path.join(pj.dir, f), "import unittest\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"], cwd=pj.dir, check=True)
        self.session(pj)

    def test_C10_1_reproducer_existing_tests_file_goes_to_the_nitpick(self):
        with Project() as pj:
            self.project(pj)
            code, out = run("add", "t", "--why", "a test task: no check decides it", "--tests", "test_a.py", "--brief", "add a case", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("nitpick does it (the lock's provider)", out)
            self.assertNotIn("Work, then", out, "the session was told to do the nitpick's task")
            ts = self.task(pj)
            self.assertEqual(ts["def"]["role"], "nitpick", ts["def"])
            self.assertNotIn("self-performed", ts)

    def test_C10_1_new_tests_file_still_goes_to_the_nitpick(self):
        with Project() as pj:
            self.project(pj)
            code, out = run("add", "t", "--why", "a test task: no check decides it", "--tests", "test_new.py", "--brief", "new suite", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("nitpick does it (the lock's provider)", out)
            self.assertEqual(self.task(pj)["def"]["role"], "nitpick")

    def test_C10_1_mixed_existing_and_new_tests_files_go_to_the_nitpick(self):
        with Project() as pj:
            self.project(pj)
            self.add(pj, "t", "--tests", "test_a.py", "test_new.py", "--brief", "amend and add")
            self.assertEqual(self.task(pj)["def"]["role"], "nitpick")

    def test_C10_1_existing_tests_run_by_the_nitpick_provider(self):
        with Project() as pj:
            self.project(pj)
            self.add(pj, "t", "--tests", "test_a.py", "--brief", "add a case")
            code, out = run("run", "t", "--target", pj.dir)
            ts = self.task(pj)
            self.assertNotEqual((ts.get("performed_by") or {}).get("provider"), "session", (code, out, ts.get("performed_by")))
            self.assertIn("teujip.py", " ".join((ts.get("performed_by") or {}).get("argv") or []), (code, out, ts.get("performed_by")))

    def test_C10_1_requires_loopback_hires_the_nitpick_alternate_for_existing_tests(self):
        with Project() as pj:
            self.project(pj, extra={"nitpick@loopback": pj.fake_provider(NITPICK_DONE, "teujip_loop")})
            code, out = run("add", "t", "--why", "a test task: no check decides it", "--tests", "test_a.py", "--brief", "add a case", "--requires", "loopback", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("nitpick@loopback does it (the lock's alternate for loopback)", out)
            self.assertEqual(self.task(pj)["def"]["role"], "nitpick")

    def test_C10_1_no_nitpick_in_the_lock_leaves_it_the_sessions(self):
        with Project() as pj:
            self.project(pj, roles=("implementer",))
            code, out = run("add", "t", "--why", "a test task: no check decides it", "--tests", "test_a.py", "--brief", "add a case", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("Work, then", out)
            ts = self.task(pj)
            self.assertEqual(ts["def"]["role"], "session", ts["def"])
            self.assertNotIn("self-performed", ts)

    def test_C10_2_role_session_without_why_is_refused_for_existing_tests(self):
        with Project() as pj:
            self.project(pj)
            code, out = run("add", "t", "--role", "session", "--tests", "test_a.py", "--brief", "add a case", "--target", pj.dir)
            self.assertNotEqual(code, 0, "a session taking the nitpick's task without --why was accepted: %s" % out)
            self.assertIn("--why", out)
            self.assertIn("nitpick", out)
            self.assertNotIn("t", pj.state().get("tasks", {}), "a refused add recorded the task")

    def test_C10_2_role_session_with_why_is_recorded_self_performed_instead_of_nitpick(self):
        with Project() as pj:
            self.project(pj)
            self.add(pj, "t", "--role", "session", "--why", "one case, quicker than a call", "--tests", "test_a.py", "--brief", "add a case")
            ts = self.task(pj)
            self.assertEqual(ts["def"]["role"], "session")
            self.assertIn("self-performed", ts, "the session's take of a tests task is not on record")
            self.assertEqual(ts["self-performed"]["instead-of"], "nitpick", ts["self-performed"])
            self.assertEqual(ts["self-performed"]["why"], "one case, quicker than a call")

    def test_C10_2_role_session_with_why_new_tests_is_self_performed_instead_of_nitpick(self):
        with Project() as pj:
            self.project(pj)
            self.add(pj, "t", "--role", "session", "--why", "the sandbox has no port", "--tests", "test_new.py", "--brief", "new suite")
            ts = self.task(pj)
            self.assertEqual(ts["self-performed"]["instead-of"], "nitpick", ts.get("self-performed"))

    def test_C10_2_role_subagent_unchanged(self):
        with Project() as pj:
            self.project(pj)
            self.add(pj, "t", "--role", "subagent", "--tests", "test_a.py", "--brief", "add a case")
            ts = self.task(pj)
            self.assertEqual(ts["def"]["role"], "subagent")
            self.assertNotIn("self-performed", ts)

    def test_C10_2_role_nitpick_unchanged(self):
        with Project() as pj:
            self.project(pj)
            code, out = run("add", "t", "--role", "nitpick", "--tests", "test_a.py", "--brief", "add a case", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj)
            self.assertEqual(ts["def"]["role"], "nitpick")
            self.assertNotIn("self-performed", ts)

    def test_C10_3_check_with_existing_tests_is_the_implementers(self):
        with Project() as pj:
            self.project(pj)
            code, out = run("add", "b", "--tests", "test_a.py", "--check", PASS, "--brief", "build", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("implementer does it (the lock's provider)", out)
            self.assertEqual(self.task(pj, "b")["def"]["role"], "implementer")

    def test_C10_3_no_tests_no_check_stays_the_sessions(self):
        with Project() as pj:
            self.project(pj)
            code, out = run("add", "p", "--why", "a test task: no check decides it", "--brief", "a plan section", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj, "p")["def"]["role"], "session")
            self.assertNotIn("self-performed", self.task(pj, "p"))

    def test_C10_3_dispute_reopens_a_session_taken_tests_task_with_the_writer_it_has(self):
        with Project() as pj:
            self.project(pj)
            self.add(pj, "tests", "--role", "session", "--why", "one case", "--tests", "test_a.py", "--brief", "add a case")
            write(os.path.join(pj.dir, "test_a.py"), "# wrong\n")
            code, out = run("run", "tests", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.add(pj, "build", "--role", "session", "--why", "no port", "--tests", "test_a.py", "--check", PASS, "--brief", "build")
            code, out = run("dispute", "build", "--tests", "test_a.py", "--why", "the fixture is wrong", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj, "tests")
            self.assertEqual(ts["def"]["role"], "session", "the reopened tests task changed hands: %s" % ts["def"])
            self.assertNotEqual(ts["status"], "done", ts["status"])


class C10_4_Docs(unittest.TestCase):
    def read(self, *rel):
        path = os.path.join(REPO, "plugin", *rel)
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def nitpick_sentences(self, text):
        flat = re.sub(r"\s+", " ", text)
        return [s for s in re.split(r"(?<=[.;:])\s", flat) if "nitpick" in s and "--tests" in s]

    def test_C10_4_readme_add_section_says_new_or_existing_tests_go_to_the_nitpick(self):
        text = self.read("README.md")
        start = text.index("### `/chongdae:add`")
        end = text.find("\n### ", start + 1)
        section = text[start:end if end > 0 else None]
        flat = re.sub(r"\s+", " ", section)
        self.assertFalse("that do not exist yet to its `nitpick`" in flat, "the add section still routes only tests that do not exist yet to the nitpick")
        said = [s for s in self.nitpick_sentences(section) if "exist" in s]
        self.assertTrue(said, "the add section never says tests that exist go to the nitpick")
        self.assertTrue(any("existing" in s or "exist or not" in s or "whether" in s for s in said), said)

    def test_C10_4_run_skill_says_new_or_existing_tests_go_to_the_nitpick(self):
        text = self.read("skills", "run", "SKILL.md")
        flat = re.sub(r"\s+", " ", text)
        self.assertFalse("where F does not exist yet goes to its `nitpick`" in flat, "the run skill still routes only a --tests F that does not exist yet to the nitpick")
        said = [s for s in self.nitpick_sentences(text) if "exist" in s]
        self.assertTrue(said, "the run skill never says tests that exist go to the nitpick")
        self.assertTrue(any("existing" in s or "exist or not" in s or "whether" in s for s in said), said)


if __name__ == "__main__":
    unittest.main()
