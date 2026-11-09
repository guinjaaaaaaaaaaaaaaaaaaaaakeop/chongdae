"""Contract V: a tests writer's red-before-build evidence is kept and shown.

A day's hired tests tasks each passed their worker's red-before-build validation, and every task record said only
"no check decides this task; done means the agent said so" — no verdict, no count, no file. The worker now answers with
`validation.red_before_build`, a list of per-file entries (file, verdict, detail, report). These tests drive a session
run through the CLI the way a session meets it: the lock hires a fake nitpick for a tests task; the fake writes a test
file into the project and answers with that field. Then the record (merged view and committed task file), `show`,
`retry`, `take`, the task's non-claim and the README are read.

The engine reads the field by its name and names no product. Offline; temporary directories only.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_chongdae
from test_chongdae import Project, run, write
import chongdae as c

ENGINE = os.path.join(test_chongdae.PLUGIN, "chongdae.py")
README = os.path.join(test_chongdae.PLUGIN, "README.md")
NON_CLAIM = "no check decides this task; done means the agent said so"
TEST_FILE = "test_a.py"


def read_text(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def report(**counts):
    full = {"tests_run": 0, "assertion_failures": 0, "fixture_failures": 0, "errors": 0, "skipped": 0,
            "expected_failures": 0, "unexpected_successes": 0}
    full.update(counts)
    return full


# the two entries of the main case: one red with a full report, one unverified with a detail and no report
RED_FULL = {"file": TEST_FILE, "verdict": "red", "detail": "red before the build: 5 of 12 fail by assertion",
            "report": report(tests_run=12, assertion_failures=5)}
UNVERIFIED = {"file": "test_b.py", "verdict": "unverified", "detail": "the module raised before any test ran"}
# the other case: errors and fixture failures beside the assertion failures
RED_WITH_ERRORS = {"file": "test_c.py", "verdict": "red", "detail": "red, with errors",
                   "report": report(tests_run=7, assertion_failures=3, errors=2, fixture_failures=1)}


def validation(*entries, failed=()):
    return {"red_before_build": list(entries), "failed": list(failed)}


def answer(status="done", summary="wrote the tests", validation_=None, decisions=(), non_claims=()):
    resp = {"status": status, "summary": summary, "verified": [], "decisions": list(decisions), "non-claims": list(non_claims)}
    if validation_ is not None:
        resp["validation"] = validation_
    return resp


class Base(unittest.TestCase):
    """A session run in a temporary git project; the lock hires a fake nitpick for a tests task."""

    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.pj = Project()
        self.addCleanup(lambda: shutil.rmtree(self.pj.dir, ignore_errors=True))
        self.git("commit", "-q", "--allow-empty", "-m", "base")

    def git(self, *argv, check=True):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(argv), cwd=self.pj.dir,
                              capture_output=True, text=True, check=check)

    # -- the fake tests writer ------------------------------------------------------------------------------------------

    def writer(self, response, name="writer"):
        """A fake tests writer: writes the test file into the request's target, then the given response."""
        script = os.path.join(self.pj.dir, name + ".py")
        write(script, "import json, os, sys\n"
                      "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
                      "open(os.path.join(req['target'], %r), 'w', encoding='utf-8').write('import unittest\\n\\n"
                      "class T(unittest.TestCase):\\n    def test_x(self):\\n        self.fail(\"red before the build\")\\n')\n"
                      "json.dump(json.loads(%r), open(sys.argv[2], 'w', encoding='utf-8'))\n" % (TEST_FILE, json.dumps(response)))
        return [sys.executable, script, "{request}", "{response}"]

    def hire(self, response, name="writer"):
        write(os.path.join(self.pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": self.writer(response, name)}})

    def session(self, response, tid="u"):
        """init, a tests task hired to the fake nitpick, one `run`; returns (exit code, output) of that run."""
        self.hire(response)
        code, out = run("init", "--session", "--goal", "g", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        code, out = run("add", tid, "--tests", TEST_FILE, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        return run("run", "--target", self.pj.dir)

    def done_session(self, response, tid="u"):
        code, out = self.session(response, tid)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task(tid).get("status"), "done", out)
        return out

    # -- reading the record ----------------------------------------------------------------------------------------------

    def task(self, tid="u"):
        return self.pj.state()["tasks"].get(tid, {})

    def committed_task(self, tid="u"):
        """The task file as committed (HEAD), parsed."""
        d = c.run_dir(self.pj.dir)
        rel = os.path.relpath(os.path.join(d, "tasks", tid + ".json"), self.pj.dir).replace(os.sep, "/")
        shown = self.git("show", "HEAD:" + rel, check=False)
        self.assertEqual(shown.returncode, 0, "the task file is not committed: %s" % shown.stderr)
        return json.loads(shown.stdout)

    def show(self):
        code, out = run("show", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        return out

    def attempt_block(self, out, n):
        """The lines `show` prints under `attempt n:` (the indented lines that follow it)."""
        lines = out.splitlines()
        heads = [i for i, l in enumerate(lines) if re.match(r"^\s+attempt %d:" % n, l)]
        self.assertEqual(len(heads), 1, "attempt %d is not shown once:\n%s" % (n, out))
        head = heads[0]
        indent = len(lines[head]) - len(lines[head].lstrip())
        block = []
        for l in lines[head + 1:]:
            if not l.strip() or len(l) - len(l.lstrip()) <= indent:
                break
            block.append(l)
        return block

    @staticmethod
    def evidence_lines(lines):
        return [l.strip() for l in lines if l.strip().startswith("red before build:")]


# ---------------------------------------------------------------- V1: kept as given

class V1Kept(Base):

    def test_V1_response_validation_kept_as_given_in_merged_state_and_committed_task_file(self):
        given = validation(RED_FULL, UNVERIFIED)
        self.done_session(answer(validation_=given))
        ts = self.task()
        self.assertIn("response", ts)
        self.assertIn("validation", ts["response"], "the response lost its validation object: %r" % ts["response"])
        self.assertEqual(ts["response"]["validation"], given)
        committed = self.committed_task()
        self.assertIn("response", committed)
        self.assertIn("validation", committed["response"], "the committed task file lost the validation object")
        self.assertEqual(committed["response"]["validation"], given)

    def test_V1_entries_of_another_shape_are_kept_never_rewritten_or_dropped(self):
        odd = {"red_before_build": ["not an object", 7, None, {"verdict": "red", "report": report(tests_run=1)},
                                    {"file": "test_d.py", "verdict": "green", "report": "n/a", "extra": {"k": [1, 2]}},
                                    {"file": "test_e.py", "verdict": "red", "report": report(tests_run="twelve", assertion_failures=5)}],
               "failed": ["a validator that refused"], "note": "another key"}
        self.done_session(answer(validation_=odd))
        ts = self.task()
        self.assertIn("response", ts)
        self.assertEqual(ts["response"].get("validation"), odd, "the merged view rewrote or dropped an entry")
        self.assertEqual(self.committed_task().get("response", {}).get("validation"), odd, "the committed file rewrote or dropped an entry")

    def test_V1_first_attempt_keeps_its_validation_after_a_retry(self):
        given = validation(RED_FULL, UNVERIFIED)
        # the first answer settles something the contract did not: the task stops for `accept`, and `retry` is the other answer
        code, out = self.session(answer(validation_=given, decisions=[{"what": "which runner", "chosen": "unittest", "alternatives": ["pytest"]}]))
        self.assertEqual(code, c.DECISION, out)
        code, out = run("retry", "u", "--by", "kim", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.hire(answer(summary="wrote the tests again"), name="writer-2")   # the second answer carries no validation
        code, out = run("run", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        ts = self.task()
        self.assertEqual(ts.get("status"), "done", out)
        self.assertIn("attempts", ts)
        self.assertEqual(len(ts["attempts"]), 1, ts["attempts"])
        self.assertIn("validation", ts["attempts"][0], "the retried attempt lost its validation object: %r" % ts["attempts"][0])
        self.assertEqual(ts["attempts"][0]["validation"], given)
        self.assertNotIn("validation", ts.get("response") or {}, "the second answer carried no validation, the record gave it one")
        committed = self.committed_task()
        self.assertEqual((committed.get("attempts") or [{}])[0].get("validation"), given, "the committed attempt lost its validation object")

    def test_V1_first_attempt_keeps_its_validation_after_a_take(self):
        given = validation(RED_FULL)
        code, out = self.session(answer(status="blocked", summary="no port here", validation_=given))
        self.assertEqual(code, c.DECISION, out)
        code, out = run("take", "u", "--why", "the sandbox had no port", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        ts = self.task()
        self.assertIn("attempts", ts)
        self.assertEqual(len(ts["attempts"]), 1, ts["attempts"])
        self.assertEqual(ts["attempts"][0].get("validation"), given, "the taken attempt lost its validation object: %r" % ts["attempts"][0])

    def test_V1_engine_reads_the_field_by_its_name_and_names_no_product(self):
        source = read_text(ENGINE)
        self.assertIn("red_before_build", source, "the engine does not read the field by its name")
        hits = [i + 1 for i, l in enumerate(source.splitlines()) if "hacheong" in l.lower()]
        self.assertEqual(hits, [], "the engine source names a product (lines %s)" % hits)


# ---------------------------------------------------------------- V2: shown

class V2Shown(Base):

    def test_V2_show_prints_one_line_per_entry_counts_for_a_report_and_detail_without_one(self):
        self.done_session(answer(validation_=validation(RED_FULL, UNVERIFIED)))
        out = self.show()
        self.assertIn("red before build: %s red — 12 run, 5 assertion failures" % TEST_FILE, out, out)
        self.assertIn("red before build: test_b.py unverified — the module raised before any test ran", out, out)

    def test_V2_show_line_omits_errors_and_fixture_failures_when_zero(self):
        self.done_session(answer(validation_=validation(RED_FULL)))
        lines = self.evidence_lines(self.show().splitlines())
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual(lines[0], "red before build: %s red — 12 run, 5 assertion failures" % TEST_FILE)

    def test_V2_show_appends_errors_and_fixture_failures_when_non_zero(self):
        self.done_session(answer(validation_=validation(RED_WITH_ERRORS)))
        lines = self.evidence_lines(self.show().splitlines())
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual(lines[0], "red before build: test_c.py red — 7 run, 3 assertion failures, 2 errors, 1 fixture failures")

    def test_V2_show_prints_detail_when_the_report_is_not_valid(self):
        entries = [{"file": "test_d.py", "verdict": "red", "detail": "the report was not a report", "report": "n/a"},
                   {"file": "test_e.py", "verdict": "green", "detail": "every test passed before the build",
                    "report": {"tests_run": "twelve", "assertion_failures": 0}},
                   {"file": "test_f.py", "verdict": "red", "detail": "no counts came back", "report": {}}]
        self.done_session(answer(validation_=validation(*entries)))
        out = self.show()
        self.assertIn("red before build: test_d.py red — the report was not a report", out, out)
        self.assertIn("red before build: test_e.py green — every test passed before the build", out, out)
        self.assertIn("red before build: test_f.py red — no counts came back", out, out)

    def test_V2_show_prints_the_line_under_the_attempt_that_carries_it(self):
        self.done_session(answer(validation_=validation(RED_FULL, UNVERIFIED)))
        out = self.show()
        block = self.attempt_block(out, 1)
        self.assertEqual(self.evidence_lines(block),
                         ["red before build: %s red — 12 run, 5 assertion failures" % TEST_FILE,
                          "red before build: test_b.py unverified — the module raised before any test ran"], out)

    def test_V2_show_keeps_the_line_under_attempt_1_after_a_retry(self):
        given = validation(RED_FULL)
        code, out = self.session(answer(validation_=given, decisions=[{"what": "which runner", "chosen": "unittest", "alternatives": ["pytest"]}]))
        self.assertEqual(code, c.DECISION, out)
        code, out = run("retry", "u", "--by", "kim", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        self.hire(answer(summary="wrote the tests again"), name="writer-2")
        code, out = run("run", "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        out = self.show()
        self.assertEqual(self.evidence_lines(self.attempt_block(out, 1)),
                         ["red before build: %s red — 12 run, 5 assertion failures" % TEST_FILE], out)
        self.assertEqual(self.evidence_lines(self.attempt_block(out, 2)), [], "attempt 2 said nothing of the kind:\n" + out)

    def test_V2_show_skips_an_entry_that_is_not_an_object_or_names_no_file(self):
        entries = ["not an object", 7, None, ["a", "list"],
                   {"verdict": "red", "detail": "no file named", "report": report(tests_run=3, assertion_failures=3)},
                   {"file": None, "verdict": "red", "detail": "file is null"},
                   RED_FULL]
        self.done_session(answer(validation_=validation(*entries)))
        out = self.show()
        lines = self.evidence_lines(out.splitlines())
        self.assertEqual(lines, ["red before build: %s red — 12 run, 5 assertion failures" % TEST_FILE], out)
        self.assertNotIn("no file named", out)
        self.assertNotIn("file is null", out)
        self.assertNotIn("Traceback", out)

    def test_V2_show_prints_nothing_of_the_kind_when_the_worker_sent_no_validation(self):
        self.done_session(answer())
        out = self.show()
        self.assertNotIn("red before build", out, out)


# ---------------------------------------------------------------- V3: not a deciding check

class V3NotACheck(Base):

    def test_V3_tests_task_keeps_its_non_claim_and_nothing_enters_checks(self):
        self.done_session(answer(validation_=validation(RED_FULL, UNVERIFIED)))
        ts = self.task()
        self.assertIn(NON_CLAIM, ts.get("non-claims") or [], ts.get("non-claims"))
        self.assertEqual((ts.get("def") or {}).get("checks"), [], ts.get("def"))
        for key in ("checks", "checks-passed", "checked"):
            self.assertFalse(ts.get(key), "%s holds something on a task no check decides: %r" % (key, ts.get(key)))
        committed = self.committed_task()
        self.assertIn(NON_CLAIM, committed.get("non-claims") or [])
        for key in ("checks", "checks-passed", "checked"):
            self.assertFalse(committed.get(key), "%s holds something in the committed task file: %r" % (key, committed.get(key)))
        out = self.show()
        self.assertIn("checks: none — done is the agent's word", out, out)
        self.assertIn("non-claim: " + NON_CLAIM, out, out)
        self.assertNotIn("checked by chongdae", out, out)

    def test_V3_red_entry_does_not_complete_a_stopped_task(self):
        code, out = self.session(answer(status="blocked", summary="no port here", validation_=validation(RED_FULL)))
        self.assertEqual(code, c.DECISION, out)
        self.assertEqual(self.task().get("status"), "todo", "a red entry completed a blocked task")

    def test_V3_green_entry_does_not_stop_a_done_task(self):
        green = {"file": TEST_FILE, "verdict": "green", "detail": "every test passed before the build", "report": report(tests_run=4)}
        code, out = self.session(answer(validation_=validation(green)))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task().get("status"), "done", "a green entry stopped the task: %s" % out)
        self.assertIn(NON_CLAIM, self.task().get("non-claims") or [])


# ---------------------------------------------------------------- V4: documented

class V4Documented(unittest.TestCase):

    def files_section(self):
        text = read_text(README)
        m = re.search(r"^## Files in your project\s*$", text, re.M)
        self.assertIsNotNone(m, "the README has no `## Files in your project` section")
        rest = text[m.end():]
        nxt = re.search(r"^## ", rest, re.M)
        return rest[:nxt.start()] if nxt else rest

    def test_V4_readme_files_section_says_red_before_build_is_kept_and_shown_as_evidence_not_a_check(self):
        section = self.files_section()
        self.assertIn("red_before_build", section, "the Files section does not name `validation.red_before_build`")
        # the sentences around the mention say: kept as given, printed by `show`, the worker's evidence, not a check
        paras = [p for p in re.split(r"\n\s*\n", section) if "red_before_build" in p]
        around = "\n".join(paras).lower()
        self.assertIn("show", around, "the README does not say `show` prints it")
        self.assertTrue("as given" in around or "kept as" in around or "as the response gave" in around,
                        "the README does not say the field is kept as given:\n%s" % around)
        self.assertIn("evidence", around, "the README does not call it the worker's evidence")
        self.assertTrue("not a check" in around or "no check" in around or "not a deciding" in around or "does not decide" in around,
                        "the README does not say it is not a check:\n%s" % around)


if __name__ == "__main__":
    unittest.main()
