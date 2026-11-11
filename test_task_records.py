"""Contract D: a task's records are its own, listed, and only its own go to its reader.

A record file (under the lock's `record-paths`, or hunsu's files) is nobody's work unless a task's own `--scope` names it.
Still, the records a task wrote in its window are its own facts: they are listed on the task as `records` (beside `touched`,
never inside it), shown by `show`, named by the `run` that finishes the task, and the verifier's request carries only them
as work to judge — in its `touched` and under `records` (`excluded.record-paths` stays empty) — never another open task's
scoped records, never a record another task's finish already listed, never a record that already differed, unchanged, when
the task started.

  python -m unittest test_task_records
"""
import glob
import json
import os
import re
import subprocess
import sys
import unittest

from test_chongdae import Project, run, write, RESPONSE_DONE
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))

# two record paths declared in the lock: a task scoped `mangsang` holds one; the other stays outside every scope
LOCK = {"roles": {}, "record-paths": {"mangsang": ["mangsang/"], "dwitbuk": ["reviews/"]}}
X = "mangsang/concepts/x.json"

# the machine-local keys an earlier version's overlay (local/tasks/<id>.json) could hold: a records snapshot is not among them
EARLIER_PRIVATE_KEYS = ("session", "transcript", "kept-locally", "start", "start-head", "start-heads", "evidence-start", "added-in",
                        "commands", "read", "reported", "rebaseline", "checked-tree", "checks-tree", "checks-source", "review-source",
                        "after-source", "completion-acks", "lease-held", "lease-work", "lease-established")


def git(pj, *argv):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *argv], cwd=pj.dir, check=True, capture_output=True)


def seed(pj, lock=LOCK):
    """A committed base: the lock with its record paths, a source file, one record file; then a session run."""
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
    write(os.path.join(pj.dir, "hunsu.lock.json"), lock)
    write(os.path.join(pj.dir, "src.py"), "x = 1\n")
    write(os.path.join(pj.dir, "mangsang", "other.json"), {"v": 0})
    git(pj, "add", "-A")
    git(pj, "commit", "-qm", "base")
    code, out = run("init", "--session", "--goal", "g", "--target", pj.dir)
    assert code == 0, out


def add_session_task(pj, tid, *more):
    """An unscoped session task: `--why` given, so the add is accepted whether or not a no-check session task must say why."""
    code, out = run("add", tid, "--brief", "the work of %s" % tid, "--why", "the session does this itself", *more, "--target", pj.dir)
    assert code == 0, out


def task(pj, tid):
    return pj.state()["tasks"][tid]


def records_of(ts):
    return ts.get("records") if "records" in ts else None


def record_line(out, path):
    """The one line of `run`'s output that names a record file the task wrote."""
    return [line for line in out.splitlines() if path in line and "git add" not in line and "git commit" not in line]


class SessionTaskRecords(unittest.TestCase):
    """D2 — an unscoped session task's own records are listed on it, shown, and named by `run`; nothing more."""

    def test_D2_an_uncommitted_record_written_in_the_window_is_listed_beside_touched_not_in_it(self):
        with Project() as pj:
            seed(pj)
            add_session_task(pj, "T")
            write(os.path.join(pj.dir, "src.py"), "x = 2\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            code, out = run("run", "T", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = task(pj, "T")
            self.assertEqual(ts.get("status"), "done", ts)
            self.assertEqual(ts.get("touched"), ["src.py"], "a record is never in touched: %r" % ts.get("touched"))
            self.assertIn("records", ts, "the record the task wrote is listed nowhere on it: %s" % sorted(ts))
            self.assertEqual(ts["records"], [X])
            # the run that finishes the task names it, in one line after its commit lines, and says --scope makes it the task's work
            lines = record_line(out, X)
            self.assertEqual(len(lines), 1, "run's output does not name the record once:\n%s" % out)
            self.assertIn("--scope", lines[0], lines[0])
            self.assertGreater(out.index(lines[0]), out.index("git commit"), "the records line comes after the commit lines:\n%s" % out)
            code, shown = run("show", "--target", pj.dir)
            self.assertEqual(code, 0, shown)
            self.assertIn("  records: %s" % X, shown, shown)
            self.assertGreater(shown.index("  records: "), shown.index("  touched: src.py"), "records is printed under touched:\n%s" % shown)

    def test_D2_a_record_committed_during_the_window_is_listed(self):
        with Project() as pj:
            seed(pj)
            add_session_task(pj, "T")
            write(os.path.join(pj.dir, "src.py"), "x = 2\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            git(pj, "add", "-A")
            git(pj, "commit", "-qm", "the session commits its work before run")
            code, out = run("run", "T", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = task(pj, "T")
            self.assertEqual(ts.get("touched"), ["src.py"], ts.get("touched"))
            self.assertIn("records", ts, "a record committed in the window is still the task's: %s" % sorted(ts))
            self.assertEqual(ts["records"], [X])
            self.assertEqual(len(record_line(out, X)), 1, out)
            code, shown = run("show", "--target", pj.dir)
            self.assertIn("  records: %s" % X, shown, shown)

    def test_D2_a_record_already_changed_at_add_and_unchanged_since_is_not_listed(self):
        with Project() as pj:
            seed(pj)
            write(os.path.join(pj.dir, "mangsang", "pre.json"), {"pre": 1})   # differs before the task exists; nobody touches it after
            add_session_task(pj, "T")
            write(os.path.join(pj.dir, "src.py"), "x = 2\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            code, out = run("run", "T", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = task(pj, "T")
            self.assertIn("records", ts, sorted(ts))
            self.assertEqual(ts["records"], [X], "a record that already differed when the task was added is not its own")
            self.assertEqual(record_line(out, "mangsang/pre.json"), [], out)

    def test_D2_a_record_under_another_open_tasks_scope_is_not_listed(self):
        with Project() as pj:
            seed(pj)
            add_session_task(pj, "S", "--scope", "mangsang")   # another open task owns everything under mangsang/
            add_session_task(pj, "U")
            write(os.path.join(pj.dir, "src.py"), "x = 2\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            write(os.path.join(pj.dir, "mangsang", "other.json"), {"v": 1})
            write(os.path.join(pj.dir, "reviews", "r.json"), {"r": 1})   # a record path no open scope holds
            code, out = run("run", "U", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = task(pj, "U")
            self.assertEqual(ts.get("status"), "done", ts)
            self.assertEqual(task(pj, "S").get("status"), "todo", "the scoped task stays open: run named U alone")
            self.assertEqual(ts.get("touched"), ["src.py"], ts.get("touched"))
            self.assertIn("records", ts, sorted(ts))
            self.assertEqual(ts["records"], ["reviews/r.json"], "nothing under the other open task's scope is this task's record")
            self.assertEqual(record_line(out, "mangsang/"), [], out)

    def test_D2_a_record_listed_at_a_first_finish_is_not_listed_again_unless_it_changed_after(self):
        with Project() as pj:
            seed(pj)
            add_session_task(pj, "A")
            add_session_task(pj, "B")
            add_session_task(pj, "C")
            write(os.path.join(pj.dir, "src.py"), "x = 2\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            code, out = run("run", "A", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("records", task(pj, "A"), sorted(task(pj, "A")))
            self.assertEqual(task(pj, "A")["records"], [X])
            # B, open at the same time, finishes without touching the record: A's finish pinned it
            write(os.path.join(pj.dir, "b.py"), "b = 1\n")
            code, out = run("run", "B", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(task(pj, "B").get("touched"), ["b.py"], task(pj, "B").get("touched"))
            self.assertFalse(records_of(task(pj, "B")), "a record another task's finish already listed, unchanged since, is not listed again: %r" % records_of(task(pj, "B")))
            self.assertEqual(record_line(out, X), [], out)
            # C, open as long: the record changed again after A's finish, so it is C's
            write(os.path.join(pj.dir, X), {"v": 2})
            write(os.path.join(pj.dir, "c.py"), "c = 1\n")
            code, out = run("run", "C", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(task(pj, "C").get("touched"), ["c.py"], task(pj, "C").get("touched"))
            self.assertIn("records", task(pj, "C"), sorted(task(pj, "C")))
            self.assertEqual(task(pj, "C")["records"], [X])

    def test_D2_records_are_not_the_tasks_work_and_close_does_not_stop_on_them(self):
        with Project() as pj:
            seed(pj)
            add_session_task(pj, "T")
            write(os.path.join(pj.dir, "src.py"), "x = 2\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            code, out = run("run", "T", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = task(pj, "T")
            self.assertIn("records", ts, sorted(ts))
            self.assertEqual(ts["records"], [X])
            self.assertNotIn(X, ts.get("touched") or [])
            self.assertNotIn("git add -- %s" % X, out, "a record gets no commit line of its own:\n%s" % out)
            git(pj, "add", "--", "src.py")
            git(pj, "commit", "-qm", "the work, committed; the record left as it is")
            code, out = run("close", "--target", pj.dir)
            self.assertEqual(code, 0, "close stops on nothing when only a record is uncommitted:\n%s" % out)


class HiredBuildPacket(unittest.TestCase):
    """D3 — the verifier's request carries only the build's own records, as work: in `touched` and under `records`."""

    def test_D3_verify_request_lists_only_the_builds_own_records(self):
        with Project() as pj:
            builder = os.path.join(pj.dir, "builder.py")
            response = dict(RESPONSE_DONE, verified=[{"check": sys.executable + " -c pass", "exit": 0}])
            write(builder, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\nt = req['target']\n"
                           "open(os.path.join(t, 'src.py'), 'w').write('x = 3\\n')\n"
                           "os.makedirs(os.path.join(t, 'mangsang'), exist_ok=True)\n"
                           "open(os.path.join(t, 'mangsang', 'own.json'), 'w').write('{\"own\": 1}\\n')\n"
                           "json.dump(%r, open(sys.argv[2], 'w'))\n" % response)
            eyes = os.path.join(pj.dir, "eyes.py")
            write(eyes, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                        "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept', 'findings': []}, open(sys.argv[2], 'w'))\n")
            lock = dict(LOCK, roles={"implementer": [sys.executable, builder, "{request}", "{response}"],
                                     "verifier": [sys.executable, eyes, "{request}", "{response}"]})
            seed(pj, lock)
            # another open task's model work, uncommitted: its scope holds the one record it changes, not the whole record path —
            # a scope of `mangsang` would hold the build's own mangsang/own.json too, and D1.2 would then rightly keep it out of the packet
            add_session_task(pj, "other", "--scope", "mangsang/other.json")
            write(os.path.join(pj.dir, "mangsang", "other.json"), {"v": 1})
            write(os.path.join(pj.dir, "mangsang", "pre.json"), {"pre": 1})   # already differs before the build starts; unchanged after
            code, out = run("add", "build", "--brief", "build it", "--check", sys.executable + " -c pass", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("implementer does it", out, out)
            code, out = run("run", "build", "--target", pj.dir)
            st = pj.state()["tasks"]
            self.assertEqual(st["build"].get("status"), "done", (code, out))
            self.assertEqual(st["other"].get("status"), "todo", "the scoped task stays open")
            seen = glob.glob(os.path.join(c.run_dir(pj.dir), "local", "build.verify*.request.json.seen"))
            self.assertEqual(len(seen), 1, "the verifier was sent one request: %r" % seen)
            req = json.load(open(seen[0], encoding="utf-8"))
            self.assertEqual(req.get("touched"), ["mangsang/own.json", "src.py"], "the build's code and its own record, the work to judge: %r" % req.get("touched"))
            self.assertEqual(req.get("touched_since"), [], req.get("touched_since"))
            self.assertEqual(req.get("excluded"), {"record-paths": []}, "no record the build changed is left out by rule: %r" % req.get("excluded"))
            self.assertIn("records", req, sorted(req))
            listed = req["records"].get("files")
            for other in ("mangsang/other.json", "mangsang/pre.json"):
                self.assertNotIn(other, req["touched"], "a record that is not the build's is not in its work: %r" % req["touched"])
            self.assertIn("mangsang/own.json", listed, "the build's own record goes to its reader")
            self.assertNotIn("mangsang/other.json", listed, "another open task's scoped record is not this build's: %r" % listed)
            self.assertNotIn("mangsang/pre.json", listed, "a record that already differed, unchanged, when the build started is not its own: %r" % listed)
            self.assertEqual(listed, ["mangsang/own.json"], listed)

    def test_D3_a_record_another_tasks_finish_listed_is_not_in_a_later_builds_packet(self):
        with Project() as pj:
            builder = os.path.join(pj.dir, "builder.py")
            response = dict(RESPONSE_DONE, verified=[{"check": sys.executable + " -c pass", "exit": 0}])
            write(builder, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\nt = req['target']\n"
                           "open(os.path.join(t, 'src.py'), 'w').write('x = 3\\n')\n"
                           "json.dump(%r, open(sys.argv[2], 'w'))\n" % response)
            eyes = os.path.join(pj.dir, "eyes.py")
            write(eyes, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                        "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept', 'findings': []}, open(sys.argv[2], 'w'))\n")
            lock = dict(LOCK, roles={"implementer": [sys.executable, builder, "{request}", "{response}"],
                                     "verifier": [sys.executable, eyes, "{request}", "{response}"]})
            seed(pj, lock)
            add_session_task(pj, "T")
            write(os.path.join(pj.dir, "t.py"), "t = 1\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            code, out = run("run", "T", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("records", task(pj, "T"), sorted(task(pj, "T")))
            self.assertEqual(task(pj, "T")["records"], [X])
            code, out = run("add", "build", "--brief", "build it", "--check", sys.executable + " -c pass", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            code, out = run("run", "build", "--target", pj.dir)
            self.assertEqual(task(pj, "build").get("status"), "done", (code, out))
            seen = glob.glob(os.path.join(c.run_dir(pj.dir), "local", "build.verify*.request.json.seen"))
            self.assertEqual(len(seen), 1, seen)
            req = json.load(open(seen[0], encoding="utf-8"))
            self.assertIn("excluded", req, sorted(req))
            self.assertEqual(req["excluded"].get("record-paths"), [], req["excluded"])
            self.assertEqual(req.get("touched"), ["src.py"], "a record the earlier task's finish listed, unchanged since, is not this build's work: %r" % req.get("touched"))
            self.assertNotIn("records", req, "a build that changed no record of its own names none: %r" % req.get("records"))


class EarlierVersionsTask(unittest.TestCase):
    """D4 — a task recorded without a records snapshot is finished and shown; its window falls back to its start-head."""

    def test_D4_a_task_without_a_records_snapshot_is_finished_and_shown_from_its_start_head(self):
        with Project() as pj:
            seed(pj)
            add_session_task(pj, "T")
            overlay = os.path.join(c.run_dir(pj.dir), "local", "tasks", "T.json")
            self.assertTrue(os.path.isfile(overlay), overlay)
            kept = json.load(open(overlay, encoding="utf-8"))
            kept = {k: v for k, v in kept.items() if k in EARLIER_PRIVATE_KEYS}   # as an earlier version wrote it: no records snapshot
            self.assertIn("start-head", kept, sorted(kept))
            write(overlay, kept)
            write(os.path.join(pj.dir, "src.py"), "x = 2\n")
            write(os.path.join(pj.dir, X), {"v": 1})
            try:
                code, out = run("run", "T", "--target", pj.dir)
            except Exception as err:   # noqa: BLE001 — the contract: no exception for an earlier version's task
                self.fail("run raised on a task without a records snapshot: %r" % (err,))
            self.assertEqual(code, 0, out)
            ts = task(pj, "T")
            self.assertEqual(ts.get("status"), "done", ts)
            self.assertEqual(ts.get("touched"), ["src.py"], ts.get("touched"))
            self.assertIn("records", ts, "measured from its start-head, the record it wrote is its own: %s" % sorted(ts))
            self.assertEqual(ts["records"], [X])
            try:
                code, shown = run("show", "--target", pj.dir)
            except Exception as err:   # noqa: BLE001
                self.fail("show raised on a task without a records snapshot: %r" % (err,))
            self.assertEqual(code, 0, shown)
            self.assertIn("  records: %s" % X, shown, shown)


class ReadmeSaysSo(unittest.TestCase):
    """D5 — plugin/README.md names `records` where record paths are said to be nobody's work, where the verifier's request is
    described, and in the task record's fields under Files in your project."""

    def paragraphs(self):
        text = open(os.path.join(HERE, "plugin", "README.md"), encoding="utf-8").read()
        return text, [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    @staticmethod
    def names_records(paragraph):
        return "`records`" in paragraph or re.search(r"\bown records\b", paragraph) is not None

    def test_D5_readme_names_records_where_record_paths_are_nobodys_work(self):
        _, paras = self.paragraphs()
        about = [p for p in paras if "nobody's" in p and "record" in p and "scope" in p]
        self.assertTrue(about, "no README paragraph says a record outside every scope is nobody's work")
        self.assertTrue(any(self.names_records(p) for p in about), "the records a task wrote are not named where record paths are said to be nobody's work:\n%s" % "\n---\n".join(about))

    def test_D5_readme_names_records_where_the_verifiers_request_is_described(self):
        _, paras = self.paragraphs()
        about = [p for p in paras if "excluded.record-paths" in p]
        self.assertTrue(about, "no README paragraph describes `excluded.record-paths`")
        self.assertTrue(any(self.names_records(p) and re.search(r"\bown\b", p) for p in about),
                        "the verifier's request is not said to carry only the task's own records:\n%s" % "\n---\n".join(about))

    def test_D5_readme_lists_records_among_the_task_records_fields(self):
        text, _ = self.paragraphs()
        self.assertIn("## Files in your project", text)
        section = text.split("## Files in your project", 1)[1]
        heading = re.search(r"\n### `[^`\n]*tasks/<id>\.json`", section)
        self.assertIsNotNone(heading, "the task file has no heading under Files in your project")
        body = section[heading.end():]
        end = body.find("\n### ")
        body = body[:end] if end > -1 else body
        fields = [p for p in re.split(r"\n\s*\n", body) if "one file per task" in p and "touched" in p]
        self.assertEqual(len(fields), 1, "the task file's field list (one file per task: status, claim, touched, …) is not where it was:\n%s" % body[:1500])
        self.assertIsNotNone(re.search(r"(?<![\w`.-])`?records`?(?![\w`-])", fields[0]),
                             "the task record's `records` is not listed beside touched under Files in your project:\n%s" % fields[0])


if __name__ == "__main__":
    unittest.main()
