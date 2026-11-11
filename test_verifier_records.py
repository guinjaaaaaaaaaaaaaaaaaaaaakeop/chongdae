"""Contract C2: the records a task changed are work its verifier judges.

An agent that edits a file may sign, right after, its own re-read of a model's relations on that file. The record that
holds that signature is changed in the task's window, yet the verifier placed on the task was only told that the record
was left out by rule: context, not work. These tests decide that

C2.1 — every record file among a task's work is in the request's `touched` and named again under `records.files`,
       `excluded.record-paths` stays and is empty, and one engine function (`task_work`) computes the work set;
C2.2 — `records.judge` says, with no product name, that a record asserting a judgment is a claim to check;
C2.3 — a reject whose finding quotes what a record stores stands on that quote;
C2.4 — which records are a task's own does not change, nor do the task record's own fields;
C2.5 — the README says so where the verifier's request is described.

Every case goes through the CLI in a temporary git project whose lock declares a record path for a model directory and a
fake verifier that keeps each request it is sent. Offline, no model, no network.

  python -m unittest test_verifier_records
"""
import json
import os
import re
import subprocess
import sys
import unittest

from test_chongdae import Project, run, write
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PASS_CHECK = PY + " -c pass"

RECORD_PATHS = {"model": ["model/"]}
X = "model/concepts/x.json"          # a record no base commit holds: a task writes it
KEPT = "model/kept.json"             # a record the base commit holds
CODE = "src/a.py"

# stored only in a record file: no brief, no check and no other file of a test project carries it
STORED = "Re-read against the changed file and every relation still holds as written."
PRODUCTS = ("chongdae", "mangsang", "dwitbuk", "hunsu", "hacheong", "jokbo")
RULE_WORDS = ("claim", "confirmation", "re-read", "approval", "person")

ACCEPT = {"artifact-type": "dwitbuk/review@1", "verdict": "accept", "findings": [], "summary": "accepted"}


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True)


class Case(unittest.TestCase):
    """A temporary git project: a base commit with the lock (a record path for `model/`, a fake verifier), a code file and a
    record file; then a session run. The verifier copies every request it gets to `seen.jsonl` beside the request and answers
    what `fakes/review.json` holds."""

    def setUp(self):
        self.pj = Project()
        self.pj.__enter__()
        self.dir = self.pj.dir
        self.addCleanup(self.pj.__exit__, None, None, None)
        self._user = os.environ.pop("CHONGDAE_USER", None)
        if self._user is not None:
            self.addCleanup(os.environ.__setitem__, "CHONGDAE_USER", self._user)

    def cli(self, *argv):
        return run(*argv, "--target", self.dir)

    def put(self, path, text):
        write(os.path.join(self.dir, *path.split("/")), text)

    def answer(self, review):
        self.put("fakes/review.json", review)

    def verifier(self):
        self.put("fakes/eyes.py",
                 "import json, os, sys\n"
                 "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
                 "with open(os.path.join(os.path.dirname(sys.argv[1]), 'seen.jsonl'), 'a', encoding='utf-8') as fh:\n"
                 "    fh.write(json.dumps(req) + '\\n')\n"
                 "here = os.path.dirname(os.path.abspath(__file__))\n"
                 "json.dump(json.load(open(os.path.join(here, 'review.json'), encoding='utf-8')), open(sys.argv[2], 'w', encoding='utf-8'))\n")
        return [PY, os.path.join(self.dir, "fakes", "eyes.py"), "{request}", "{response}"]

    def builder(self, code_file="src/a.py", record="model/own.json"):
        """An implementer command: writes a code file and a record under the request's target, then answers done."""
        response = {"status": "done", "summary": "built", "non-claims": [], "verified": [{"check": PASS_CHECK, "exit": 0}]}
        self.put("fakes/builder.py",
                 "import json, os, sys\n"
                 "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
                 "for rel, text in json.loads(%r):\n"
                 "    p = os.path.join(req['target'], *rel.split('/'))\n"
                 "    os.makedirs(os.path.dirname(p), exist_ok=True)\n"
                 "    open(p, 'w', encoding='utf-8').write(text)\n"
                 "json.dump(json.loads(%r), open(sys.argv[2], 'w', encoding='utf-8'))\n"
                 % (json.dumps([[code_file, "a = 3\n"], [record, '{"own": 1}\n']]), json.dumps(response)))
        return [PY, os.path.join(self.dir, "fakes", "builder.py"), "{request}", "{response}"]

    def start(self, review=ACCEPT, roles=None, files=()):
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        self.put(".gitignore", "fakes/\n")
        self.put(CODE, "a = 0\n")
        self.put(KEPT, '{"v": 0}\n')
        for path, text in files:
            self.put(path, text)
        self.put("hunsu.lock.json", {"roles": dict({"verifier": self.verifier()}, **(roles or {})), "record-paths": RECORD_PATHS})
        self.answer(review)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "base")
        code, out = self.cli("init", "--session", "--goal", "g")
        self.assertEqual(code, 0, out)

    def add(self, tid, *more):
        code, out = self.cli("add", tid, "--brief", "the work of %s" % tid, *more)
        self.assertEqual(code, 0, out)
        return out

    def add_no_check(self, tid, *more):
        return self.add(tid, "--why", "the session does this itself", *more)

    def add_checked(self, tid, *more):
        return self.add(tid, "--check", PASS_CHECK, *more)

    def task(self, tid="T"):
        tasks = self.pj.state()["tasks"]
        self.assertIn(tid, tasks, "no task %s in the run: %s" % (tid, sorted(tasks)))
        return tasks[tid]

    def seen(self, tid=None):
        path = os.path.join(c.run_dir(self.dir), "local", "seen.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            reqs = [json.loads(line) for line in fh if line.strip()]
        return [r for r in reqs if tid is None or r.get("task") == tid]

    def request(self, tid="T", out=""):
        """The one request the verifier was sent for the task."""
        reqs = self.seen(tid)
        self.assertEqual(len(reqs), 1, "the verifier was sent %d request(s) for %s:\n%s" % (len(reqs), tid, out))
        return reqs[0]

    def records_of(self, req):
        """`records.files` of a request, [] when the request has no `records`."""
        rec = req.get("records")
        if rec is None:
            return []
        self.assertIsInstance(rec, dict, "the request's `records` is not an object: %r" % (rec,))
        return rec.get("files") or []

    def assertRecordsAreWork(self, req, touched, records):
        self.assertEqual(req.get("touched"), sorted(touched),
                         "the request's `touched` is not the task's work with its records: %r" % (req.get("touched"),))
        self.assertIn("records", req, "the request names no `records`: %s" % sorted(req))
        self.assertIsInstance(req["records"], dict, req["records"])
        self.assertEqual(req["records"].get("files"), sorted(records), req["records"])
        self.assertIn("excluded", req, sorted(req))
        self.assertEqual(req["excluded"], {"record-paths": []}, "a record the task changed is left out of its work: %r" % (req["excluded"],))


# ====================================================================== C2.1: records are work

class C2_1_RecordsAreWork(Case):

    def test_C2_1_a_no_check_task_whose_only_change_is_a_record_outside_every_scope_sends_it_as_touched(self):
        self.start()
        self.add_no_check("T")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertRecordsAreWork(self.request("T", out), [X], [X])

    def test_C2_1_a_checked_code_task_that_also_changed_a_record_sends_both_as_touched_sorted(self):
        self.start()
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        req = self.request("T", out)
        self.assertRecordsAreWork(req, [X, CODE], [X])
        self.assertEqual(req["touched"], [X, CODE], "`touched` is not sorted: %r" % req["touched"])

    def test_C2_1_a_task_scoped_on_the_record_directory_names_its_record_under_records_too(self):
        self.start()
        self.add_no_check("T", "--scope", "model")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        req = self.request("T", out)
        self.assertEqual(req.get("touched"), [X], "the fixture's ground: a record its own scope holds is already in `touched`")
        self.assertRecordsAreWork(req, [X], [X])

    def test_C2_1_two_records_of_one_task_are_listed_sorted_and_once_each(self):
        self.start()
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        self.put("model/z.json", {"z": 1})
        self.put(X, {"v": 1})
        self.put(KEPT, '{"v": 1}\n')
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        want = sorted([X, KEPT, "model/z.json"])
        req = self.request("T", out)
        self.assertRecordsAreWork(req, want + [CODE], want)
        self.assertEqual(len(req["touched"]), len(set(req["touched"])), "a file is listed twice in `touched`: %r" % req["touched"])

    def test_C2_1_a_record_committed_during_the_tasks_window_is_touched_and_under_records(self):
        self.start()
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "the session commits its work before run")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertRecordsAreWork(self.request("T", out), [X, CODE], [X])

    def test_C2_1_a_record_deleted_during_the_tasks_window_is_touched_and_under_records(self):
        self.start()
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        os.remove(os.path.join(self.dir, "model", "kept.json"))
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertRecordsAreWork(self.request("T", out), [KEPT, CODE], [KEPT])

    def test_C2_1_a_hired_build_that_wrote_code_and_a_record_sends_both_and_nothing_changed_since(self):
        self.start(roles={"implementer": self.builder(CODE, "model/own.json")})
        out = self.add_checked("build")
        self.assertIn("implementer does it", out, "the fixture's ground: the build is hired, not the session's:\n" + out)
        code, out = self.cli("run", "build")
        self.assertEqual(self.task("build").get("status"), "done", (code, out))
        req = self.request("build", out)
        self.assertRecordsAreWork(req, ["model/own.json", CODE], ["model/own.json"])
        self.assertEqual(req.get("touched_since"), [], "the builder's own record is not a change after its answer: %r" % (req.get("touched_since"),))


class C2_1_TaskWork(Case):
    """C2.1 (direct) — one engine function computes the work set the request is written from."""

    HELD = "src/held.py"

    def live(self):
        """A live run with one open task that changed a code file and a record outside every scope and holds a file already
        changed when it was added; returns the function's arguments for it."""
        self.start(files=((self.HELD, "h = 0\n"),))
        self.put(self.HELD, "h = 1\n")   # already changed when the task is added; its brief names it
        code, out = self.cli("add", "T", "--brief", "%s: finish the held change" % self.HELD, "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        d = c.run_dir(self.dir)
        plan, state = c.load_plan(d), c.load_state(d)
        tasks = [t for t in c.all_tasks(plan, state) if t.get("id") == "T"]
        self.assertEqual(len(tasks), 1, "the run has no one task T")
        self.assertIn("T", state.get("tasks") or {}, sorted(state.get("tasks") or {}))
        return plan, state, tasks[0], state["tasks"]["T"]

    def work(self):
        task_work = getattr(c, "task_work", None)
        self.assertIsNotNone(task_work, "the engine has no `task_work(target, plan, state, task, ts)`")
        self.assertTrue(callable(task_work), task_work)
        plan, state, task, ts = self.live()
        work = task_work(self.dir, plan, state, task, ts)
        self.assertIsInstance(work, dict, "task_work does not return a dict: %r" % (work,))
        for key in ("touched", "touched_since", "held-at-start", "records", "files"):
            self.assertIn(key, work, "task_work's answer has no `%s`: %s" % (key, sorted(work)))
            self.assertIsInstance(work[key], list, "`%s` is not a list: %r" % (key, work[key]))
        return work

    def test_C2_1_task_work_lists_the_record_and_files_is_the_sorted_union_of_its_parts(self):
        work = self.work()
        self.assertEqual(work["records"], [X], work)
        self.assertIn(CODE, work["touched"], work)
        self.assertNotIn(X, work["touched"], "a record outside the task's scope is in the measure itself, not added as a record: %r" % work)
        self.assertEqual(work["touched_since"], [], "a session task has no builder's answer to change after: %r" % work)
        union = set(work["touched"]) | set(work["touched_since"]) | set(work["held-at-start"]) | set(work["records"])
        self.assertEqual(work["files"], sorted(union), work)
        for path in (CODE, X, self.HELD):
            self.assertIn(path, work["files"], "%s is not among the task's work files: %r" % (path, work))

    def test_C2_1_the_request_touched_is_task_works_touched_with_its_records_added(self):
        work = self.work()
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        req = self.request("T", out)
        self.assertEqual(req.get("touched"), sorted(set(work["touched"]) | set(work["records"])), req.get("touched"))
        self.assertIn("records", req, sorted(req))
        self.assertIsInstance(req["records"], dict, req["records"])
        self.assertEqual(req["records"].get("files"), work["records"], req["records"])


# ====================================================================== C2.2: the rule

class C2_2_TheRule(Case):

    def judge(self, req):
        self.assertIn("records", req, "the request names no `records`: %s" % sorted(req))
        self.assertIsInstance(req["records"], dict, req["records"])
        self.assertTrue(req["records"].get("files"), "the fixture's ground: the task changed a record: %r" % (req["records"],))
        self.assertIn("judge", req["records"], "`records` carries no rule: %s" % sorted(req["records"]))
        judge = req["records"]["judge"]
        self.assertIsInstance(judge, str, "`records.judge` is not a sentence: %r" % (judge,))
        return judge

    def records_only(self):
        self.start()
        self.add_no_check("T")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        return self.request("T", out)

    def test_C2_2_the_rule_says_a_record_asserting_a_judgment_is_a_claim_to_check(self):
        judge = self.judge(self.records_only())
        low = judge.lower()
        for word in RULE_WORDS:
            self.assertIn(word, low, "the rule does not say `%s`: %r" % (word, judge))
        self.assertGreater(len(judge.split()), 8, "the rule is not a sentence: %r" % judge)

    def test_C2_2_the_rule_names_no_product(self):
        judge = self.judge(self.records_only())
        low = judge.lower()
        for name in PRODUCTS:
            self.assertNotIn(name, low, "the rule names a product (%s): %r" % (name, judge))

    def test_C2_2_the_rule_is_the_same_sentence_for_a_checked_code_task_and_a_hired_build(self):
        self.start(roles={"implementer": self.builder("src/b.py", "model/own.json")})
        out = self.add_checked("build")
        self.assertIn("implementer does it", out, out)
        code, out = self.cli("run", "build")
        self.assertEqual(self.task("build").get("status"), "done", (code, out))
        hired = self.judge(self.request("build", out))
        low = hired.lower()
        for word in RULE_WORDS:
            self.assertIn(word, low, "the rule sent with a hired build does not say `%s`: %r" % (word, hired))
        for name in PRODUCTS:
            self.assertNotIn(name, low, "the rule sent with a hired build names a product (%s): %r" % (name, hired))

    def test_C2_2_a_request_without_records_carries_no_rule_while_one_with_a_record_does(self):
        self.start()
        self.add_checked("R")
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "R")
        self.assertEqual(code, 0, out)
        self.assertTrue(self.judge(self.request("R", out)).strip(), "the rule is empty beside a non-empty `records.files`")
        self.add_checked("N")
        self.put("src/n.py", "n = 1\n")
        code, out = self.cli("run", "N")
        self.assertEqual(code, 0, out)
        req = self.request("N", out)
        self.assertEqual(req.get("touched"), ["src/n.py"], req.get("touched"))
        self.assertEqual(self.records_of(req), [], "a task that changed no record is sent one: %r" % (req.get("records"),))
        self.assertNotIn("judge", req.get("records") or {}, "the rule is sent with no record to judge: %r" % (req.get("records"),))


# ====================================================================== C2.3: quotes

class C2_3_Quotes(Case):

    FINDING = {"kind": "contradiction", "where": "touched", "why": "the re-read cites no comparison",
               "record_quote": STORED, "tree_quote": "…"}
    REJECT = {"artifact-type": "dwitbuk/review@1", "verdict": "reject", "findings": [FINDING], "summary": "rejected"}

    def assertRejectStands(self, code, out, tid="T"):
        self.assertEqual(len(self.seen(tid)), 1, "the verifier was not asked once:\n" + out)
        ts = self.task(tid)
        over = [o.get("finding") for o in (ts.get("overruled") or {}).get("findings") or []]
        self.assertNotIn(self.FINDING, over, "a finding that quotes what the task's record stores was overruled: %r" % (ts.get("overruled"),))
        self.assertNotIn("overruled", ts, "nothing of this review is unfounded: %r" % (ts.get("overruled"),))
        self.assertNotIn("unfounded, overruled", out, out)
        self.assertEqual(code, c.DECISION, "the reject does not stop the task for the session (exit 2):\n" + out)
        self.assertNotEqual(ts.get("status"), "done", ts.get("status"))
        self.assertEqual((ts.get("review") or {}).get("verdict"), "reject", ts.get("review"))
        self.assertEqual((ts.get("rejected") or {}).get("by"), "verifier", ts.get("rejected"))
        self.assertIn(STORED, out, "the standing finding is not printed whole:\n" + out)
        self.assertIn(self.FINDING["why"], out, out)

    def test_C2_3_a_reject_quoting_what_the_tasks_only_record_stores_stands(self):
        self.start(review=self.REJECT)
        self.add_no_check("T")
        self.put(X, {"judgment": "confirmed", "note": STORED})
        self.assertIn(STORED, open(os.path.join(self.dir, *X.split("/")), encoding="utf-8").read(),
                      "the fixture's ground: the record stores the sentence as written")
        code, out = self.cli("run", "T")
        self.assertRejectStands(code, out)

    def test_C2_3_a_reject_quoting_the_record_of_a_checked_code_task_stands(self):
        self.start(review=self.REJECT)
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        self.put(X, {"judgment": "confirmed", "note": STORED})
        code, out = self.cli("run", "T")
        self.assertRejectStands(code, out)

    def test_C2_3_a_reject_quoting_a_record_committed_in_the_window_stands(self):
        self.start(review=self.REJECT)
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        self.put(X, {"judgment": "confirmed", "note": STORED})
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "the session commits its work before run")
        code, out = self.cli("run", "T")
        self.assertRejectStands(code, out)


# ====================================================================== C2.4: unchanged

class C2_4_Unchanged(Case):

    def assertNotThisTasks(self, req, path, why):
        self.assertNotIn(path, req.get("touched") or [], "%s, yet it is in `touched`: %r" % (why, req.get("touched")))
        self.assertNotIn(path, self.records_of(req), "%s, yet it is under `records`: %r" % (why, req.get("records")))
        self.assertNotIn(path, (req.get("excluded") or {}).get("record-paths") or [], "%s, yet it is under `excluded`: %r" % (why, req.get("excluded")))

    def test_C2_4_another_open_tasks_scoped_record_is_not_this_tasks_while_its_own_is(self):
        self.start()
        self.add_no_check("S", "--scope", KEPT)   # another open task holds the one record it changes
        self.add_checked("U")
        self.put(KEPT, '{"v": 1}\n')
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "U")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("S").get("status"), "todo", "the scoped task stays open: run named U alone")
        req = self.request("U", out)
        self.assertNotThisTasks(req, KEPT, "a record under another open task's scope is not this task's")
        self.assertRecordsAreWork(req, [X, CODE], [X])

    def test_C2_4_a_record_that_already_differed_at_add_and_is_unchanged_since_is_not_this_tasks_while_its_own_is(self):
        self.start()
        self.put("model/pre.json", {"pre": 1})   # differs before the task exists; nobody touches it after
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        req = self.request("T", out)
        self.assertNotThisTasks(req, "model/pre.json", "a record that already differed, unchanged, when the task was added is not its own")
        self.assertRecordsAreWork(req, [X, CODE], [X])

    def test_C2_4_a_record_an_earlier_tasks_finish_listed_unchanged_since_is_not_a_later_tasks_while_its_own_is(self):
        self.start()
        self.add_checked("A")
        self.add_checked("B")
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "A")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("A").get("records"), [X], "the fixture's ground: the first finish lists the record")
        self.put("src/b.py", "b = 1\n")
        self.put("model/b.json", {"b": 1})
        code, out = self.cli("run", "B")
        self.assertEqual(code, 0, out)
        req = self.request("B", out)
        self.assertNotThisTasks(req, X, "a record an earlier task's finish listed, unchanged since, is not a later task's")
        self.assertRecordsAreWork(req, ["model/b.json", "src/b.py"], ["model/b.json"])

    def test_C2_4_a_hired_build_is_sent_its_own_record_and_no_other_tasks(self):
        self.start(roles={"implementer": self.builder(CODE, "model/own.json")})
        self.add_no_check("other", "--scope", KEPT)
        self.put(KEPT, '{"v": 1}\n')
        self.put("model/pre.json", {"pre": 1})
        out = self.add_checked("build")
        self.assertIn("implementer does it", out, out)
        code, out = self.cli("run", "build")
        self.assertEqual(self.task("build").get("status"), "done", (code, out))
        self.assertEqual(self.task("other").get("status"), "todo", "the scoped task stays open")
        req = self.request("build", out)
        self.assertNotThisTasks(req, KEPT, "another open task's scoped record is not this build's")
        self.assertNotThisTasks(req, "model/pre.json", "a record that already differed, unchanged, when the build started is not its own")
        self.assertRecordsAreWork(req, ["model/own.json", CODE], ["model/own.json"])

    def test_C2_4_the_task_record_keeps_its_fields_touched_without_the_record_and_records_listing_it(self):
        self.start()
        self.add_checked("T")
        self.put(CODE, "a = 1\n")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts.get("status"), "done", ts)
        self.assertEqual(ts.get("touched"), [CODE], "the task's own `touched` holds no record outside its scope: %r" % (ts.get("touched"),))
        self.assertEqual(ts.get("records"), [X], ts.get("records"))
        self.assertNotIn("nothing-to-review", ts)
        self.assertRecordsAreWork(self.request("T", out), [X, CODE], [X])

    def test_C2_4_a_no_check_task_with_only_a_record_is_still_held_unnamed_and_judged_once_named(self):
        self.start()
        self.add_no_check("T")
        self.put(X, {"v": 1})
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, "a no-check task whose only change is its own record is still held unnamed:\n" + out)
        self.assertNotEqual(self.task("T").get("status"), "done")
        self.assertEqual(self.seen(), [], "held, yet the verifier was asked")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts.get("status"), "done", ts)
        self.assertEqual(ts.get("touched"), [], "its own record is not in the task record's `touched`: %r" % (ts.get("touched"),))
        self.assertEqual(ts.get("records"), [X], ts.get("records"))
        self.assertNotIn("nothing-to-review", ts)
        self.assertRecordsAreWork(self.request("T", out), [X], [X])

    def test_C2_4_a_task_with_nothing_of_its_own_still_records_nothing_to_review_beside_one_whose_record_is_judged(self):
        self.start()
        self.put("model/pre.json", {"pre": 1})   # another record, changed before either task exists
        self.add_no_check("R")
        self.put(X, {"v": 1})
        code, out = self.cli("run", "R")
        self.assertEqual(code, 0, out)
        self.assertRecordsAreWork(self.request("R", out), [X], [X])
        self.add_no_check("N")
        code, out = self.cli("run", "N")
        self.assertEqual(code, 0, out)
        ts = self.task("N")
        self.assertEqual(ts.get("status"), "done", ts)
        self.assertIn("nothing-to-review", ts, sorted(ts))
        self.assertFalse(ts.get("records"), ts.get("records"))
        self.assertEqual(self.seen("N"), [], "nothing to read, yet the verifier was asked")


# ====================================================================== C2.5: documentation

class C2_5_Documentation(unittest.TestCase):
    """plugin/README.md, in the paragraph that describes the verifier's request."""

    def about(self):
        path = os.path.join(HERE, "plugin", "README.md")
        self.assertTrue(os.path.isfile(path), "no plugin/README.md")
        text = open(path, encoding="utf-8").read()
        about = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if "excluded.record-paths" in p and "verifier" in p]
        self.assertTrue(about, "no README paragraph describes the verifier's request and its `excluded.record-paths`")
        return about

    def test_C2_5_the_readme_says_the_tasks_records_are_in_touched_and_under_records(self):
        about = self.about()
        hits = [p for p in about if re.search(r"records?\b[^.]*\bin `touched`", p) and "`records`" in p]
        self.assertTrue(hits, "where the verifier's request is described, the task's records are not said to be in `touched` "
                              "and under `records`:\n%s" % "\n---\n".join(about))
        for p in about:
            self.assertNotIn("only its own records under `excluded.record-paths`", p,
                             "the README still says the task's records reach the verifier only as left out by rule:\n" + p)
            self.assertNotIn("excluding files already in `touched`", p,
                             "the README still says `records` leaves out the record files in `touched`:\n" + p)

    def test_C2_5_the_readme_says_excluded_record_paths_is_empty(self):
        about = self.about()
        self.assertTrue(any(re.search(r"`excluded\.record-paths`[^.]*\bempty\b", p) for p in about),
                        "`excluded.record-paths` is not said to be empty where the verifier's request is described:\n%s" % "\n---\n".join(about))

    def test_C2_5_the_readme_says_a_record_asserting_a_judgment_is_a_claim_the_verifier_checks(self):
        about = self.about()
        self.assertTrue(any(re.search(r"\bjudge?ment\b", p) and re.search(r"\bclaim\b", p) and "`records`" in p for p in about),
                        "where the verifier's request is described, a record asserting a judgment is not said to be a claim "
                        "the verifier checks:\n%s" % "\n---\n".join(about))


if __name__ == "__main__":
    unittest.main()
