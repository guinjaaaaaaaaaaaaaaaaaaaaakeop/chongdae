"""Contract K: a red run is the contract's red, and its record shows what failed.

`take … --checked-red COMMAND` and `retry … --checked-red COMMAND` once recorded any non-zero exit as "red as expected" —
a usage error of the command itself, a missing file or module, a crash before any test ran and a process killed by a signal
looked the same as a suite with failing tests, and the record kept only the output's last six lines. These tests drive the
two commands through the CLI the way a session meets the defect (a session run, a tests task the lock gives to a fake
nitpick that answers `blocked`, then `take` or `retry`), and `run_checked` directly where that is clearer.

Each command under test is a small script written into the temporary project. Offline; temporary directories only.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import test_chongdae
from test_chongdae import Project, run, write
import chongdae as c

REPO = os.path.dirname(os.path.abspath(__file__))


def read_text(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()
README = os.path.join(test_chongdae.PLUGIN, "README.md")
RUN_SKILL = os.path.join(test_chongdae.PLUGIN, "skills", "run", "SKILL.md")

BLOCKED = {"status": "blocked", "summary": "no port here", "verified": [], "decisions": [], "non-claims": []}

# a unittest module with two failing tests and one passing
TWO_FAIL_ONE_PASS = textwrap.dedent("""\
    import unittest

    class T(unittest.TestCase):
        def test_a(self):
            self.fail("a is red before the build")

        def test_b(self):
            self.assertEqual(1, 2)

        def test_c(self):
            pass

    if __name__ == "__main__":
        unittest.main()
    """)

# the same module whose tests also start subprocesses that print argparse's usage error and a "No module named" line
TWO_FAIL_WITH_NOISY_SUBPROCESSES = textwrap.dedent("""\
    import subprocess, sys, unittest

    class T(unittest.TestCase):
        def test_a(self):
            subprocess.run([sys.executable, "-c", "import argparse; argparse.ArgumentParser(prog='sub').parse_args(['--nope'])"])
            self.fail("a is red before the build")

        def test_b(self):
            subprocess.run([sys.executable, "-c", "import no_such_module_for_this_test"])
            self.assertEqual(1, 2)

        def test_c(self):
            pass

    if __name__ == "__main__":
        unittest.main()
    """)

PLAIN_RUNNER_RED = textwrap.dedent("""\
    print("PASS a")
    print("FAIL b -- AssertionError: b is red before the build")
    print("1 failed")
    raise SystemExit(1)
    """)

PLAIN_RUNNER_GREEN = textwrap.dedent("""\
    print("PASS a")
    print("SKIP c -- no port on this host")
    print("all passed")
    """)

PYTEST_FORM_RED = textwrap.dedent("""\
    print("============================= test session starts ==============================")
    print("collected 3 items")
    print("")
    print("test_x.py F..                                                            [100%]")
    print("")
    print("=================================== FAILURES ===================================")
    print("___________________________________ test_a _____________________________________")
    print("")
    print("    def test_a():")
    print(">       assert 1 == 2")
    print("E       assert 1 == 2")
    print("")
    print("test_x.py:3: AssertionError")
    print("=========================== short test summary info ============================")
    print("FAILED test_x.py::test_a - assert 1 == 2")
    print("========================= 1 failed, 2 passed in 0.03s ==========================")
    raise SystemExit(1)
    """)


class Base(unittest.TestCase):
    """A session run in a temporary git project; the lock hires a fake nitpick for tests tasks, and it answers `blocked`, so
    the task is stopped on a provider response: `take` and `retry` both apply."""

    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.pj = Project()
        self.addCleanup(lambda: shutil.rmtree(self.pj.dir, ignore_errors=True))
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"],
                       cwd=self.pj.dir, check=True)

    # -- the session run ------------------------------------------------------------------------------------------------

    def session(self, tid="u", tests="test_b.py"):
        """init, a tests task hired to a fake nitpick that answers blocked, one `run`: the task is stopped on its answer."""
        pj = self.pj
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": pj.fake_provider(BLOCKED)}})
        code, out = run("init", "--session", "--goal", "g", "--target", pj.dir)
        self.assertEqual(code, 0, out)
        code, out = run("add", tid, "--tests", tests, "--target", pj.dir)
        self.assertEqual(code, 0, out)
        code, out = run("run", "--target", pj.dir)
        self.assertEqual(code, c.DECISION, out)
        self.assertEqual((self.task(tid).get("response") or {}).get("status"), "blocked")
        return c.run_dir(pj.dir)

    def script(self, name, body):
        """A script in the temporary project; returns the `--checked-red` command line that runs it."""
        write(os.path.join(self.pj.dir, name), body)
        return sys.executable + " " + name

    def task(self, tid="u"):
        return self.pj.state()["tasks"].get(tid, {})

    def committed(self, d, tid="u"):
        """The committed record (tasks/<id>.json) and this machine's overlay (local/tasks/<id>.json), as text."""
        pub = read_text(os.path.join(d, "tasks", tid + ".json"))
        loc_path = os.path.join(d, c.LOCAL, "tasks", tid + ".json")
        loc = read_text(loc_path) if os.path.exists(loc_path) else ""
        return pub, loc

    # -- refusals -------------------------------------------------------------------------------------------------------

    def assert_refusal_message(self, msg, cmd, code, why_words):
        """The message names the command, its exit and why it is not red."""
        self.assertIn(cmd, msg, "the refusal does not name the command: %r" % msg)
        self.assertIn("exit %d" % code, msg, "the refusal does not name the exit: %r" % msg)
        low = msg.lower()
        self.assertTrue(any(w.lower() in low for w in why_words),
                        "the refusal does not say why it is not red (none of %r): %r" % (why_words, msg))

    def assert_run_checked_refuses(self, cmd, code, why_words):
        with self.assertRaises(SystemExit) as cm:
            c.run_checked(self.pj.dir, [], red=[cmd])
        self.assert_refusal_message(str(cm.exception), cmd, code, why_words)

    def assert_take_refuses(self, cmd, code, why_words, tid="u"):
        """`take … --checked-red CMD` exits non-zero before anything is recorded: the take did not happen."""
        before = self.task(tid)
        out_code, out = run("take", tid, "--why", "the sandbox had no port", "--checked-red", cmd, "--target", self.pj.dir)
        self.assertNotEqual(out_code, 0, "take recorded a run that cannot have reached the tests: %s" % out)
        self.assert_refusal_message(out, cmd, code, why_words)
        self.assertNotIn("red as expected", out)
        after = self.task(tid)
        self.assertNotIn("checked", after, "a refused run was recorded: %r" % after.get("checked"))
        self.assertNotIn("taken", after, "the take happened on a refused run")
        self.assertNotIn("self-performed", after, "the take happened on a refused run")
        self.assertEqual(before.get("attempts"), after.get("attempts"), "the take moved the attempt on a refused run")
        show = run("show", "--target", self.pj.dir)[1]
        self.assertNotIn("checked by chongdae at", show, show)

    def assert_retry_refuses(self, cmd, code, why_words, tid="u"):
        """`retry … --checked-red CMD` exits non-zero before anything is recorded: no attempt is kept, nothing checked."""
        before = self.task(tid)
        out_code, out = run("retry", tid, "--checked-red", cmd, "--target", self.pj.dir)
        self.assertNotEqual(out_code, 0, "retry recorded a run that cannot have reached the tests: %s" % out)
        self.assert_refusal_message(out, cmd, code, why_words)
        after = self.task(tid)
        self.assertNotIn("checked", after, "a refused run was recorded: %r" % after.get("checked"))
        self.assertEqual(before.get("attempts"), after.get("attempts"), "retry kept an attempt on a refused run")
        self.assertEqual((after.get("response") or {}).get("status"), "blocked", "retry moved the stopped answer on a refused run")

    # -- red runs -------------------------------------------------------------------------------------------------------

    def take_red(self, cmd, tid="u", expect_exit=1):
        """`take … --checked-red CMD` of a run that is red as expected; returns (printed output, the record entry)."""
        code, out = run("take", tid, "--why", "the sandbox had no port", "--checked-red", cmd, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("exit %d — red as expected" % expect_exit, out, out)
        ts = self.task(tid)
        self.assertIn("checked", ts)
        rec = ts["checked"]["ran"][0]
        self.assertEqual(rec["command"], cmd)
        self.assertEqual(rec["exit"], expect_exit)
        self.assertEqual(rec["outcome"], "red as expected")
        self.assertEqual(rec["expect"], "fail")
        return out, rec

    def record_says_none_recognized(self, rec):
        """K4.5: `"result": "none recognized"` or an equivalent key — the value is the contract's, the key is the README's."""
        return any(isinstance(v, str) and "none recognized" in v for v in rec.values())

    def whole_output_file(self, d, rec):
        """K4.4: the file under the run's local directory a record entry names, found by its value at any depth, whatever
        the key. Returns (its real path, the string that named it, the entry's top-level key holding that string)."""
        local = os.path.realpath(os.path.join(d, c.LOCAL))

        def strings(v):
            if isinstance(v, str):
                yield v
            elif isinstance(v, dict):
                for x in v.values():
                    yield from strings(x)
            elif isinstance(v, list):
                for x in v:
                    yield from strings(x)

        for key, sub in rec.items():
            for v in strings(sub):
                for cand in (v, os.path.join(d, v), os.path.join(local, v), os.path.join(self.pj.dir, v)):
                    full = os.path.realpath(cand)
                    if os.path.isfile(full) and full.startswith(local + os.sep):
                        return full, v, key
        return None, None, None


# ====================================================================================================================
# K1 — refused: a run that cannot have reached the contract's tests


class K1Refusals(Base):

    def test_K1_1_a_process_ended_by_a_signal_is_refused(self):
        """K1.1: a negative return code (the subprocess was ended by a signal) is not a red run. Skip-free: the script ends
        itself with SIGTERM, which a POSIX host reports as -15."""
        self.session()
        cmd = self.script("test_b.py", "import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n")
        with self.assertRaises(SystemExit) as cm:
            c.run_checked(self.pj.dir, [], red=[cmd])
        msg = str(cm.exception)
        self.assertIn(cmd, msg)
        self.assertTrue(any(w in msg for w in ("-15", "signal", "SIGTERM")), "the refusal names neither the signal nor the exit: %r" % msg)
        self.assertNotIn("red as expected", msg)
        # through the CLI: the take did not happen
        code, out = run("take", "u", "--why", "the sandbox had no port", "--checked-red", cmd, "--target", self.pj.dir)
        self.assertNotEqual(code, 0, out)
        self.assertIn(cmd, out)
        self.assertTrue(any(w in out for w in ("-15", "signal", "SIGTERM")), out)
        ts = self.task()
        self.assertNotIn("checked", ts)
        self.assertNotIn("taken", ts)

    def test_K1_2_a_missing_program_and_a_timeout_stay_refused(self):
        """K1.2: exit 127 (no such program) and 124 (timed out) did not run — refused today, kept so."""
        self.session()
        self.assert_run_checked_refuses("no-such-command-xyz-k", 127, ("did not run", "not there", "missing", "no such"))
        self.assert_take_refuses("no-such-command-xyz-k", 127, ("did not run", "not there", "missing", "no such"))
        sleeper = self.script("sleeper.py", "import time\ntime.sleep(20)\n")
        with patch.dict(os.environ, {"CHONGDAE_CHECK_TIMEOUT": "1"}):
            self.assert_run_checked_refuses(sleeper, 124, ("timed out", "timeout", "did not run"))
            self.assert_retry_refuses(sleeper, 124, ("timed out", "timeout", "did not run"))

    def test_K1_3_a_usage_error_of_the_command_itself_is_refused(self):
        """K1.3: exit 2, a `usage:` line and `<prog>: error: …`, no test result — argparse refused the command's own
        arguments; no test ran."""
        self.session()
        cmd = self.script("test_b.py", "import argparse\nargparse.ArgumentParser(prog='test_b.py').parse_args(['--nope'])\n")
        why = ("usage", "did not run", "cannot have reached", "no test")
        self.assert_run_checked_refuses(cmd, 2, why)
        self.assert_take_refuses(cmd, 2, why)
        self.assert_retry_refuses(cmd, 2, why)

    def test_K1_3_a_usage_error_from_the_command_itself_on_retry_records_nothing(self):
        """K1.3 on `retry`: refused before anything is recorded — the attempt stays as it was, no `checked`."""
        self.session()
        cmd = self.script("test_b.py", "import argparse\nargparse.ArgumentParser(prog='test_b.py').parse_args(['--nope', 'x'])\n")
        self.assert_retry_refuses(cmd, 2, ("usage", "did not run", "cannot have reached", "no test"))
        d = c.run_dir(self.pj.dir)
        pub, loc = self.committed(d)
        self.assertNotIn('"checked"', pub)
        self.assertNotIn('"checked"', loc)

    def test_K1_4_a_missing_file_is_refused(self):
        """K1.4: Python's `can't open file …` — the command named a test file that does not exist."""
        self.session()
        cmd = sys.executable + " missing_file.py"
        self.assertFalse(os.path.exists(os.path.join(self.pj.dir, "missing_file.py")))
        why = ("can't open file", "cannot open", "not found", "no such file", "does not exist", "did not run", "no test")
        self.assert_run_checked_refuses(cmd, 2, why)
        self.assert_take_refuses(cmd, 2, why)

    def test_K1_4_a_missing_module_is_refused(self):
        """K1.4: `No module named …` / `ModuleNotFoundError` before any test, exit 1."""
        self.session()
        cmd = self.script("test_b.py", "import no_such_module_for_this_test\n")
        why = ("no module named", "modulenotfounderror", "missing module", "did not run", "no test")
        self.assert_run_checked_refuses(cmd, 1, why)
        self.assert_take_refuses(cmd, 1, why)
        self.assert_retry_refuses(cmd, 1, why)

    def test_K1_5_an_interpreter_error_before_any_test_is_refused(self):
        """K1.5: a traceback whose final exception is not an AssertionError, and no test result."""
        self.session()
        cmd = self.script("test_b.py", "import json\nraise RuntimeError('the fixture could not be built')\n")
        why = ("traceback", "runtimeerror", "before any test", "crash", "interpreter", "did not run", "no test")
        self.assert_run_checked_refuses(cmd, 1, why)
        self.assert_take_refuses(cmd, 1, why)

    def test_K1_5_a_syntax_error_is_refused(self):
        """K1.5: `SyntaxError` — the test file itself does not parse; no test ran."""
        self.session()
        cmd = self.script("test_b.py", "def (:\n    pass\n")
        why = ("syntaxerror", "syntax error", "before any test", "interpreter", "did not run", "no test")
        self.assert_run_checked_refuses(cmd, 1, why)
        self.assert_take_refuses(cmd, 1, why)
        self.assert_retry_refuses(cmd, 1, why)

    def test_K1_5_an_assertion_error_traceback_is_not_refused(self):
        """K1.5's boundary: a bare traceback ending in AssertionError is not an interpreter error — nothing in K1 names it,
        so it stays red as expected (K2), and with no test result recognized the record says so (K4.5)."""
        self.session()
        cmd = self.script("test_b.py", "assert 1 == 2, 'red before the build'\n")
        out, rec = self.take_red(cmd)
        self.assertTrue(self.record_says_none_recognized(rec), "no test result was recognized, and the record does not say so: %r" % rec)
        self.assertFalse(rec.get("failures"), rec.get("failures"))

    def test_K1_6_unittest_that_could_not_import_its_module_is_refused(self):
        """K1.6: `python -m unittest test_broken` whose only failure is the loader's (`unittest.loader._FailedTest`,
        "Failed to import test module") — unittest ran one test, its own, and none of the contract's."""
        self.session()
        write(os.path.join(self.pj.dir, "test_broken.py"), "import no_such_module_for_this_test\n")
        cmd = sys.executable + " -m unittest test_broken"
        why = ("failed to import", "_failedtest", "could not import", "import", "did not run", "no test")
        self.assert_run_checked_refuses(cmd, 1, why)
        self.assert_take_refuses(cmd, 1, why)
        self.assert_retry_refuses(cmd, 1, why)

    def test_K1_6_a_loader_failure_beside_tests_that_ran_is_red_as_expected(self):
        """K1.6's boundary: when other tests ran (and failed) beside the loader's failure, the run reached the tests —
        red as expected, with the real failures in the record."""
        self.session()
        write(os.path.join(self.pj.dir, "test_broken.py"), "import no_such_module_for_this_test\n")
        write(os.path.join(self.pj.dir, "test_two.py"), TWO_FAIL_ONE_PASS)
        cmd = sys.executable + " -m unittest test_broken test_two"
        out, rec = self.take_red(cmd)
        self.assertIn("failures", rec)
        heads = rec["failures"]
        self.assertTrue(any("test_a" in h for h in heads), heads)
        self.assertTrue(any("test_b" in h for h in heads), heads)
        self.assertIn("summary", rec)
        self.assertTrue(any(s.startswith("Ran 4 test") for s in rec["summary"]), rec["summary"])


# ====================================================================================================================
# K2 / K3 — red as expected, and what a test result is


class K2RedRuns(Base):

    def test_K2_a_unittest_module_with_failing_tests_is_red_as_expected(self):
        """K2: a test result with failures is red as expected; the record shows which (K4.1, K4.2)."""
        self.session()
        cmd = self.script("test_b.py", TWO_FAIL_ONE_PASS)
        out, rec = self.take_red(cmd)
        self.assertIn("summary", rec)
        self.assertTrue(any(s.startswith("Ran 3 tests in") for s in rec["summary"]), rec["summary"])
        self.assertTrue(any(s.startswith("FAILED (failures=2") for s in rec["summary"]), rec["summary"])
        self.assertIn("failures", rec)
        self.assertEqual(len(rec["failures"]), 2, rec["failures"])
        self.assertTrue(rec["failures"][0].startswith("FAIL: test_a"), rec["failures"])
        self.assertTrue(rec["failures"][1].startswith("FAIL: test_b"), rec["failures"])
        self.assertFalse(self.record_says_none_recognized(rec), rec)

    def test_K2_usage_text_and_module_errors_printed_by_subprocesses_do_not_refuse_a_red_run(self):
        """K2: the output holds `usage:` / `<prog>: error:` lines, a `No module named` line and tracebacks — printed by
        subprocesses the failing tests started — and a test result with failures: red as expected, not refused."""
        self.session()
        cmd = self.script("test_b.py", TWO_FAIL_WITH_NOISY_SUBPROCESSES)
        # the noise is really there
        done = subprocess.run([sys.executable, "test_b.py"], cwd=self.pj.dir, capture_output=True, text=True)
        noise = done.stdout + done.stderr
        self.assertIn("usage: sub", noise)
        self.assertIn("sub: error:", noise)
        self.assertIn("No module named", noise)
        self.assertIn("Traceback", noise)
        self.assertEqual(done.returncode, 1)
        rec = c.run_checked(self.pj.dir, [], red=[cmd])["ran"][0]
        self.assertEqual(rec["outcome"], "red as expected")
        out, rec = self.take_red(cmd)
        self.assertIn("failures", rec)
        self.assertEqual(len(rec["failures"]), 2, rec["failures"])
        self.assertTrue(all(h.startswith("FAIL: ") for h in rec["failures"]), rec["failures"])
        self.assertIn("summary", rec)
        self.assertTrue(any(s.startswith("FAILED (failures=2") for s in rec["summary"]), rec["summary"])

    def test_K2_a_plain_runners_failed_line_is_red_as_expected(self):
        """K2/K3: the product suites' own runner lines — `PASS a`, `FAIL b -- …`, `1 failed`."""
        self.session()
        cmd = self.script("test_b.py", PLAIN_RUNNER_RED)
        out, rec = self.take_red(cmd)
        self.assertIn("summary", rec)
        self.assertEqual(rec["summary"], ["1 failed"])
        self.assertIn("failures", rec)
        self.assertEqual(rec["failures"], ["FAIL b -- AssertionError: b is red before the build"])
        self.assertFalse(self.record_says_none_recognized(rec), rec)

    def test_K2_a_bare_system_exit_stays_red_and_says_no_test_result_was_recognized(self):
        """K2/K4.5: non-zero exit, no test result, none of K1's signs — red as expected as today, and the record says
        that no test result was recognized; no summary, no failures."""
        self.session()
        cmd = self.script("test_b.py", "raise SystemExit(1)\n")
        out, rec = self.take_red(cmd)
        self.assertTrue(self.record_says_none_recognized(rec), "the record does not say that no test result was recognized: %r" % rec)
        self.assertFalse(rec.get("summary"), rec.get("summary"))
        self.assertFalse(rec.get("failures"), rec.get("failures"))

    def test_K2_an_unknown_runners_output_stays_red_and_says_no_test_result_was_recognized(self):
        """K2: an unknown runner's words (no K3 line, no K1 sign) with exit 3 — red as expected, none recognized."""
        self.session()
        cmd = self.script("test_b.py", "print('checking the widgets')\nprint('the widgets are wrong')\nraise SystemExit(3)\n")
        out, rec = self.take_red(cmd, expect_exit=3)
        self.assertTrue(self.record_says_none_recognized(rec), rec)
        self.assertEqual(rec["tail"], ["checking the widgets", "the widgets are wrong"])

    def test_K2_a_zero_exit_is_passed_before_the_build_with_its_summary(self):
        """K2: a zero exit is recorded as passed before the build, as today; its summary is the runner's `all passed`,
        and a SKIP line is a test result, not a failure (K3)."""
        self.session()
        cmd = self.script("test_b.py", PLAIN_RUNNER_GREEN)
        code, out = run("take", "u", "--why", "the sandbox had no port", "--checked-red", cmd, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("exit 0 — passed before the build", out)
        rec = self.task()["checked"]["ran"][0]
        self.assertEqual(rec["outcome"], "passed before the build")
        self.assertIn("summary", rec)
        self.assertEqual(rec["summary"], ["all passed"])
        self.assertFalse(rec.get("failures"), rec.get("failures"))
        self.assertFalse(self.record_says_none_recognized(rec), rec)

    def test_K3_pytests_summary_and_failed_lines_are_a_test_result(self):
        """K3: pytest's `FAILED path::test - …` lines and its final `N failed, N passed in …s` summary."""
        self.session()
        cmd = self.script("test_b.py", PYTEST_FORM_RED)
        out, rec = self.take_red(cmd)
        self.assertIn("summary", rec)
        self.assertEqual(len(rec["summary"]), 1, rec["summary"])
        self.assertIn("1 failed, 2 passed in 0.03s", rec["summary"][0])
        self.assertIn("failures", rec)
        self.assertEqual(len(rec["failures"]), 1, rec["failures"])
        self.assertTrue(rec["failures"][0].startswith("FAILED test_x.py::test_a"), rec["failures"])
        self.assertFalse(self.record_says_none_recognized(rec), rec)

    def test_K3_a_runners_skip_line_alone_is_a_test_result(self):
        """K3: `SKIP name -- …` is a test result — a non-zero exit after it is red as expected and not "none recognized",
        and a skip is not a failure."""
        self.session()
        cmd = self.script("test_b.py", "print('SKIP a -- no port on this host')\nraise SystemExit(1)\n")
        out, rec = self.take_red(cmd)
        self.assertFalse(self.record_says_none_recognized(rec), "a SKIP line is a test result, yet the record says none was recognized: %r" % rec)
        self.assertFalse(rec.get("failures"), rec.get("failures"))
        self.assertIn("lines", rec, rec)   # K4.3 is on every record
        self.assertEqual(rec["lines"], 1)

    def test_K3_unittests_error_headers_count_as_failures(self):
        """K3/K4.2: unittest's `ERROR: …` headers are failing tests' headers too, in output order with the `FAIL:` ones."""
        self.session()
        cmd = self.script("test_b.py", textwrap.dedent("""\
            import unittest

            class T(unittest.TestCase):
                def test_a(self):
                    raise KeyError("a")

                def test_b(self):
                    self.fail("b")

            if __name__ == "__main__":
                unittest.main()
            """))
        out, rec = self.take_red(cmd)
        self.assertIn("failures", rec)
        self.assertEqual(len(rec["failures"]), 2, rec["failures"])
        self.assertTrue(rec["failures"][0].startswith("ERROR: test_a"), rec["failures"])
        self.assertTrue(rec["failures"][1].startswith("FAIL: test_b"), rec["failures"])
        self.assertIn("summary", rec)
        self.assertTrue(any(s.startswith("FAILED (failures=1, errors=1)") for s in rec["summary"]), rec["summary"])


# ====================================================================================================================
# K4 — the record: bounded in the commit, whole on this machine


class K4Record(Base):

    def test_K4_1_summary_keeps_at_most_five_result_lines_in_output_order(self):
        """K4.1: eight suites' `1 failed` lines in one output — the summary keeps at most 5 of them."""
        self.session()
        body = "".join("print('PASS a%d')\nprint('1 failed')\n" % i for i in range(8)) + "raise SystemExit(1)\n"
        cmd = self.script("test_b.py", body)
        out, rec = self.take_red(cmd)
        self.assertIn("summary", rec)
        self.assertTrue(1 <= len(rec["summary"]) <= 5, rec["summary"])
        self.assertTrue(all(s == "1 failed" for s in rec["summary"]), rec["summary"])

    def test_K4_2_failures_are_bounded_to_ten_headers_of_three_hundred_characters(self):
        """K4.2: thirty failing tests with long messages — at most 10 headers, each at most 300 characters, the first ones."""
        self.session()
        long_msg = "x" * 500
        body = "".join("print('FAIL t%02d -- AssertionError: %s')\n" % (i, long_msg) for i in range(30)) + "print('30 failed')\nraise SystemExit(1)\n"
        cmd = self.script("test_b.py", body)
        out, rec = self.take_red(cmd)
        self.assertIn("failures", rec)
        heads = rec["failures"]
        self.assertTrue(1 <= len(heads) <= 10, len(heads))
        for h in heads:
            self.assertLessEqual(len(h), 300, len(h))
        self.assertTrue(heads[0].startswith("FAIL t00 -- AssertionError: "), heads[0])
        self.assertTrue(heads[-1].startswith("FAIL t%02d -- " % (len(heads) - 1)), heads[-1])
        self.assertIn("summary", rec)
        self.assertEqual(rec["summary"], ["30 failed"])
        # the committed record stays bounded: summary, failures and tail together at most 21 lines
        d = c.run_dir(self.pj.dir)
        pub = json.loads(self.committed(d)[0])
        crec = pub["checked"]["ran"][0]
        together = len(crec.get("summary") or []) + len(crec.get("failures") or []) + len(crec.get("tail") or [])
        self.assertLessEqual(together, 21, crec)
        self.assertNotIn(long_msg, self.committed(d)[0])

    def test_K4_3_lines_counts_the_whole_output(self):
        """K4.3: the record says how many lines the whole output had — not the six the tail keeps."""
        self.session()
        body = "".join("print('line %d of the output')\n" % i for i in range(1, 38)) + \
               "print('FAIL z -- AssertionError: z')\nprint('PASS y')\nprint('1 failed')\nraise SystemExit(1)\n"
        cmd = self.script("test_b.py", body)
        out, rec = self.take_red(cmd)
        self.assertIn("lines", rec)
        self.assertEqual(rec["lines"], 40, rec)
        self.assertLessEqual(len(rec["tail"]), 6)

    def test_K4_4_the_whole_output_is_kept_under_local_and_named_only_in_the_overlay(self):
        """K4.4: the whole output goes to a file under the run's machine-local directory; the record names it under a private
        key, so the committed task file names no machine path and the local overlay names the file."""
        d = self.session()
        body = "".join("print('line %d of the output')\n" % i for i in range(1, 38)) + \
               "print('FAIL z -- AssertionError: z')\nprint('PASS y')\nprint('1 failed')\nraise SystemExit(1)\n"
        cmd = self.script("test_b.py", body)
        out, rec = self.take_red(cmd)
        path, named, key = self.whole_output_file(d, rec)
        self.assertIsNotNone(path, "no entry of the record names a file under the run's local directory: %r" % rec)
        kept = read_text(path)
        self.assertIn("line 1 of the output", kept)       # not in the tail: the whole output, not the kept lines
        self.assertIn("FAIL z -- AssertionError: z", kept)
        self.assertIn("1 failed", kept)
        pub, loc = self.committed(d)
        self.assertIn('"checked"', pub)
        self.assertNotIn(os.path.basename(path), pub, "the committed record names the local file")
        self.assertNotIn(named, pub, "the committed record names the local file")
        self.assertNotIn(self.pj.dir, pub)
        self.assertIn(os.path.basename(path), loc, "the overlay does not name the local file")
        # the public projection of the record keeps no private key: whatever key names the file is a private one
        public_rec = json.loads(pub)["checked"]["ran"][0]
        self.assertNotIn(key, public_rec, "the key naming the file is in the committed record: %s" % key)
        self.assertIn(key, c.PRIVATE_KEYS)

    def test_K4_a_retrys_record_moves_whole_into_the_attempt(self):
        """K4: an entry in an attempt (a retry's run, moved there when the next answer came) keeps the same keys."""
        d = self.session()
        cmd = self.script("test_b.py", TWO_FAIL_ONE_PASS)
        code, out = run("retry", "u", "--checked-red", cmd, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("exit 1 — red as expected", out)
        ts = self.task()
        self.assertIn("checked", ts)
        rec = ts["checked"]["ran"][0]
        for key in ("summary", "failures", "lines"):
            self.assertIn(key, rec, rec)
        path, named, key = self.whole_output_file(d, rec)
        self.assertIsNotNone(path, rec)
        # the next answer comes; the run moves the retry's run into the attempt it was run for
        code, out = run("run", "--target", self.pj.dir)
        self.assertEqual(code, c.DECISION, out)
        code, out = run("take", "u", "--why", "the sandbox had no port", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        ts = self.task()
        held = [a for a in ts.get("attempts") or [] if isinstance(a.get("checked"), dict)]
        self.assertEqual(len(held), 1, ts.get("attempts"))
        arec = held[0]["checked"]["ran"][0]
        self.assertEqual(arec["command"], cmd)
        for key in ("summary", "failures", "lines"):
            self.assertIn(key, arec, arec)
        self.assertEqual(arec["summary"], rec["summary"])
        self.assertEqual(arec["failures"], rec["failures"])
        self.assertEqual(arec["lines"], rec["lines"])
        apath, anamed, akey = self.whole_output_file(d, arec)
        self.assertEqual(apath, path, "the attempt's entry does not name the whole output")
        pub, loc = self.committed(d)
        self.assertNotIn(os.path.basename(path), pub)
        self.assertIn(os.path.basename(path), loc)

    def test_K4_a_checked_green_run_keeps_the_same_keys(self):
        """K4: every `--checked` record too — the entries of `checked.ran` for a `--checked` command keep summary and lines."""
        d = self.session()
        cmd = self.script("test_b.py", PLAIN_RUNNER_GREEN)
        code, out = run("take", "u", "--why", "the sandbox had no port", "--checked", cmd, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        rec = self.task()["checked"]["ran"][0]
        self.assertEqual(rec["exit"], 0)
        self.assertIn("summary", rec)
        self.assertEqual(rec["summary"], ["all passed"])
        self.assertIn("lines", rec)
        self.assertEqual(rec["lines"], 3)
        path, named, key = self.whole_output_file(d, rec)
        self.assertIsNotNone(path, rec)


# ====================================================================================================================
# K5 — what take, retry and show print


class K5Printed(Base):

    def test_K5_takes_line_keeps_red_as_expected_and_adds_the_summary(self):
        self.session()
        cmd = self.script("test_b.py", TWO_FAIL_ONE_PASS)
        out, rec = self.take_red(cmd)
        self.assertIn("exit 1 — red as expected", out)
        self.assertIn("FAILED (failures=2", out, "take's line does not add the summary: %s" % out)

    def test_K5_retrys_line_keeps_red_as_expected_and_adds_the_summary(self):
        self.session()
        cmd = self.script("test_b.py", PLAIN_RUNNER_RED)
        code, out = run("retry", "u", "--checked-red", cmd, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("exit 1 — red as expected", out)
        self.assertIn("1 failed", out, "retry's line does not add the summary: %s" % out)

    def test_K5_a_red_run_with_no_result_recognized_keeps_the_plain_line(self):
        """K5: with no summary there is nothing to add — the line is as today."""
        self.session()
        cmd = self.script("test_b.py", "raise SystemExit(1)\n")
        out, rec = self.take_red(cmd)
        line = [l for l in out.splitlines() if "red as expected" in l]
        self.assertEqual(len(line), 1, out)
        self.assertIn("exit 1 — red as expected", line[0])

    def test_K5_show_prints_the_summary_and_first_failures_under_the_checked_line(self):
        self.session()
        cmd = self.script("test_b.py", TWO_FAIL_ONE_PASS)
        self.take_red(cmd)
        show = run("show", "--target", self.pj.dir)[1]
        lines = show.splitlines()
        at = [i for i, l in enumerate(lines) if "checked by chongdae at" in l]
        self.assertEqual(len(at), 1, show)
        head = lines[at[0]]
        self.assertIn("exit 1", head)
        self.assertIn("red as expected", head)
        # what follows inside the task's own block: up to the next unindented line (the next task, or the run's footer)
        below = []
        for l in lines[at[0] + 1:]:
            if l.strip() and not l.startswith(" "):
                break
            below.append(l)
        under = "\n".join(below)
        self.assertIn("Ran 3 tests", under, "show does not print the summary under the checked line:\n%s" % show)
        self.assertIn("FAILED (failures=2", under, show)
        self.assertIn("FAIL: test_a", under, "show does not print the first failures under the checked line:\n%s" % show)
        self.assertIn("FAIL: test_b", under, show)

    def test_K5_show_prints_a_plain_runners_failures(self):
        self.session()
        cmd = self.script("test_b.py", PLAIN_RUNNER_RED)
        self.take_red(cmd)
        show = run("show", "--target", self.pj.dir)[1]
        i = show.find("checked by chongdae at")
        self.assertGreater(i, -1, show)
        after = show[i:]
        self.assertIn("1 failed", after, show)
        self.assertIn("FAIL b -- AssertionError: b is red before the build", after, show)


# ====================================================================================================================
# K6 — documentation in the README's own voice, the run skill, the help text


class K6Docs(unittest.TestCase):

    @staticmethod
    def paragraph_with(text, needle):
        """The run of non-blank lines holding `needle`."""
        paras = re.split(r"\n\s*\n", text)
        return "\n".join(p for p in paras if needle in p)

    @staticmethod
    def help_option(text, flag):
        """argparse's help for one option: from its line to the next option's."""
        m = re.search(r"^\s*%s\b.*?(?=^\s*--\w|\Z)" % re.escape(flag), text, re.S | re.M)
        return m.group(0) if m else ""

    def test_K6_readme_says_what_checked_red_refuses_and_why(self):
        text = read_text(README)
        para = self.paragraph_with(text, "`--checked-red \"COMMAND\"`")
        self.assertTrue(para, "the README has no paragraph on --checked-red")
        low = para.lower()
        self.assertIn("refus", low, para)
        for sign in ("usage", "signal"):
            self.assertIn(sign, low, "the README's --checked-red paragraph does not say %r is refused:\n%s" % (sign, para))
        self.assertTrue("module" in low or "import" in low, para)
        self.assertTrue("traceback" in low or "syntaxerror" in low or "syntax error" in low or "interpreter" in low, para)
        self.assertTrue("test result" in low or "no result" in low, para)

    def test_K6_readme_says_what_the_record_keeps(self):
        text = read_text(README)
        para = self.paragraph_with(text, "`--checked-red \"COMMAND\"`")
        low = para.lower()
        for word in ("summary", "failures"):
            self.assertIn(word, low, "the README's --checked-red paragraph does not say the record keeps %r:\n%s" % (word, para))
        self.assertTrue("local" in low or "whole output" in low, para)

    def test_K6_readme_files_section_names_the_records_new_keys(self):
        text = read_text(README)
        i = text.find("## Files in your project")
        self.assertGreater(i, -1)
        files = text[i:]
        for key in ("`summary`", "`failures`", "`lines`"):
            self.assertIn(key, files, "the README's Files section does not name %s" % key)
        self.assertIn("none recognized", files)

    def test_K6_run_skill_sentence_on_checked_red_says_what_is_refused(self):
        text = read_text(RUN_SKILL)
        self.assertIn("--checked-red", text, "the run skill does not mention --checked-red")
        # the sentence naming --checked-red and the one after it (a paragraph of the skill is a whole numbered step)
        sentences = re.split(r"(?<=[.;:!?])\s+(?=[A-Z`(])", self.paragraph_with(text, "--checked-red"))
        at = [i for i, x in enumerate(sentences) if "--checked-red" in x]
        self.assertTrue(at, sentences)
        said = " ".join(sentences[at[0]:at[-1] + 2])
        low = said.lower()
        self.assertIn("refus", low, "the skill's sentence on --checked-red does not say a run is refused:\n%s" % said)
        self.assertTrue("test result" in low or "usage" in low or "cannot have reached" in low or "did not reach" in low
                        or "no test" in low or "signal" in low, said)

    def test_K6_take_and_retry_help_text_say_what_checked_red_refuses(self):
        for cmd in ("take", "retry"):
            code, text = run(cmd, "--help")
            opt = self.help_option(text, "--checked-red")
            self.assertTrue(opt, "%s --help has no --checked-red: %s" % (cmd, text))
            low = opt.lower()
            self.assertIn("refus", low, "%s's --checked-red help does not say what is refused:\n%s" % (cmd, opt))
            self.assertTrue("test" in low and ("usage" in low or "reach" in low or "did not run" in low or "test result" in low), opt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
