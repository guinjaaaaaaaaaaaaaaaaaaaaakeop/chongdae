"""Contract T: a task's work is what it carries, its commit is said as not made, and the session says why it did a worker's task.

Found in a sibling project's day of real work: a session task scoped to the model's record directory was added after its
record files were written, recorded `touched: []` and "nothing to review", while the commit made under its name carried them
all; `done` was read as committed; commit subjects were cut mid-word; and every task a worker was hired for was done by the
session with a `--why` that described the work instead of saying why the worker was not hired, untested code unsaid.

T1 — work done before a task is added, inside its own scope, is its work (`held-at-add`). T2 — `done` says the work is not
committed, the next task hears it, and no commit subject is cut. T3 — self-performance names a reason class, and untested code
is said. T4 — the README, the run skill and `add --help` say so.

Every test goes through the CLI the way a session meets it: a temporary git project, fake providers that are small scripts,
no network, no model. Run with ``python3 -m unittest test_task_work``.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import unittest

from test_chongdae import Project, run, write, UNCOMMITTED
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PASS_CHECK = PY + " -c pass"
R1 = "mangsang/relations/R-1.json"
R2 = "mangsang/relations/R-2.json"
R3 = "mangsang/relations/R-3.json"
CLASSES = ("owner-dialogue", "latency", "capability", "provider-unavailable", "operation", "project-rule", "worker-contract")
RESPONSE_BLOCKED = {"status": "blocked", "summary": "never sent", "verified": [], "decisions": [], "non-claims": []}


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True)


def held_at_add_said(text):
    return re.search(r"held[ -]at[ -]add", text, re.IGNORECASE) is not None


class TaskWorkCase(unittest.TestCase):
    def setUp(self):
        self.pj = Project()
        self.pj.__enter__()
        self.dir = self.pj.dir
        self.addCleanup(self.pj.__exit__, None, None, None)
        user = os.environ.pop("CHONGDAE_USER", None)
        if user is not None:
            self.addCleanup(os.environ.__setitem__, "CHONGDAE_USER", user)

    # -- fixtures -------------------------------------------------------------------------------------------------------

    def cli(self, *argv):
        return run(*argv, "--target", self.dir)

    def path(self, rel):
        return os.path.join(self.dir, rel)

    def fake_verifier(self):
        """A verifier command that appends every request to `seen.jsonl` beside it (the run's local/) and accepts."""
        script = self.path(os.path.join("fakes", "eyes.py"))
        write(script,
              "import json, os, sys\n"
              "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
              "with open(os.path.join(os.path.dirname(sys.argv[1]), 'seen.jsonl'), 'a', encoding='utf-8') as fh:\n"
              "    fh.write(json.dumps(req) + '\\n')\n"
              "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept', 'findings': []}, open(sys.argv[2], 'w', encoding='utf-8'))\n")
        return [PY, script, "{request}", "{response}"]

    def fake_answer(self, response, name):
        script = self.path(os.path.join("fakes", name + ".py"))
        write(script, "import json, sys\njson.dump(json.loads(%r), open(sys.argv[2], 'w', encoding='utf-8'))\n" % json.dumps(response))
        return [PY, script, "{request}", "{response}"]

    def init_session(self, roles=None, files=(), local=None, goal="g", record_paths=True):
        """A committed base (a git identity, fakes/ ignored, a source file, a record file, `files`), the lock with `roles` and a
        record path for the model directory, then a session run."""
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        write(self.path(".gitignore"), "fakes/\n")
        lock = {"roles": roles or {}}
        if record_paths:
            lock["record-paths"] = {"mangsang": ["mangsang/"]}
        write(self.path("hunsu.lock.json"), lock)
        write(self.path("src/a.py"), "a = 0\n")
        write(self.path("mangsang/base.json"), "{}\n")
        for rel, text in files:
            write(self.path(rel), text)
        if local is not None:
            write(self.path("hunsu.local.json"), local)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "base")
        code, out = self.cli("init", "--session", "--goal", goal)
        self.assertEqual(code, 0, out)

    def run_id(self):
        return os.path.basename(c.run_dir(self.dir))

    def tasks(self):
        return self.pj.state()["tasks"]

    def task(self, tid):
        tasks = self.tasks()
        self.assertIn(tid, tasks, "no task %s in the run: %s" % (tid, sorted(tasks)))
        return tasks[tid]

    def seen(self):
        path = os.path.join(c.run_dir(self.dir), "local", "seen.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def two_records(self):
        write(self.path(R1), '{"r": 1}\n')
        write(self.path(R2), '{"r": 2}\n')

    def commit_line(self, out, tid=None):
        lines = [l.strip() for l in out.splitlines() if l.strip().startswith("git commit")]
        if tid is not None:
            lines = [l for l in lines if "/%s (session)" % tid in l]
        self.assertTrue(lines, "no `git commit` line%s in the output:\n%s" % (" for " + tid if tid else "", out))
        return lines[0]

    @staticmethod
    def messages(argv):
        return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-m"]

    @staticmethod
    def files_of(argv):
        return argv[argv.index("--") + 1:] if "--" in argv else []


# ====================================================================== T1: work held at add

class T1_HeldAtAdd(TaskWorkCase):

    def add_scoped(self, *more, check=True):
        argv = ["add", "T", "--scope", "mangsang", "--brief", "reconfirm the relations", "--why", "w"]
        if check:
            argv += ["--check", PASS_CHECK]
        code, out = self.cli(*argv, *more)
        self.assertEqual(code, 0, out)
        return out

    def test_T1_1_add_prints_one_line_naming_the_files_changed_before_it_inside_its_scope(self):
        self.init_session()
        self.two_records()
        out = self.add_scoped()
        lines = [l for l in out.splitlines() if R1 in l and R2 in l]
        self.assertEqual(len(lines), 1, "add does not print one line naming both files as work held at add:\n" + out)
        self.assertTrue(held_at_add_said(lines[0]) or "before" in lines[0], lines[0])
        self.assertIn("chongdae adopt", out, "the line gives the judgment that hands a file to another task:\n" + out)

    def test_T1_1_the_task_records_held_at_add_with_both_files(self):
        self.init_session()
        self.two_records()
        self.add_scoped()
        ts = self.task("T")
        self.assertIn("held-at-add", ts, "no held-at-add on the task: %s" % sorted(ts))
        rec = ts["held-at-add"]
        self.assertIsInstance(rec, dict, rec)
        self.assertEqual(sorted(rec.get("files") or []), [R1, R2], rec)
        self.assertEqual(rec.get("why"), "changed before T was added, inside its own scope, claimed by no other task", rec)
        self.assertIn("at", rec)
        self.assertIn("chongdae", rec)

    def test_T1_2_the_verifier_is_sent_the_held_files_in_touched_and_the_task_lists_them(self):
        self.init_session({"verifier": self.fake_verifier()})
        self.two_records()
        self.add_scoped()
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        seen = [r for r in self.seen() if r.get("task") == "T"]
        self.assertEqual(len(seen), 1, "the verifier was not asked once about T: %d request(s)\n%s" % (len(seen), out))
        self.assertEqual(sorted(seen[0].get("touched") or []), [R1, R2], seen[0].get("touched"))
        ts = self.task("T")
        self.assertEqual(ts.get("status"), "done", out)
        self.assertEqual(sorted(ts.get("touched") or []), [R1, R2], ts.get("touched"))
        self.assertNotIn("nothing-to-review", ts, "a task carrying held-at-add files never records nothing-to-review")
        line = self.commit_line(out, "T")
        self.assertEqual(sorted(self.files_of(shlex.split(line))), [R1, R2], line)

    def test_T1_2_the_request_names_the_held_files_under_attribution_as_held_at_add(self):
        self.init_session({"verifier": self.fake_verifier()})
        self.two_records()
        self.add_scoped()
        code, out = self.cli("run", "T")
        seen = [r for r in self.seen() if r.get("task") == "T"]
        self.assertEqual(len(seen), 1, "the verifier was not asked about T:\n" + out)
        self.assertIn("attribution", seen[0], sorted(seen[0]))
        said = json.dumps(seen[0]["attribution"])
        self.assertIn("held-at-add", said, said)
        self.assertIn(R1, said, said)
        self.assertIn(R2, said, said)

    def test_T1_2_no_check_task_finished_by_name_carries_the_held_files(self):
        self.init_session()
        self.two_records()
        self.add_scoped(check=False)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts.get("status"), "done", out)
        self.assertEqual(sorted(ts.get("touched") or []), [R1, R2], ts.get("touched"))
        self.assertNotIn("nothing-to-review", ts)

    def test_T1_2_a_held_file_changed_back_to_head_drops_out_and_one_changed_since_stays(self):
        self.init_session()
        self.two_records()
        self.add_scoped()
        os.remove(self.path(R2))                     # back to HEAD: no longer changed
        write(self.path(R1), '{"r": 11}\n')          # changed since add: still T's
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts.get("touched"), [R1], ts.get("touched"))
        self.assertIn("held-at-add", ts, sorted(ts))
        self.assertIn(R1, ts["held-at-add"].get("files") or [])

    def test_T1_2_a_held_file_unchanged_since_add_is_in_touched(self):
        self.init_session()
        write(self.path(R1), '{"r": 1}\n')
        self.add_scoped()
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T").get("touched"), [R1], out)
        self.assertNotIn("nothing-to-review", self.task("T"))
        self.assertIsNone(re.search(r"nothing[ -]to[ -]review", out, re.IGNORECASE), out)

    def test_T1_1_a_file_a_narrower_open_task_scopes_is_claimed_and_named_with_it(self):
        self.init_session()
        self.two_records()
        code, out = self.cli("add", "U", "--scope", R1, "--brief", "one relation", "--why", "w")
        self.assertEqual(code, 0, out)
        out = self.add_scoped()
        ts = self.task("T")
        self.assertIn("held-at-add", ts, sorted(ts))
        self.assertEqual(ts["held-at-add"].get("files"), [R2], "the file U's narrower scope holds is not T's: %s" % ts["held-at-add"])
        claimed = [l for l in out.splitlines() if R1 in l]
        self.assertTrue(claimed, "add does not name the claimed file:\n" + out)
        self.assertTrue(any(re.search(r"\bU\b", l) for l in claimed), "the add line does not name U as claiming %s:\n%s" % (R1, out))

    def test_T1_1_a_finished_tasks_uncommitted_work_inside_the_scope_is_not_counted(self):
        self.init_session()
        code, out = self.cli("add", "F", "--scope", R3, "--brief", "a third relation", "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        write(self.path(R3), '{"r": 3}\n')
        code, out = self.cli("run", "F")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("F").get("status"), "done", out)
        self.assertIn(R3, self.task("F").get("touched") or [], "the fixture: F's uncommitted work holds %s" % R3)
        write(self.path(R1), '{"r": 1}\n')
        self.add_scoped()
        ts = self.task("T")
        self.assertIn("held-at-add", ts, sorted(ts))
        self.assertEqual(ts["held-at-add"].get("files"), [R1], "F's uncommitted work is F's, not T's: %s" % ts["held-at-add"])

    def test_T1_3_a_no_check_task_holding_only_held_files_stays_open_on_a_bare_run_then_finishes_by_name(self):
        self.init_session()
        self.two_records()
        self.add_scoped(check=False)
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, "a bare run does not finish it (exit 2):\n" + out)
        self.assertEqual(self.task("T").get("status"), "todo", out)
        held = [l for l in out.splitlines() if R1 in l and R2 in l]
        self.assertTrue(held, "the bare run's output gives no held line naming the held-at-add files:\n" + out)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts.get("status"), "done", out)
        nc = ts.get("non-claims") or []
        self.assertFalse([n for n in nc if "nothing of its own in the tree" in n],
                         "the non-claim says the tree holds nothing of its own though it holds held-at-add work: %s" % nc)
        named = [n for n in nc if R1 in n and R2 in n and held_at_add_said(n)]
        self.assertTrue(named, "no non-claim names the files as work held at add: %s" % nc)

    def test_T1_4_a_task_with_no_scope_does_not_count_a_file_changed_before_it(self):
        """Unchanged by contract T: may pass before the build."""
        self.init_session()
        write(self.path("src/a.py"), "a = 1\n")
        code, out = self.cli("add", "T", "--brief", "unscoped", "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        self.assertNotIn("held-at-add", self.task("T"))
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T").get("touched"), [], out)


# ====================================================================== T2: done says not committed; subjects are whole

class T2_NotCommitted(TaskWorkCase):

    def done_T_with_a_uncommitted(self, brief="Fix a"):
        self.init_session()
        code, out = self.cli("add", "T", "--brief", brief, "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        write(self.path("src/a.py"), "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T").get("status"), "done", out)
        return out

    def test_T2_1_the_done_line_says_not_committed_before_the_commit_lines(self):
        out = self.done_T_with_a_uncommitted()
        done = [l for l in out.splitlines() if re.match(r"\s*done T\b", l)]
        self.assertEqual(len(done), 1, out)
        self.assertIn("not committed", done[0].lower(), "the done line does not say the work is not committed:\n" + out)
        self.assertLess(out.index(done[0]), out.index("git commit"), out)

    def test_T2_1_work_committed_before_run_is_said_done_only(self):
        """As today: may pass before the build."""
        self.init_session()
        code, out = self.cli("add", "T", "--brief", "Fix a", "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        write(self.path("src/a.py"), "a = 1\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "the work")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertIn("done T", out)
        self.assertNotIn("not committed", out.lower(), out)

    def test_T2_2_add_of_a_task_whose_scope_holds_a_finished_tasks_uncommitted_file_prints_a_note(self):
        self.done_T_with_a_uncommitted()
        code, out = self.cli("add", "U", "--scope", "src/a.py", "--brief", "more on a", "--why", "w")
        self.assertEqual(code, 0, "notes only: nothing is refused\n" + out)
        notes = [l for l in out.splitlines() if "note" in l.lower() and "src/a.py" in l and re.search(r"\bT\b", l)]
        self.assertTrue(notes, "add U prints no note naming T and src/a.py:\n" + out)
        self.assertIn("git commit", out, "the note gives T's commit lines:\n" + out)

    def test_T2_2_run_of_the_next_task_says_ts_reviewed_version_is_no_longer_in_the_tree(self):
        self.done_T_with_a_uncommitted()
        code, out = self.cli("add", "U", "--scope", "src/a.py", "--brief", "more on a", "--why", "w")
        self.assertEqual(code, 0, out)
        write(self.path("src/a.py"), "a = 2\n")
        code, out = self.cli("run", "U")
        self.assertIn("src/a.py", self.task("U").get("touched") or [], "the fixture: U measures src/a.py:\n" + out)
        notes = [l for l in out.splitlines() if "src/a.py" in l and re.search(r"\bT\b", l) and "no longer in the tree" in l]
        self.assertTrue(notes, "run U does not say T's reviewed version of src/a.py is no longer in the tree:\n" + out)

    def test_T2_3_a_long_unbroken_brief_gives_a_bare_subject_and_the_whole_brief_in_a_body(self):
        brief = ("word " * 60).strip() + "s"
        self.assertEqual(len(brief), 300)
        out = self.done_T_with_a_uncommitted(brief)
        argv = shlex.split(self.commit_line(out))
        self.assertEqual(argv[:2], ["git", "commit"], argv)
        msgs = self.messages(argv)
        self.assertEqual(len(msgs), 2, "a subject and a body (`-m SUBJECT -m BODY`): %r" % argv)
        self.assertEqual(msgs[0], "%s/T (session)" % self.run_id(), msgs[0])
        self.assertNotIn("…", msgs[0])
        self.assertEqual(" ".join(msgs[1].split()), brief, "the body is not the whole brief: %r" % msgs[1])
        self.assertEqual(self.files_of(argv), ["src/a.py"], argv)

    def test_T2_3_a_brief_with_a_short_first_sentence_gives_it_as_the_subject(self):
        brief = "Fix the header. Then much more text follows, describing the rest of the change at length."
        out = self.done_T_with_a_uncommitted(brief)
        argv = shlex.split(self.commit_line(out))
        msgs = self.messages(argv)
        self.assertTrue(msgs, argv)
        self.assertEqual(msgs[0], "%s/T (session): Fix the header" % self.run_id(), argv)
        self.assertEqual(len(msgs), 2, argv)
        self.assertEqual(" ".join(msgs[1].split()), brief, msgs[1])

    def test_T2_3_no_record_commit_subject_is_cut_and_done_is_named_by_action_and_task(self):
        brief = ("word " * 60).strip() + "s"
        goal = ("the goal of this run, said at length " * 6).strip()
        self.init_session(local={"settings": {"chongdae": {"commit-records": True}}}, goal=goal)
        code, out = self.cli("add", "T", "--brief", brief, "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        write(self.path("src/a.py"), "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        code, out = self.cli("close", *UNCOMMITTED)
        self.assertEqual(code, 0, out)
        rid = self.run_id()
        log = git(self.dir, "log", "--format=%x1e%s%x1f%b").stdout
        commits = [e.split("\x1f", 1) for e in log.split("\x1e") if e.strip()]
        mine = [(s.strip(), b) for s, b in commits if s.startswith(rid)]
        self.assertTrue(mine, "the run made no record commits:\n" + log)
        cut = [s for s, _ in mine if s.endswith("…")]
        self.assertEqual(cut, [], "record commit subjects cut with …: %s" % cut)
        done = [(s, b) for s, b in mine if " done T" in s or s.endswith("done T")]
        self.assertTrue(done, "no done record commit: %s" % [s for s, _ in mine])
        self.assertEqual(done[0][0], "%s: done T" % rid, done[0][0])
        self.assertIn(brief, " ".join(done[0][1].split()), "the done commit's body does not hold the brief: %r" % done[0][1])


# ====================================================================== T3: why the worker was not hired; untested code

class T3_1_ReasonClass(TaskWorkCase):

    def init_hired(self):
        self.init_session({"implementer": self.fake_answer(RESPONSE_BLOCKED, "builder"),
                           "nitpick": self.fake_answer(RESPONSE_BLOCKED, "writer")})

    def test_T3_1_a_why_without_a_reason_class_is_refused_and_lists_the_classes(self):
        self.init_hired()
        code, out = self.cli("add", "T", "--role", "session", "--check", PASS_CHECK, "--why", "the work is small")
        self.assertNotEqual(code, 0, "a self-performed task with no reason class was added:\n" + out)
        self.assertNotIn("T", self.tasks(), "refused, yet the task exists")
        missing = [k for k in CLASSES if k not in out]
        self.assertEqual(missing, [], "the refusal does not list the classes %s:\n%s" % (missing, out))

    def test_T3_1_a_classed_why_is_kept_with_its_class_shown_and_reported(self):
        why = "latency: three lines in one function"
        self.init_hired()
        code, out = self.cli("add", "T", "--role", "session", "--check", PASS_CHECK, "--why", why)
        self.assertEqual(code, 0, out)
        own = self.task("T").get("self-performed")
        self.assertIsInstance(own, dict, self.task("T"))
        self.assertEqual(own.get("why"), why, own)
        self.assertIn("because", own, "the reason class is not kept on self-performed: %s" % own)
        self.assertEqual(own["because"], "latency", own)
        code, shown = self.cli("show")
        self.assertEqual(code, 0, shown)
        line = [l for l in shown.splitlines() if "self-performed" in l]
        self.assertTrue(line and "latency" in line[0], shown)
        write(self.path("src/a.py"), "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.cli("close", *UNCOMMITTED)[0], 0)
        code, out = self.cli("report")
        self.assertEqual(code, 0, out)
        obs = [f for f in json.loads(out)["findings"] if f.get("kind") == "self-performed"]
        self.assertTrue(obs and any("latency" in json.dumps(f) for f in obs), "report's self-performed observation does not name latency: %s" % obs)

    def test_T3_1_a_tests_task_taken_from_the_nitpick_records_its_class(self):
        self.init_hired()
        code, out = self.cli("add", "t", "--role", "session", "--tests", "t.py",
                             "--why", "worker-contract: the tests must pass before the build")
        self.assertEqual(code, 0, out)
        own = self.task("t").get("self-performed")
        self.assertIsInstance(own, dict, self.task("t"))
        self.assertIn("because", own, own)
        self.assertEqual(own["because"], "worker-contract", own)

    def test_T3_1_a_session_task_with_no_role_due_keeps_a_free_why(self):
        """As today (no role is due: no check, no tests): may pass before the build."""
        self.init_hired()
        code, out = self.cli("add", "F", "--brief", "a decision", "--why", "a decision nothing checks")
        self.assertEqual(code, 0, out)
        self.assertNotIn("self-performed", self.task("F"))
        self.assertEqual((self.task("F").get("no-check") or {}).get("why"), "a decision nothing checks")

    def test_T3_1_a_task_chongdae_gives_the_session_for_a_lacked_capability_records_capability(self):
        lacked = {"status": "failed", "summary": "the tests need a local server", "verified": [], "decisions": [], "lacked": ["loopback"],
                  "non-claims": ["sandbox lacked: loopback — could not bind a local port"]}
        self.init_session({"implementer": self.fake_answer(lacked, "lacks")},
                          files=[("hunsu.json", json.dumps({"capabilities": {"loopback": "session"}}))])
        code, out = self.cli("add", "w", "--check", PASS_CHECK, "--brief", "a build")
        self.assertEqual(code, 0, out)
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        ts = self.task("w")
        self.assertIn("taken", ts, "the fixture: the session takes w for the lacked capability:\n" + out)
        own = ts.get("self-performed")
        self.assertIsInstance(own, dict, "a task taken for a lacked capability is self-performed: %s" % sorted(ts))
        self.assertEqual(own.get("because"), "capability", own)


class T3_2_Untested(TaskWorkCase):

    def session_task(self, tid, files, *more):
        code, out = self.cli("add", tid, "--brief", "the work of %s" % tid, "--check", PASS_CHECK, *more)
        self.assertEqual(code, 0, out)
        for rel in files:
            write(self.path(rel), "# changed by %s\n" % tid)
        code, out = self.cli("run", tid)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task(tid).get("status"), "done", out)
        return out

    def assert_untested(self, tid, out, code_files):
        ts = self.task(tid)
        self.assertIn("untested", ts, "%s changes code and no test file, yet records no untested: %s" % (tid, sorted(ts)))
        rec = ts["untested"]
        self.assertEqual(rec.get("code"), code_files, rec)
        self.assertEqual(rec.get("why"), "it changes code and no test file, and declares no tests", rec)
        self.assertIn("at", rec)
        self.assertIn("chongdae", rec)
        notes = [l for l in out.splitlines() if "note" in l and ("%s is untested" % tid) in l]
        self.assertTrue(notes, "the done line prints no note that %s is untested:\n%s" % (tid, out))
        self.assertTrue(all(f in notes[0] for f in code_files), notes[0])

    def test_T3_2_a_task_changing_only_code_is_untested_said_and_listed_at_close(self):
        self.init_session()
        out = self.session_task("T", ["src/app.py"])
        self.assert_untested("T", out, ["src/app.py"])
        code, out = self.cli("close", *UNCOMMITTED)
        self.assertEqual(code, 0, out)
        self.assertIn("it changes code and no test file, and declares no tests", out, "close does not list the untested non-claim:\n" + out)

    def test_T3_2_a_task_changing_code_and_a_test_file_is_not_untested(self):
        self.init_session()
        out = self.session_task("U", ["src/u.py"])
        self.assert_untested("U", out, ["src/u.py"])      # the rule is in force in this run
        self.session_task("T", ["src/app.py", "tests/test_app.py"])
        self.assertNotIn("untested", self.task("T"))

    def test_T3_2_a_task_declaring_tests_is_not_untested(self):
        self.init_session(files=[("tests/test_app.py", "# a test\n")])
        out = self.session_task("U", ["src/u.py"])
        self.assert_untested("U", out, ["src/u.py"])
        self.session_task("T", ["src/app.py"], "--tests", "tests/test_app.py")
        self.assertNotIn("untested", self.task("T"))

    def test_T3_2_a_task_changing_only_documentation_is_not_untested(self):
        self.init_session()
        out = self.session_task("U", ["src/u.py"])
        self.assert_untested("U", out, ["src/u.py"])
        self.session_task("T", ["README.md"])
        self.assertNotIn("untested", self.task("T"))


# ====================================================================== T4: documentation

class T4_Documentation(unittest.TestCase):

    def read(self, *rel):
        with open(os.path.join(HERE, *rel), encoding="utf-8") as fh:
            return fh.read()

    def test_T4_readme_names_held_at_add_untested_and_the_reason_classes(self):
        text = self.read("plugin", "README.md")
        self.assertIn("held-at-add", text)
        self.assertIn("untested", text)
        self.assertIn("because", text)
        missing = [k for k in CLASSES if "`%s`" % k not in text and k not in text]
        self.assertEqual(missing, [], "README does not name the reason classes %s" % missing)

    def test_T4_run_skill_says_the_commit_lines_are_not_yet_run_and_names_the_classes(self):
        text = self.read("plugin", "skills", "run", "SKILL.md")
        missing = [k for k in CLASSES if k not in text]
        self.assertEqual(missing, [], "the run skill does not name the reason classes %s" % missing)
        paras = [p for p in re.split(r"\n\s*\n", text) if "done" in p and "commit" in p and re.search(r"not (yet )?committed", p, re.IGNORECASE)]
        self.assertTrue(paras, "the run skill does not say the done line's commit lines are not yet run (the work is not committed)")

    def test_T4_add_help_names_the_reason_classes(self):
        code, out = run("add", "--help")
        missing = [k for k in CLASSES if k not in out]
        self.assertEqual(missing, [], "add --help does not name the reason classes %s:\n%s" % (missing, out))


if __name__ == "__main__":
    unittest.main()
