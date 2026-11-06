"""Contract C3: the close review covers the run's own range from its base.

hunsu's run-20261106-023801-83d9 was based on 708cf1c; a review ran mid-run (708cf1c..8f8578d), and the close review the
runner placed, told nothing, reviewed from the last review's head — an empty range. The lock's `reviewer` argv may name
`{since}`; chongdae replaces it by the run's base (`created.based_on`).

  python -m unittest test_close_review
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_chongdae import Project, run, write   # noqa: E402  (puts plugin/ on sys.path)
import chongdae as c  # noqa: E402

PHRASE = "the lock's `reviewer` names no `{since}`: it was not told this run's range and reviewed the range it chose itself"

# A reviewer outside the project: appends the argv it received as one JSON line to LOG, prints one line, exits 0.
# With a STOPFILE count > 0 it writes a review whose one objection this tree can answer, and counts down.
REVIEWER = r'''import json, os, sys
LOG = %(log)r
STOP = %(stop)r
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
findings = []
if STOP and os.path.exists(STOP):
    n = int(open(STOP).read().strip() or 0)
    if n > 0:
        open(STOP, "w").write(str(n - 1))
        findings = [{"kind": "cq-failed", "where": "records-kept", "text": "a projection was lost", "layer": "objection"}]
if os.path.isdir(".chongdae") or findings:
    os.makedirs("reviews", exist_ok=True)
    json.dump({"artifact-type": "dwitbuk/review@1", "findings": findings}, open(os.path.join("reviews", "review-x.json"), "w"))
print("review-x: %%d finding(s)" %% len(findings))
'''


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="c3-reviewer-")
        self.addCleanup(shutil.rmtree, self.out, True)
        self.log = os.path.join(self.out, "argv.jsonl")
        self.stop = os.path.join(self.out, "stop")
        self.script = os.path.join(self.out, "reviewer.py")
        write(self.script, REVIEWER % {"log": self.log, "stop": self.stop})

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def argv(self, since=True):
        return [sys.executable, self.script, "--since", "{since}"] if since else [sys.executable, self.script, "--mode", "x"]

    def project(self, pj, argv):
        """A git project whose base commit B carries the lock; returns B."""
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"reviewer": argv}})
        write(os.path.join(pj.dir, "a.txt"), "base\n")
        git(pj.dir, "add", "-A")
        git(pj.dir, "commit", "-qm", "base")
        return git(pj.dir, "rev-parse", "HEAD")

    def session_run_with_work(self, pj, name="W1"):
        """init --session; a task whose work is committed; a review run by hand in between; another commit."""
        code, out = run("init", "--session", "--goal", "g-" + name, "--target", pj.dir)
        self.assertEqual(code, 0, out)
        code, out = run("add", name, "--brief", "write w", "--scope", name + ".txt", "--target", pj.dir)
        self.assertEqual(code, 0, out)
        write(os.path.join(pj.dir, name + ".txt"), "work\n")
        git(pj.dir, "add", name + ".txt")
        git(pj.dir, "commit", "-qm", "work " + name)
        mid = git(pj.dir, "rev-parse", "HEAD")
        code, out = run("run", name, "--target", pj.dir)
        self.assertEqual(code, 0, out)
        # the session reviews by hand mid-run (chongdae reads nothing of it)
        subprocess.run([sys.executable, self.script, "--since", mid], cwd=self.out, check=True, capture_output=True)
        write(os.path.join(pj.dir, name + "-more.txt"), "more\n")
        git(pj.dir, "add", name + "-more.txt")
        git(pj.dir, "commit", "-qm", "more " + name)
        return mid


class TestC3Since(Fixture):
    def test_C3_1_session_close_gives_the_reviewer_the_runs_base_not_the_last_reviews_head(self):
        with Project() as pj:
            base = self.project(pj, self.argv())
            mid = self.session_run_with_work(pj)
            self.assertEqual(pj.state()["created"]["based_on"], base)
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(pj.state()["status"], "complete", out)
            got = self.calls()
            self.assertGreaterEqual(len(got), 2, got)
            self.assertEqual(got[-1], ["--since", base], "the close review's {since} is the run's base commit: %r" % got)
            self.assertNotEqual(got[-1][-1], mid)

    def test_C3_1_every_since_in_the_argv_is_replaced(self):
        with Project() as pj:
            base = self.project(pj, [sys.executable, self.script, "--since", "{since}", "--range", "{since}..HEAD"])
            code, out = run("init", "--session", "--goal", "g", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            git(pj.dir, "commit", "-q", "--allow-empty", "-m", "between")
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.calls()[-1:], [["--since", base, "--range", base + "..HEAD"]], self.calls())

    def test_C3_1_a_run_with_no_git_base_gets_an_empty_since(self):
        d = tempfile.mkdtemp(prefix="c3-nogit-")
        self.addCleanup(shutil.rmtree, d, True)
        write(os.path.join(d, "hunsu.lock.json"), {"roles": {"reviewer": self.argv()}})
        code, out = run("init", "--session", "--goal", "g", "--target", d)
        self.assertEqual(code, 0, out)
        st = c.load_state(c.run_dir(d))
        self.assertFalse(st.get("created", {}).get("based_on"), st.get("created"))
        code, out = run("close", "--target", d)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls()[-1:], [["--since", ""]], self.calls())
        st = c.load_state(c.run_dir(d))
        self.assertEqual(st.get("reviewed", {}).get("since"), "", st.get("reviewed"))

    def test_C3_1_a_plan_runs_completion_places_the_reviewer_with_its_base(self):
        with Project() as pj:
            base = self.project(pj, self.argv())
            plan = {"artifact-type": "chongdae/plan@1", "goal": "p",
                    "providers": {"b": [sys.executable, "-c", "import json,sys; json.dump({'status': 'done', 'summary': 's', 'verified': [], 'decisions': [], 'non-claims': []}, open(sys.argv[2], 'w'))", "{request}", "{response}"]},
                    "tasks": [{"id": "T", "role": "b", "checks": [[sys.executable, "-c", "pass"]]}]}
            stdin = sys.stdin
            sys.stdin = io.StringIO(json.dumps(plan))
            try:
                code, out = run("init", "--plan", "-", "--target", pj.dir)
            finally:
                sys.stdin = stdin
            self.assertEqual(code, 0, out)
            code, out = run("run", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            st = pj.state()
            self.assertEqual(st["status"], "complete", out)
            self.assertEqual(st["created"]["based_on"], base)
            self.assertEqual(self.calls()[-1:], [["--since", base]], self.calls())
            self.assertEqual(st.get("reviewed", {}).get("since"), base, st.get("reviewed"))


class TestC3Reviewed(Fixture):
    def test_C3_2_reviewed_records_the_since_it_was_given(self):
        with Project() as pj:
            base = self.project(pj, self.argv())
            self.session_run_with_work(pj)
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            rv = pj.state().get("reviewed", {})
            self.assertEqual(rv.get("since"), base, rv)
            self.assertEqual(rv.get("said"), "review-x: 0 finding(s)", rv)

    def test_C3_2_no_since_key_when_the_argv_names_none(self):
        with Project() as pj:
            self.project(pj, self.argv(since=False))
            self.session_run_with_work(pj)
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            rv = pj.state().get("reviewed", {})
            self.assertEqual(rv.get("said"), "review-x: 0 finding(s)", rv)
            self.assertNotIn("since", rv, rv)
            # and the C3.3 non-claim is recorded — this is what tells the two apart in the current source
            self.assertTrue(any(n.startswith(PHRASE) for n in pj.state()["non-claims"]), pj.state()["non-claims"])


class TestC3Undeclared(Fixture):
    def test_C3_3_argv_without_since_runs_as_declared_and_the_run_says_so(self):
        with Project() as pj:
            base = self.project(pj, self.argv(since=False))
            self.session_run_with_work(pj)
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.calls()[-1], ["--mode", "x"], "run as declared, no flag added: %r" % self.calls())
            st = pj.state()
            said = [n for n in st["non-claims"] if n.startswith(PHRASE)]
            self.assertEqual(len(said), 1, st["non-claims"])
            self.assertIn(PHRASE, out, out)
            run_id = os.path.basename(c.run_dir(pj.dir))
            self.assertNotIn(base, said[0])
            self.assertNotIn(base[:7], said[0])
            self.assertNotIn(run_id, said[0])
            self.assertTrue(any(said[0].startswith(p) for p in c.LOCK_STANDING), (said[0], c.LOCK_STANDING))

    def test_C3_3_the_next_run_keeps_it_in_its_record_and_does_not_print_it_again(self):
        with Project() as pj:
            self.project(pj, self.argv(since=False))
            self.session_run_with_work(pj, "W1")
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            first = [n for n in pj.state()["non-claims"] if n.startswith(PHRASE)]
            self.assertEqual(len(first), 1, pj.state()["non-claims"])
            self.assertIn(PHRASE, out, out)
            self.session_run_with_work(pj, "W2")
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertNotIn("names no `{since}`", out, out)
            second = [n for n in pj.state()["non-claims"] if n.startswith(PHRASE)]
            self.assertEqual(second, first, "worded the same in every run: %r" % pj.state()["non-claims"])
            self.assertEqual(self.calls()[-1], ["--mode", "x"])

    def test_C3_3_an_argv_with_since_says_no_such_non_claim(self):
        with Project() as pj:
            self.project(pj, self.argv())
            code, out = run("init", "--session", "--goal", "g", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertFalse(any("names no `{since}`" in n for n in pj.state()["non-claims"]), pj.state()["non-claims"])
            self.assertEqual(pj.state().get("reviewed", {}).get("since"), pj.state()["created"]["based_on"], pj.state().get("reviewed"))


class TestC3Stopped(Fixture):
    def test_C3_4_a_stopped_close_takes_back_reviewed_and_the_next_close_gives_the_base_again(self):
        with Project() as pj:
            base = self.project(pj, self.argv())
            self.session_run_with_work(pj)
            write(self.stop, "1")
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertIn("objection(s) this tree can answer", out)
            st = pj.state()
            self.assertEqual(st["status"], "running", st)
            self.assertNotIn("reviewed", st)
            stopped_head = git(pj.dir, "rev-parse", "HEAD")
            self.assertEqual(self.calls()[-1], ["--since", base], self.calls())
            git(pj.dir, "commit", "-q", "--allow-empty", "-m", "answered the objection")
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.calls()[-1], ["--since", base], "the run's base again, not the stopped close's head %s: %r" % (stopped_head, self.calls()))
            self.assertEqual(pj.state().get("reviewed", {}).get("since"), base, pj.state().get("reviewed"))


class TestC3Readme(unittest.TestCase):
    def readme(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin", "README.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_C3_5_providers_reviewer_paragraph_names_since_and_the_example(self):
        text = self.readme()
        i = text.find("The reviewer is placed by the runner")
        self.assertGreaterEqual(i, 0, "the reviewer paragraph in Providers")
        para = text[i:text.find("\n\n", i) if text.find("\n\n", i) > 0 else len(text)]
        self.assertIn("{since}", para, para)
        self.assertIn("base", para, para)
        self.assertIn('["python3", "{plugin:dwitbuk}/dwitbuk.py", "review", "--since", "{since}", "--target", "."]', text)

    def test_C3_5_close_section_says_since_becomes_the_base_and_without_it_a_non_claim(self):
        text = self.readme()
        heads = [k for k, line in enumerate(text.splitlines()) if line.startswith("#") and "close" in line]
        self.assertTrue(heads, "a section for the `close` command")
        lines = text.splitlines()
        sections = []
        for k in heads:
            end = next((j for j in range(k + 1, len(lines)) if lines[j].startswith("#") and len(lines[j]) - len(lines[j].lstrip("#")) <= len(lines[k]) - len(lines[k].lstrip("#"))), len(lines))
            sections.append("\n".join(lines[k:end]))
        self.assertTrue(any("{since}" in s and "base" in s and "non-claim" in s for s in sections), "the close section names {since}, the base, and the non-claim without it")


if __name__ == "__main__":
    unittest.main()
