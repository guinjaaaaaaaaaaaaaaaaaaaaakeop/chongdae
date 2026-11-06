"""Contract C4: an inspection task — it reads, owns nothing, and is decided by the record it consumed.

Log 48 finding 5: guin-site's `ui-review` asked for a read-only review, was a session task with a source `--scope`, and
was given write attribution. These tests reproduce that through the CLI, then decide `add --inspect … --evidence …`.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_chongdae
from test_chongdae import Project, run, write, UNCOMMITTED
import chongdae as c

REPO = os.path.dirname(os.path.abspath(__file__))
PASS = sys.executable + " -c pass"
BRIEF = "a read-only review of the UI under src: read it, write nothing, report findings"
HELD = "is an inspection: nothing under"
HELD_TAIL = "changed since it was added — consume the review or eyes answer it is for (the command that records it), then `chongdae run %s`"


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def git(cwd, *a):
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t", "-c", "user.email=t@t"] + list(a),
                          cwd=cwd, capture_output=True, text=True, check=True).stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)

    # ------------------------------------------------------------------ helpers
    def session(self, pj):
        code, out = run("init", "--session", "--goal", "inspection", "--target", pj.dir)
        self.assertEqual(code, 0, out)
        return c.run_dir(pj.dir)

    def add(self, pj, tid, *extra):
        code, out = run("add", tid, *extra, "--target", pj.dir)
        self.assertEqual(code, 0, out)
        return out

    def inspect(self, pj, tid="ui-review", reads=("src",), evidence=("reviews/",), *extra):
        return self.add(pj, tid, "--inspect", *reads, "--evidence", *evidence, "--brief", BRIEF, *extra)

    def task(self, pj, tid):
        return pj.state()["tasks"][tid]

    def public(self, pj, tid):
        with open(os.path.join(c.run_dir(pj.dir), "tasks", tid + ".json"), encoding="utf-8") as fh:
            return json.load(fh)

    def overlay(self, pj, tid):
        path = os.path.join(c.run_dir(pj.dir), "local", "tasks", tid + ".json")
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def snapshot(self, pj):
        """Every file under the run directory, as bytes: 'the record unchanged'."""
        out = {}
        for root, _, files in os.walk(os.path.join(pj.dir, ".chongdae")):
            for name in files:
                p = os.path.join(root, name)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, pj.dir)] = fh.read()
        return out

    def head(self, pj):
        return subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()

    def review(self, pj, name="reviews/review-1.json", body=None):
        path = os.path.join(pj.dir, name)
        write(path, body if body is not None else {"artifact-type": "dwitbuk/findings@1", "findings": []})
        return path

    def assert_refused(self, pj, argv, *reason):
        """An add the contract refuses: not argparse's 'unknown option', nothing written, the reason given; then the
        same id as a proper inspection is accepted (the refusal was C4.1's, not the option's absence)."""
        before, head = self.snapshot(pj), self.head(pj)
        code, out = run("add", "ui-review", *argv, "--target", pj.dir)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("unrecognized arguments", out, "`add --inspect` is not an option yet: " + out)
        for word in reason:
            self.assertIn(word, out)
        self.assertEqual(self.snapshot(pj), before, "a refused add wrote to the record")
        self.assertEqual(self.head(pj), head, "a refused add committed")
        self.assertNotIn("ui-review", pj.state().get("tasks", {}))
        self.inspect(pj)
        self.assertEqual(self.task(pj, "ui-review")["def"].get("kind"), "inspection")


# ====================================================================== log 48 finding 5, as it happened
class Reproducer(Base):
    def test_C4_2_log48_finding5_the_review_as_an_inspection_is_not_given_the_fix_tasks_write(self):
        """Today's commands: the review is a session task with `--scope src`, and it is counted src/a.ts written for
        `fix` — the defect, which stays true of a scoped session task. The same review as an inspection owns nothing,
        and src/a.ts is fix's."""
        with Project() as pj:
            self.session(pj)
            self.add(pj, "ui-review", "--scope", "src", "--brief", BRIEF)
            self.add(pj, "fix", "--brief", "fix the button")
            write(os.path.join(pj.dir, "src", "a.ts"), "export const a = 1\n")
            run("run", "ui-review", "--target", pj.dir)
            run("run", "fix", "--target", pj.dir)
            today = (self.task(pj, "ui-review").get("touched"), self.task(pj, "fix").get("touched"))
            self.assertEqual(today, (["src/a.ts"], []), "log 48 finding 5 as it happened: the scoped review took fix's file")
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.add(pj, "fix", "--brief", "fix the button")
            write(os.path.join(pj.dir, "src", "a.ts"), "export const a = 1\n")
            self.review(pj)
            run("run", "ui-review", "--target", pj.dir)
            run("run", "fix", "--target", pj.dir)
            self.assertEqual(self.task(pj, "ui-review").get("status"), "done")
            self.assertEqual((self.task(pj, "ui-review").get("touched"), self.task(pj, "fix").get("touched")),
                             ([], ["src/a.ts"]))

    def test_C4_3_log48_finding5_after_C4_the_inspection_is_held_then_decided_by_its_review(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.add(pj, "fix", "--brief", "fix the button")
            write(os.path.join(pj.dir, "src", "a.ts"), "export const a = 1\n")
            code, out = run("run", "fix", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj, "fix")["status"], "done", out)
            self.assertEqual(self.task(pj, "fix")["touched"], ["src/a.ts"])
            # nothing under reviews/: held for the session, with the sentence
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertIn("ui-review " + HELD, out)
            self.assertIn(HELD_TAIL % "ui-review", out)
            self.assertEqual(self.task(pj, "ui-review")["status"], "todo")
            # the review lands: the inspection is done on it
            path = self.review(pj)
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            pub = self.public(pj, "ui-review")
            self.assertEqual(pub["status"], "done", out)
            self.assertEqual(pub["touched"], [])
            self.assertEqual(pub["evidence-read"], [{"path": "reviews/review-1.json", "sha256": sha(path)}])
            self.assertEqual(self.task(pj, "fix")["touched"], ["src/a.ts"])


# ====================================================================== C4.1 add --inspect
class C4_1_Add(Base):
    def test_C4_1_definition_records_kind_reads_and_evidence(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj, "ui-review", ("./src/", "."), ("reviews/",))
            d = self.task(pj, "ui-review")["def"]
            self.assertEqual(d.get("kind"), "inspection")
            self.assertEqual(sorted(d.get("reads") or []), [".", "src"])
            self.assertTrue(d.get("evidence"), d)
            self.assertEqual([e.rstrip("/") for e in d["evidence"]], ["reviews"])
            self.assertFalse(d.get("checks"), d)
            self.assertFalse(d.get("scope"), "an inspection owns no files: its --inspect paths are what it reads")
            self.assertEqual(self.public(pj, "ui-review")["def"].get("kind"), "inspection")

    def test_C4_1_reads_are_cleaned_like_scope(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "scoped", "--scope", "./src/", "--brief", "b")
            self.inspect(pj, "ui-review", ("./src/",), ("./reviews/",))
            self.assertEqual(self.task(pj, "ui-review")["def"].get("reads"), self.task(pj, "scoped")["def"]["scope"])

    def test_C4_1_role_subagent_is_accepted(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj, "ui-review", ("src",), ("reviews/",), "--role", "subagent")
            d = self.task(pj, "ui-review")["def"]
            self.assertEqual(d.get("kind"), "inspection")
            self.assertEqual(d.get("role"), "subagent")

    def test_C4_1_evidence_under_other_default_record_paths_is_accepted(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj, "eyes", (".",), (".dwitbuk/",))
            self.assertEqual(self.task(pj, "eyes")["def"].get("kind"), "inspection")

    def test_C4_1_check_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--check", PASS], "--check")

    def test_C4_1_tests_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--tests", "test_x.py"], "--tests")

    def test_C4_1_scope_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--scope", "src"], "--scope")

    def test_C4_1_before_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--before", "quibble"], "--before")

    def test_C4_1_after_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--after", "newbie"], "--after")

    def test_C4_1_requires_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--requires", "network"], "--requires")

    def test_C4_1_allow_outside_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--allow-outside"], "--allow-outside")

    def test_C4_1_repeat_checks_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--repeat-checks"], "--repeat-checks")

    def test_C4_1_role_implementer_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--role", "implementer"], "implementer")

    def test_C4_1_role_verifier_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "--role", "verifier"], "verifier")

    def test_C4_1_source_evidence_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "src/"], "src")

    def test_C4_1_one_source_path_among_record_paths_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "reviews/", "notes.md"], "notes.md")

    def test_C4_1_chongdae_own_record_is_not_evidence(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", ".chongdae/"], ".chongdae")

    def test_C4_1_the_whole_project_is_not_evidence(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--evidence", "."])

    def test_C4_1_missing_evidence_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["--inspect", "src", "--brief", BRIEF], "--evidence")

    def test_C4_1_evidence_follows_the_locks_record_paths(self):
        """A lock that declares its own record paths: evidence under them is accepted; `reviews/`, no longer declared, is not."""
        with Project() as pj:
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {}, "record-paths": {"notes": ["notes/"]}})
            self.session(pj)
            before = self.snapshot(pj)
            code, out = run("add", "r1", "--inspect", "src", "--evidence", "reviews/", "--brief", BRIEF, "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertNotIn("unrecognized arguments", out)
            self.assertEqual(self.snapshot(pj), before)
            self.add(pj, "r2", "--inspect", "src", "--evidence", "notes/", "--brief", BRIEF)
            self.assertEqual(self.task(pj, "r2")["def"].get("kind"), "inspection")

    def test_C4_1_never_the_no_check_decides_non_claim(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.review(pj)
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            st = pj.state()
            self.assertEqual(st["tasks"]["ui-review"]["status"], "done", out)
            self.assertFalse([n for n in st["tasks"]["ui-review"].get("non-claims", []) if "no check decides" in n])
            self.assertFalse([n for n in c.non_claims(st) if "no check decides" in n], c.non_claims(st))
            self.assertNotIn("no check decides", run("show", "--target", pj.dir)[1])


# ====================================================================== C4.2 owns nothing
class C4_2_OwnsNothing(Base):
    def test_C4_2_no_start_snapshot_and_touched_always_empty(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.assertNotIn("start", self.overlay(pj, "ui-review"), "an inspection takes no start snapshot")
            self.assertEqual(self.task(pj, "ui-review").get("touched", []), [])
            write(os.path.join(pj.dir, "src", "a.ts"), "x\n")
            self.review(pj)
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj, "ui-review")["status"], "done", out)
            self.assertEqual(self.public(pj, "ui-review")["touched"], [])
            self.assertNotIn("git add", out, "nothing is the inspection's to commit")

    def test_C4_2_a_file_changed_while_only_the_inspection_is_open_is_nobodys(self):
        with Project() as pj:
            write(os.path.join(pj.dir, "README"), "x\n")
            git(pj.dir, "add", "-A")
            git(pj.dir, "commit", "-qm", "base")
            base = self.head(pj)
            self.session(pj)
            self.inspect(pj)
            write(os.path.join(pj.dir, "src", "b.ts"), "while only the inspection was open\n")
            self.add(pj, "fix", "--brief", "fix the button")
            write(os.path.join(pj.dir, "src", "a.ts"), "fix\n")
            self.review(pj)
            code, out = run("run", "--target", pj.dir)
            st = pj.state()
            self.assertEqual(st["tasks"]["ui-review"]["status"], "done", out)
            self.assertEqual(st["tasks"]["ui-review"]["touched"], [])
            self.assertEqual(st["tasks"]["fix"]["touched"], ["src/a.ts"])
            for tid, ts in st["tasks"].items():
                self.assertNotIn("src/b.ts", ts.get("touched", []), tid)
            run("close", *UNCOMMITTED, "--target", pj.dir)
            doc = json.loads(run("report", "--since", base, "--target", pj.dir)[1])
            nobody = [f["where"] for f in doc["findings"] if f["kind"] == "outside-run"]
            self.assertIn("src/b.ts", nobody, doc["findings"])
            self.assertNotIn("src/a.ts", nobody)

    def test_C4_2_the_window_rule_ignores_an_open_inspection(self):
        """Unscoped tasks with and without an inspection open beside them measure the same."""
        def scenario(with_inspection):
            with Project() as pj:
                self.session(pj)
                if with_inspection:
                    self.inspect(pj)
                self.add(pj, "first", "--brief", "one")
                write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
                self.add(pj, "second", "--brief", "two")
                write(os.path.join(pj.dir, "src", "b.ts"), "b\n")
                if with_inspection:
                    self.review(pj)
                run("run", "second", "--target", pj.dir)
                run("run", "first", "--target", pj.dir)
                if with_inspection:
                    run("run", "ui-review", "--target", pj.dir)
                    self.assertEqual(self.task(pj, "ui-review")["status"], "done")
                    self.assertEqual(self.task(pj, "ui-review")["touched"], [])
                return {t: self.task(pj, t).get("touched") for t in ("first", "second")}
        self.assertEqual(scenario(True), scenario(False))

    def test_C4_2_scoped_measure_ignores_an_open_inspection(self):
        """A scoped task beside an unscoped one: an inspection reading src is not an open scoped task."""
        def scenario(with_inspection):
            with Project() as pj:
                self.session(pj)
                if with_inspection:
                    self.inspect(pj, "ui-review", ("src",), ("reviews/",))
                self.add(pj, "lib", "--scope", "lib", "--brief", "lib work")
                self.add(pj, "fix", "--brief", "fix")
                write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
                write(os.path.join(pj.dir, "lib", "x.py"), "x\n")
                outs = []
                if with_inspection:
                    self.review(pj)
                    outs.append(run("run", "ui-review", "--target", pj.dir)[1])
                    self.assertEqual(self.task(pj, "ui-review")["touched"], [], outs)
                outs.append(run("run", "lib", "--target", pj.dir)[1])
                outs.append(run("run", "fix", "--target", pj.dir)[1])
                self.assertNotIn("adopt ui-review", "\n".join(outs))
                return {t: self.task(pj, t).get("touched") for t in ("lib", "fix")}
        self.assertEqual(scenario(True), scenario(False))

    def test_C4_2_its_finish_pins_nothing_into_an_open_task(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.add(pj, "fix", "--brief", "fix")
            start = self.overlay(pj, "fix").get("start")
            write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
            self.review(pj)
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj, "ui-review")["status"], "done", out)
            self.assertEqual(self.overlay(pj, "fix").get("start"), start, "the inspection's finish pinned into fix's start")
            run("run", "fix", "--target", pj.dir)
            self.assertEqual(self.task(pj, "fix")["touched"], ["src/a.ts"])

    def test_C4_2_another_tasks_finish_pins_nothing_into_it(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.add(pj, "fix", "--brief", "fix")
            write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
            run("run", "fix", "--target", pj.dir)
            self.assertEqual(self.task(pj, "fix")["touched"], ["src/a.ts"])
            ov = self.overlay(pj, "ui-review")
            self.assertTrue(ov, "an inspection is added in a session: its overlay names it (added-in)")
            self.assertNotIn("start", ov)
            self.assertEqual(self.task(pj, "ui-review").get("touched", []), [])
            self.assertEqual(self.task(pj, "ui-review")["status"], "todo")

    def test_C4_2_its_brief_contests_no_file(self):
        with Project() as pj:
            self.session(pj)
            self.add(pj, "ui-review", "--inspect", "src", "--evidence", "reviews/", "--brief",
                     "review src/a.ts and src/b.ts read-only")
            self.add(pj, "fix", "--brief", "fix")
            write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
            code, out = run("run", "fix", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertNotIn("adopt ui-review", out)
            self.assertNotIn("ui-review", "\n".join(l for l in out.splitlines() if "note:" in l))
            self.assertEqual(self.task(pj, "fix")["touched"], ["src/a.ts"])

    def test_C4_2_adopt_into_an_inspection_is_refused(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
            before, head = self.snapshot(pj), self.head(pj)
            code, out = run("adopt", "ui-review", "src/a.ts", "--why", "it reviewed it", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertIn("an inspection owns no files", out)
            self.assertEqual(self.snapshot(pj), before)
            self.assertEqual(self.head(pj), head)

    def test_C4_2_adopt_into_another_task_neither_gives_to_nor_takes_from_it(self):
        with Project() as pj:
            self.session(pj)
            write(os.path.join(pj.dir, "src", "a.ts"), "written before fix was added\n")
            self.inspect(pj)
            self.add(pj, "fix", "--brief", "fix")
            code, out = run("adopt", "fix", "src/a.ts", "--why", "fix's work, written before it was added", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ui = self.task(pj, "ui-review")
            self.assertEqual(ui["def"].get("kind"), "inspection")
            self.assertNotIn("gave", ui)
            self.assertNotIn("adopted", ui)
            self.assertNotIn("start", self.overlay(pj, "ui-review"))
            for entry in self.task(pj, "fix").get("adopted", []):
                self.assertNotIn("ui-review", entry.get("from", []), entry)
                self.assertNotIn("ui-review", entry.get("beside", {}), entry)
            self.review(pj)
            run("run", "--target", pj.dir)
            self.assertEqual(self.task(pj, "ui-review")["touched"], [])
            self.assertIn("src/a.ts", self.task(pj, "fix")["touched"])


# ====================================================================== C4.3 decided by its evidence
class C4_3_Evidence(Base):
    def test_C4_3_add_records_evidence_digests_in_the_local_overlay_only(self):
        with Project() as pj:
            self.session(pj)
            old = self.review(pj, "reviews/old.json", {"old": 1})
            digest = sha(old)
            self.inspect(pj)
            ov = self.overlay(pj, "ui-review")
            keys = [k for k, v in ov.items() if digest in json.dumps(v)]
            self.assertTrue(keys, "the evidence digest at add is not in the overlay: %r" % ov)
            for k in keys:
                self.assertIn(k, c.PRIVATE_KEYS)
            self.assertNotIn(digest, json.dumps(self.public(pj, "ui-review")), "the add-time digests are this machine's")

    def test_C4_3_named_run_with_nothing_new_stops_with_the_sentence(self):
        with Project() as pj:
            self.session(pj)
            self.review(pj, "reviews/old.json", {"old": 1})
            self.inspect(pj)
            for _ in range(2):   # the second call is held the same way
                code, out = run("run", "ui-review", "--target", pj.dir)
                self.assertEqual(code, c.DECISION, out)
                self.assertIn("ui-review " + HELD, out)
                self.assertIn("reviews", out[out.index(HELD):])
                self.assertIn(HELD_TAIL % "ui-review", out)
                self.assertEqual(self.task(pj, "ui-review")["status"], "todo")
                self.assertNotIn("evidence-read", self.task(pj, "ui-review"))

    def test_C4_3_bare_run_holds_it_and_goes_on_with_the_others(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.add(pj, "fix", "--brief", "fix")
            self.add(pj, "later", "--check", PASS)
            write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
            code, out = run("run", "--target", pj.dir)
            self.assertIn("ui-review " + HELD, out)
            self.assertIn(HELD_TAIL % "ui-review", out)
            st = pj.state()
            self.assertEqual(st["tasks"]["ui-review"]["status"], "todo")
            self.assertEqual(st["tasks"]["fix"]["status"], "done", out)
            self.assertEqual(st["tasks"]["later"]["status"], "done", out)

    def test_C4_3_bare_run_decides_it_once_a_review_lands(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            a = self.review(pj, "reviews/b.json", {"b": 1})
            b = self.review(pj, "reviews/a/x.json", {"a": 1})
            code, out = run("run", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            pub = self.public(pj, "ui-review")
            self.assertEqual(pub["status"], "done", out)
            self.assertEqual(pub["evidence-read"], [{"path": "reviews/a/x.json", "sha256": sha(b)},
                                                    {"path": "reviews/b.json", "sha256": sha(a)}])

    def test_C4_3_a_changed_file_is_evidence_an_unchanged_one_is_not(self):
        with Project() as pj:
            self.session(pj)
            old = self.review(pj, "reviews/old.json", {"round": 1})
            self.inspect(pj)
            self.assertEqual(run("run", "ui-review", "--target", pj.dir)[0], c.DECISION)
            self.review(pj, "reviews/old.json", {"round": 2})
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.public(pj, "ui-review")["evidence-read"], [{"path": "reviews/old.json", "sha256": sha(old)}])

    def test_C4_3_ignored_evidence_files_are_walked_too(self):
        with Project() as pj:
            write(os.path.join(pj.dir, ".gitignore"), "reviews/\n")
            self.session(pj)
            self.inspect(pj)
            path = self.review(pj)
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.public(pj, "ui-review")["evidence-read"], [{"path": "reviews/review-1.json", "sha256": sha(path)}])

    def test_C4_3_a_source_change_is_not_evidence(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertIn(HELD_TAIL % "ui-review", out)
            self.assertEqual(self.task(pj, "ui-review")["status"], "todo")

    def test_C4_3_evidence_read_is_committed_with_the_record(self):
        with Project() as pj:
            d = self.session(pj)
            self.inspect(pj)
            path = self.review(pj)
            self.assertEqual(run("run", "ui-review", "--target", pj.dir)[0], 0)
            rel = os.path.relpath(os.path.join(d, "tasks", "ui-review.json"), pj.dir).replace(os.sep, "/")
            committed = json.loads(git(pj.dir, "show", "HEAD:" + rel))
            self.assertEqual(committed.get("evidence-read"), [{"path": "reviews/review-1.json", "sha256": sha(path)}])
            self.assertNotIn("reviews/review-1.json", git(pj.dir, "show", "--name-only", "--format=", "HEAD").split(),
                             "the review itself is not committed as the inspection's work")

    def test_C4_3_no_verifier_is_placed_for_it(self):
        with Project() as pj:
            marker = os.path.join(pj.dir, "verifier-was-called")
            script = os.path.join(pj.dir, "eyes.py")
            write(script, "import sys\nopen(%r, 'w').write('called')\nsys.exit(1)\n" % marker)
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"verifier": [sys.executable, script, "{request}", "{response}"],
                                                                       "newbie": [sys.executable, script, "{request}", "{response}"]}})
            git(pj.dir, "add", "-A")
            git(pj.dir, "commit", "-qm", "base")
            self.session(pj)
            self.inspect(pj)
            self.review(pj)
            code, out = run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj, "ui-review")
            self.assertEqual(ts["status"], "done", out)
            self.assertFalse(os.path.exists(marker), "a verifier was placed for an inspection")
            self.assertNotIn("verified_by", ts)
            self.assertNotIn("review", ts)
            self.assertFalse(ts.get("stages"), ts.get("stages"))


# ====================================================================== C4.4 show and report
class C4_4_Tell(Base):
    def test_C4_4_show_tells_the_inspection_line(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            path = self.review(pj)
            self.assertEqual(run("run", "ui-review", "--target", pj.dir)[0], 0)
            code, out = run("show", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            line = [l for l in out.splitlines() if "inspection (read-only)" in l]
            self.assertTrue(line, out)
            line = line[0]
            self.assertIn("inspection (read-only): reads src; evidence ", line)
            self.assertIn("(sha256 %s…)" % sha(path)[:12], line)
            self.assertTrue(line.rstrip().endswith("; owns nothing"), line)

    def test_C4_4_show_path_never_names_the_inspection(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.add(pj, "fix", "--brief", "fix")
            write(os.path.join(pj.dir, "src", "a.ts"), "a\n")
            self.review(pj)
            run("run", "--target", pj.dir)
            self.assertEqual(self.task(pj, "ui-review")["status"], "done")
            for argv in (("show", "--path", "src/a.ts"), ("show", "--path", "src"), ("show", "--path", "src/a.ts", "--brief")):
                code, out = run(*argv, "--target", pj.dir)
                self.assertEqual(code, 0, out)
                self.assertIn("fix", out, argv)
                self.assertNotIn("ui-review", out, argv)

    def test_C4_4_report_lists_no_non_claim_for_a_done_inspection(self):
        with Project() as pj:
            write(os.path.join(pj.dir, "README"), "x\n")
            git(pj.dir, "add", "-A")
            git(pj.dir, "commit", "-qm", "base")
            base = self.head(pj)
            self.session(pj)
            self.inspect(pj)
            self.review(pj)
            self.assertEqual(run("run", "ui-review", "--target", pj.dir)[0], 0)
            self.assertEqual(self.task(pj, "ui-review")["status"], "done")
            run("close", *UNCOMMITTED, "--target", pj.dir)
            code, out = run("report", "--since", base, "--target", pj.dir)
            doc = json.loads(out)
            mine = [f for f in doc["findings"] if f["kind"] == "non-claim"
                    and (f.get("where", "").endswith("/ui-review") or "ui-review" in f.get("text", ""))]
            self.assertEqual(mine, [])

    def test_C4_4_an_open_inspection_is_an_open_task_in_report(self):
        with Project() as pj:
            write(os.path.join(pj.dir, "README"), "x\n")
            git(pj.dir, "add", "-A")
            git(pj.dir, "commit", "-qm", "base")
            base = self.head(pj)
            self.session(pj)
            self.inspect(pj)
            run("close", *UNCOMMITTED, "--target", pj.dir)
            doc = json.loads(run("report", "--since", base, "--target", pj.dir)[1])
            left = [f for f in doc["findings"] if f["kind"] == "left-open"]
            self.assertTrue(any(f["where"].endswith("/ui-review") for f in left), doc["findings"])
            self.assertEqual(self.task(pj, "ui-review")["def"].get("kind"), "inspection")


# ====================================================================== C4.5 ownership and life
class C4_5_Life(Base):
    def test_C4_5_added_in_this_session(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.assertEqual(self.task(pj, "ui-review")["def"].get("kind"), "inspection")
            self.assertIn("added-in", self.overlay(pj, "ui-review"))

    def test_C4_5_another_session_cannot_drop_or_amend_it(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            before, head = self.snapshot(pj), self.head(pj)
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            for argv in (("drop", "ui-review", "--why", "mine now"),
                         ("amend", "ui-review", "--brief", "other", "--why", "mine now"),
                         ("adopt", "ui-review", "src/a.ts", "--why", "x")):
                code, out = run(*argv, "--target", pj.dir)
                self.assertNotEqual(code, 0, (argv, out))
                self.assertEqual(self.snapshot(pj), before, argv)
                self.assertEqual(self.head(pj), head, argv)
            code, out = run("drop", "ui-review", "--why", "mine now", "--target", pj.dir)
            self.assertIn("another session", out)
            self.assertEqual(self.task(pj, "ui-review")["status"], "todo")

    def test_C4_5_another_sessions_named_run_does_not_decide_it(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            self.review(pj)
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            run("run", "ui-review", "--target", pj.dir)
            self.assertEqual(self.task(pj, "ui-review")["status"], "todo")
            os.environ["CHONGDAE_SESSION"] = "owner-a"
            self.assertEqual(run("run", "ui-review", "--target", pj.dir)[0], 0)
            self.assertEqual(self.task(pj, "ui-review")["status"], "done")

    def test_C4_5_drop_works_on_it(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            code, out = run("drop", "ui-review", "--why", "the review was not needed", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj, "ui-review")
            self.assertEqual(ts["status"], "dropped")
            self.assertEqual(ts["def"].get("kind"), "inspection")
            self.assertEqual(ts.get("touched", []), [])

    def test_C4_5_amend_its_brief_but_not_checks(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            code, out = run("amend", "ui-review", "--brief", "review src/ui only", "--why", "narrower", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj, "ui-review")
            self.assertEqual(ts["def"]["brief"], "review src/ui only")
            self.assertEqual(ts["def"].get("kind"), "inspection")
            before = self.snapshot(pj)
            code, out = run("amend", "ui-review", "--check", PASS, "--why", "a check", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertEqual(self.snapshot(pj), before)
            self.assertFalse(self.task(pj, "ui-review")["def"].get("checks"))

    def test_C4_5_close_leaves_an_open_inspection_open(self):
        with Project() as pj:
            self.session(pj)
            self.inspect(pj)
            code, out = run("close", *UNCOMMITTED, "--target", pj.dir)
            self.assertEqual(code, 0, out)
            st = pj.state()
            self.assertEqual(st["status"], "complete")
            self.assertEqual(st["tasks"]["ui-review"]["status"], "todo")
            self.assertEqual(st["tasks"]["ui-review"]["def"].get("kind"), "inspection")
            self.assertNotIn("evidence-read", st["tasks"]["ui-review"])


# ====================================================================== C4.6 documentation
def section(text, heading):
    start = text.index(heading)
    nxt = text.find("\n### ", start + len(heading))
    return text[start:nxt if nxt >= 0 else len(text)]


class C4_6_Docs(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_C4_6_readme_add_section_tells_inspect(self):
        add = section(self.read("plugin", "README.md"), "### `/chongdae:add`")
        self.assertIn("--inspect", add)
        self.assertIn("--evidence", add)
        self.assertIn("refuse", add.lower())

    def test_C4_6_readme_task_record_names_the_fields(self):
        rec = section(self.read("plugin", "README.md"), "### `.chongdae/run-<id>/tasks/<id>.json`")
        for field in ("`kind`", "`reads`", "`evidence`", "`evidence-read`"):
            self.assertIn(field, rec, field)

    def test_C4_6_run_skill_says_a_review_is_an_inspection(self):
        skill = self.read("plugin", "skills", "run", "SKILL.md")
        self.assertIn("--inspect", skill)
        self.assertIn("--evidence", skill)
        line = [l for l in skill.split("\n\n") if "--inspect" in l]
        self.assertTrue(line)
        self.assertIn("did", line[0])


if __name__ == "__main__":
    unittest.main()
