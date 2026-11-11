"""Contract C1: a task is held to the relations on its own work (the lock's scoped `coherence` role).

Every lock declares a `coherence` role, but it ran only in the merge plan: a task finished with the relations standing on
its own files stale, and the re-reads happened later, unreviewed, or not at all. A scoped argv — a word exactly `{files}`,
or a word containing `{base}` — now runs for every task after its own checks, on the task's work files and its start head;
a nonzero exit fails the task. An unscoped argv stays the merge run's, and the session is told tasks are not held to it.

Every test goes through the CLI the way a session meets it: a temporary git project whose hunsu.lock.json declares a
`coherence` role pointing at a fake coherence command written here (under the ignored `fakes/`), no model tool, no
network. Run with ``python3 -m unittest test_task_coherence``.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
import unittest

from test_chongdae import Project, run, write, UNCOMMITTED  # noqa: F401 — the shared fixtures
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PASS_CHECK = PY + " -c pass"

# The fake coherence command: logs its argv (after the script) as one JSON line, marks its turn in the order log, and exits 1
# naming every word it received that the control file lists as stale; else prints one line and exits 0.
FAKE_COHERENCE = r'''import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
words = sys.argv[1:]
with open(os.path.join(here, "coherence.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(words, ensure_ascii=False) + "\n")
with open(os.path.join(here, "order.log"), "a", encoding="utf-8") as fh:
    fh.write("coherence\n")
stale = set()
control = os.path.join(here, "stale.txt")
if os.path.exists(control):
    with open(control, encoding="utf-8") as fh:
        stale = {line.strip() for line in fh if line.strip()}
hit = [w for w in words if w in stale]
if hit:
    for w in hit:
        print("stale: " + w)
    sys.exit(1)
print("coherent: %d word(s) in scope" % len(words))
'''

# A task's own check: marks its turn in the same order log, so the order of the two is visible.
FAKE_OWN = r'''import os
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "order.log"), "a", encoding="utf-8") as fh:
    fh.write("own\n")
'''

# A verifier: keeps each request it is sent (one JSON line in fakes/seen.jsonl), then answers the scripted verdict for its
# n-th call (the last one repeats). A reject's finding quotes the task's own file, so it stands on its quote.
FAKE_VERIFIER = r'''import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
req = json.load(open(sys.argv[1], encoding="utf-8"))
with open(os.path.join(here, "seen.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(req, ensure_ascii=False) + "\n")
with open(os.path.join(here, "seen.jsonl"), encoding="utf-8") as fh:
    n = sum(1 for line in fh if line.strip())
verdicts = json.loads(%r)
verdict = verdicts[min(n, len(verdicts)) - 1]
finding = {"kind": "plan-vs-code", "where": "src/a.py", "record_quote": "the work of T", "tree_quote": "a = 1",
           "why": "the change does not do what the brief says"}
json.dump({"artifact-type": "dwitbuk/review@1", "verdict": verdict, "findings": [] if verdict == "accept" else [finding]},
          open(sys.argv[2], "w", encoding="utf-8"))
'''

# A builder: changes src/a.py under the request's target, counts its calls, answers done.
FAKE_BUILDER = r'''import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
req = json.load(open(sys.argv[1], encoding="utf-8"))
with open(os.path.join(here, "builder.log"), "a", encoding="utf-8") as fh:
    fh.write("built\n")
with open(os.path.join(req["target"], "src", "a.py"), "w", encoding="utf-8") as fh:
    fh.write("a = 1\n")
json.dump(json.loads(%r), open(sys.argv[2], "w", encoding="utf-8"))
'''


def git(cwd, *a):
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.pj = Project()
        self.pj.__enter__()
        self.dir = self.pj.dir
        self.addCleanup(self.pj.__exit__, None, None, None)
        user = os.environ.pop("CHONGDAE_USER", None)
        if user is not None:
            self.addCleanup(os.environ.__setitem__, "CHONGDAE_USER", user)
        self.fakes = os.path.join(self.dir, "fakes")
        self.fake = os.path.join(self.fakes, "coherence.py")
        write(self.fake, FAKE_COHERENCE)
        write(os.path.join(self.fakes, "own.py"), FAKE_OWN)

    # -- the project ----------------------------------------------------------------------------------------------------

    def scoped(self):
        return [PY, self.fake, "--files", "{files}", "--base", "{base}"]

    def prepare(self, coherence, files=(("src/a.py", "a = 0\n"),), roles=None, ignore=(), init=True, **more):
        """A project with a git identity, `fakes/` ignored, a lock declaring `coherence` (and `roles`), a base commit holding
        `files`; then a session run (its output kept as self.init_out)."""
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        write(os.path.join(self.dir, ".gitignore"), "".join(x + "\n" for x in ("fakes/",) + tuple(ignore)))
        all_roles = dict(roles or {})
        if coherence is not None:
            all_roles["coherence"] = coherence
        write(os.path.join(self.dir, "hunsu.lock.json"), {"roles": all_roles, **more})
        for path, text in files:
            write(os.path.join(self.dir, path), text)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "base")
        self.init_out = ""
        if init:
            code, out = self.cli("init", "--session", "--goal", "g")
            self.assertEqual(code, 0, out)
            self.init_out = out

    def cli(self, *argv):
        return run(*argv, "--target", self.dir)

    def put(self, path, text):
        write(os.path.join(self.dir, path), text)

    def head(self):
        return git(self.dir, "rev-parse", "HEAD").strip()

    def task(self, tid):
        tasks = self.pj.state()["tasks"]
        self.assertIn(tid, tasks, "no task %s in the run: %s" % (tid, sorted(tasks)))
        return tasks[tid]

    def add(self, tid, *more):
        code, out = self.cli("add", tid, "--brief", "the work of %s" % tid, *more)
        self.assertEqual(code, 0, out)
        return out

    def own_check(self):
        return shlex.join([PY, os.path.join(self.fakes, "own.py")])

    # -- what the fakes saw ---------------------------------------------------------------------------------------------

    def lines(self, name):
        path = os.path.join(self.fakes, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [line.rstrip("\n") for line in fh if line.strip()]

    def calls(self):
        """Every argv (after the script) the fake coherence command was run with, in order."""
        return [json.loads(line) for line in self.lines("coherence.jsonl")]

    def seen(self):
        return [json.loads(line) for line in self.lines("seen.jsonl")]

    def one_call(self, out=""):
        calls = self.calls()
        self.assertEqual(len(calls), 1, "the scoped coherence role was run %d time(s) for the task, not once: %r\n%s" % (len(calls), calls, out))
        return calls[0]

    def files_of(self, argv):
        """The words between `--files` and `--base` of a call of the scoped form."""
        self.assertIn("--files", argv, argv)
        self.assertIn("--base", argv, argv)
        i, j = argv.index("--files"), argv.index("--base")
        self.assertLess(i, j, argv)
        return argv[i + 1:j]

    def base_of(self, argv):
        self.assertIn("--base", argv, argv)
        i = argv.index("--base")
        self.assertGreater(len(argv), i + 1, argv)
        return argv[i + 1]

    def run_non_claims(self):
        nc = self.pj.state().get("non-claims") or []
        return [n if isinstance(n, str) else json.dumps(n, ensure_ascii=False) for n in nc]

    def fake_verifier(self, verdicts=("accept",)):
        script = os.path.join(self.fakes, "eyes.py")
        write(script, FAKE_VERIFIER % json.dumps(list(verdicts)))
        return [PY, script, "{request}", "{response}"]

    def fake_builder(self):
        script = os.path.join(self.fakes, "builder.py")
        response = {"status": "done", "summary": "built", "verified": [{"check": PASS_CHECK, "exit": 0}], "decisions": [], "non-claims": []}
        write(script, FAKE_BUILDER % json.dumps(response))
        return [PY, script, "{request}", "{response}"]


# ====================================================================== C1.1 / C1.2: which argvs, and when

class C1_2_When(Base):

    def test_C1_1_C1_2_a_session_task_with_a_passing_check_runs_the_scoped_role_once_after_its_own_check(self):
        self.prepare(self.scoped())
        self.add("T", "--check", self.own_check())
        head = self.head()
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)
        argv = self.one_call(out)
        self.assertEqual(self.lines("order.log"), ["own", "coherence"], "the coherence check runs after the task's own check, once")
        self.assertEqual(self.files_of(argv), ["src/a.py"], argv)
        self.assertEqual(self.base_of(argv), head, "{base} is the commit HEAD named when the task was added: %r" % argv)

    def test_C1_2_a_no_check_session_task_finished_by_name_runs_it(self):
        self.prepare(self.scoped())
        self.add("T", "--why", "the session does this itself")
        head = self.head()
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)
        argv = self.one_call(out)
        self.assertEqual(self.files_of(argv), ["src/a.py"], argv)
        self.assertEqual(self.base_of(argv), head, argv)

    def test_C1_2_a_no_check_task_held_unnamed_with_nothing_of_its_own_does_not_run_it_until_finishable(self):
        self.prepare(self.scoped())
        self.add("T", "--why", "the session does this itself")
        self.cli("run")
        self.assertEqual(self.task("T")["status"], "todo", "unnamed, with nothing of its own, the task is held")
        self.assertEqual(self.calls(), [], "a held no-check task does not run the coherence check")
        # once it is otherwise finishable, it does
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)
        self.assertEqual(self.files_of(self.one_call(out)), ["src/a.py"])

    def test_C1_2_an_inspection_never_runs_it_while_a_task_beside_it_does(self):
        self.prepare(self.scoped())
        code, out = self.cli("add", "ui-review", "--why", "a test task: no check decides it", "--inspect", "src",
                             "--evidence", "reviews/", "--brief", "a read-only review of src: write nothing, report findings")
        self.assertEqual(code, 0, out)
        # the inspection's evidence is written before the code task starts, so it is no record of that task's window
        self.put("reviews/review-1.json", json.dumps({"artifact-type": "dwitbuk/findings@1", "findings": []}))
        self.add("fix", "--check", self.own_check())
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "ui-review", "fix")
        self.assertEqual(self.task("ui-review")["status"], "done", out)
        self.assertEqual(self.task("fix")["status"], "done", out)
        argv = self.one_call(out)   # fix's, never the inspection's
        self.assertEqual(self.files_of(argv), ["src/a.py"], argv)


# ====================================================================== C1.3: {files}

class C1_3_Files(Base):

    def test_C1_3_the_files_equal_the_verifiers_work_set_records_and_deletions_included(self):
        self.prepare(self.scoped(), roles={"verifier": self.fake_verifier()},
                     files=(("src/a.py", "a = 0\n"), ("src/gone.py", "g = 0\n"), ("src/held.py", "h = 0\n"),
                            ("model/r.json", '{"v": 0}\n')),
                     **{"record-paths": {"model": ["model/"]}})
        self.put("src/held.py", "h = 1\n")   # already changed when the task is added; its brief names it
        code, out = self.cli("add", "T", "--brief", "src/held.py: finish the held change", "--check", self.own_check())
        self.assertEqual(code, 0, out)
        self.put("src/a.py", "a = 1\n")
        os.remove(os.path.join(self.dir, "src", "gone.py"))
        self.put("model/r.json", '{"v": 1}\n')   # a record outside every scope
        code, out = self.cli("run", "T")
        argv = self.one_call(out)
        reqs = self.seen()
        self.assertEqual(len(reqs), 1, "the verifier was sent %d request(s):\n%s" % (len(reqs), out))
        req = reqs[0]
        work = set(req.get("touched") or []) | set(req.get("touched_since") or []) \
            | set((req.get("attribution") or {}).get("held-at-start") or []) | set((req.get("records") or {}).get("files") or [])
        files = self.files_of(argv)
        self.assertEqual(files, sorted(work), "the coherence check's files are not the verifier's work set (request %r)" % req)
        for path in ("model/r.json", "src/gone.py", "src/held.py", "src/a.py"):
            self.assertIn(path, files, files)

    def test_C1_3_a_path_with_a_space_and_one_with_non_ascii_letters_are_each_one_word(self):
        spaced, accented = "src/my file.py", unicodedata.normalize("NFC", "src/naïve.py")
        self.prepare(self.scoped(), files=((spaced, "s = 0\n"), (accented, "n = 0\n")))
        self.add("T", "--check", self.own_check())
        self.put(spaced, "s = 1\n")
        self.put(accented, "n = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        files = [unicodedata.normalize("NFC", w) for w in self.files_of(self.one_call(out))]
        self.assertEqual(files, sorted([spaced, accented]), files)

    def test_C1_3_a_file_in_a_nested_repository_is_the_word_nested_slash_path(self):
        self.prepare(self.scoped(), ignore=("/engine/",), init=False)
        eng = os.path.join(self.dir, "engine")
        os.makedirs(eng)
        git(eng, "init", "-q")
        write(os.path.join(eng, "a.py"), "x = 0\n")
        git(eng, "add", "-A")
        git(eng, "commit", "-qm", "engine base")
        code, out = self.cli("init", "--session", "--goal", "g")
        self.assertEqual(code, 0, out)
        self.add("T", "--why", "the session does this itself")
        write(os.path.join(eng, "a.py"), "x = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.files_of(self.one_call(out)), ["engine/a.py"])

    def test_C1_3_a_did_only_task_runs_it_with_no_file_words(self):
        self.prepare(self.scoped())
        self.add("T", "--why", "an operation, nothing in the tree")
        head = self.head()
        code, out = run("did", "T", "--why", "the operation", "--target", self.dir, "--", PY, "-c", "pass")
        self.assertEqual(code, 0, out)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)
        argv = self.one_call(out)
        self.assertEqual(argv, ["--files", "--base", head], "an empty work set gives no words: %r" % argv)

    def test_C1_3_files_inside_a_larger_word_fails_the_check_naming_the_word_and_runs_nothing(self):
        self.prepare([PY, self.fake, "--files={files}", "--base", "{base}"])
        self.add("T", "--check", self.own_check())
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertNotEqual(code, 0, "a misdeclared coherence role let the task finish:\n" + out)
        self.assertNotEqual(self.task("T")["status"], "done", out)
        self.assertIn("--files={files}", out, "the failure names the misdeclared word:\n" + out)
        self.assertRegex(" ".join(out.split()), r"`?\{files\}`? must be a word of its own", out)
        self.assertEqual(self.calls(), [], "nothing is run for a misdeclared role")


# ====================================================================== C1.4: {base}

class C1_4_Base(Base):

    def test_C1_4_base_inside_a_word_becomes_the_tasks_start_head(self):
        self.prepare([PY, self.fake, "--at={base}", "--files", "{files}"])
        self.add("T", "--check", self.own_check())
        head = self.head()
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        argv = self.one_call(out)
        self.assertEqual(argv, ["--at=" + head, "--files", "src/a.py"], argv)

    def test_C1_4_a_path_containing_the_text_base_is_passed_unaltered(self):
        self.prepare(self.scoped(), files=(("{base}.txt", "0\n"),))
        self.add("T", "--check", self.own_check())
        self.put("{base}.txt", "1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.files_of(self.one_call(out)), ["{base}.txt"])


# ====================================================================== C1.5: a failure

class C1_5_Failure(Base):

    def test_C1_5_a_failing_coherence_check_stops_the_task_and_is_answered_inside_it(self):
        self.prepare(self.scoped())
        self.put("fakes/stale.txt", "src/a.py\n")
        self.add("T", "--check", self.own_check())
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, c.DECISION, out)
        self.assertEqual(self.task("T")["status"], "todo", out)
        self.assertIn("stale: src/a.py", out, "the stop shows the coherence check's output tail:\n" + out)
        said = " ".join(out.split())
        self.assertIn("relations", said, out)
        self.assertRegex(said, r"re-?read", "the stop does not say the relations owe a re-read:\n" + out)
        self.assertIn("chongdae run T", said, out)
        self.put("fakes/stale.txt", "")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)

    def test_C1_5_a_hired_builds_failing_coherence_check_stops_for_the_session_and_is_not_resent(self):
        self.prepare(self.scoped(), roles={"implementer": self.fake_builder()})
        self.put("fakes/stale.txt", "src/a.py\n")
        code, out = self.cli("add", "build", "--brief", "build it", "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        code, out = self.cli("run", "build")
        self.assertEqual(code, c.DECISION, out)
        ts = self.task("build")
        self.assertNotEqual(ts["status"], "done", out)
        self.assertGreaterEqual(len(self.calls()), 1, "the build's coherence check never ran:\n" + out)
        self.assertIn("stale: src/a.py", out, out)
        self.assertEqual(len(self.lines("builder.log")), 1, "the builder was sent the work again:\n" + out)
        autos = [a for a in ts.get("attempts") or [] if (a.get("retried") or {}).get("auto")]
        self.assertEqual(autos, [], "a failed coherence check is not resent to the builder")


# ====================================================================== C1.6: a pass is evidence

class C1_6_Evidence(Base):

    def coherence_record(self, tid, head):
        ts = self.task(tid)
        self.assertIn("checks-passed", ts, sorted(ts))
        hits = [r for r in ts["checks-passed"].get("ran") or [] if "coherence.py" in str(r.get("command"))]
        self.assertEqual(len(hits), 1, "checks-passed.ran keeps no coherence record: %r" % ts["checks-passed"])
        return hits[0]

    def test_C1_6_a_pass_is_kept_with_the_checks_and_reaches_the_verifier_under_checked(self):
        self.prepare(self.scoped(), roles={"verifier": self.fake_verifier()})
        self.add("T", "--check", self.own_check())
        head = self.head()
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.one_call(out)
        rec = self.coherence_record("T", head)
        self.assertIn("src/a.py", rec["command"], rec)
        self.assertIn(head, rec["command"], rec)
        self.assertNotIn("{files}", rec["command"], rec)
        self.assertNotIn("{base}", rec["command"], rec)
        reqs = self.seen()
        self.assertEqual(len(reqs), 1, out)
        checked = [e for e in reqs[0].get("checked") or [] if "coherence.py" in str(e.get("command") if isinstance(e, dict) else e)]
        self.assertEqual(len(checked), 1, "the verifier's request does not carry the coherence check under checked: %r" % reqs[0].get("checked"))
        cmd = checked[0]["command"] if isinstance(checked[0], dict) else checked[0]
        self.assertIn("src/a.py", cmd)
        self.assertIn(head, cmd)

    def test_C1_6_deciding_again_on_an_identical_tree_reuses_the_coherence_pass(self):
        self.prepare(self.scoped(), roles={"verifier": self.fake_verifier(("reject", "accept"))})
        self.add("T", "--check", self.own_check())
        head = self.head()
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(len(self.seen()), 1, "the verifier was not asked:\n" + out)
        self.assertNotEqual(self.task("T")["status"], "done", "the verifier rejected:\n" + out)
        self.one_call(out)
        code, out = self.cli("retry", "T")
        self.assertEqual(code, 0, out)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)
        self.assertEqual(len(self.calls()), 1, "the coherence check ran again on an identical tree:\n" + out)
        self.assertIn("reused", self.coherence_record("T", head), "the second decision's coherence pass is not recorded as reused")


# ====================================================================== C1.7: an unscoped argv

def says_unscoped(line):
    return "coherence" in line and "unscoped" in line and "not held" in line


class C1_7_Unscoped(Base):

    def test_C1_7_an_unscoped_role_is_never_run_for_a_task_and_the_session_is_told_once(self):
        self.prepare([PY, self.fake])
        code, first_add = self.cli("add", "T1", "--brief", "one", "--check", self.own_check())
        self.assertEqual(code, 0, first_add)
        told = [l for l in (self.init_out + first_add).splitlines() if says_unscoped(l)]
        self.assertEqual(len(told), 1, "init/the first add does not say once that the coherence role is unscoped and tasks are not held to it:\n%s%s"
                         % (self.init_out, first_add))
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T1")
        self.assertEqual(code, 0, out)
        self.add("T2", "--check", self.own_check())
        self.put("src/b.py", "b = 1\n")
        code, out = self.cli("run", "T2")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), [], "an unscoped coherence argv was run for a task")
        said = [n for n in self.run_non_claims() if says_unscoped(n)]
        self.assertEqual(len(said), 1, "the run carries the unscoped non-claim %d time(s): %r" % (len(said), self.run_non_claims()))
        plan = c.merge_plan(self.dir, self.head())
        self.assertIn([PY, self.fake], plan["tasks"][0]["checks"], "the merge plan keeps the unscoped argv as today")

    def test_C1_7_a_mixed_list_runs_only_the_scoped_argv_and_the_non_claim_names_the_unscoped(self):
        self.prepare([self.scoped(), [PY, self.fake, "--whole"]])
        self.add("T", "--check", self.own_check())
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        argv = self.one_call(out)
        self.assertNotIn("--whole", argv, "the unscoped argv was run for a task")
        self.assertEqual(self.files_of(argv), ["src/a.py"])
        said = [n for n in self.run_non_claims() if says_unscoped(n)]
        self.assertEqual(len(said), 1, self.run_non_claims())
        self.assertIn("--whole", said[0], "the non-claim does not name the unscoped argv: %r" % said[0])


# ====================================================================== C1.8: the merge plan

class C1_8_MergePlan(Base):

    def test_C1_8_files_in_the_merge_plan_are_the_files_the_merge_brought_in(self):
        self.prepare([PY, self.fake, "--at", "{base}"], files=(("x.py", "x = 0\n"), ("y.py", "y = 0\n")), init=False)
        base = self.head()
        merge_plan = getattr(c, "merge_plan", None)
        self.assertTrue(callable(merge_plan), "chongdae.merge_plan is gone")
        # an argv with only {base}: as today
        plan = merge_plan(self.dir, base)
        self.assertIn([PY, self.fake, "--at", base], plan["tasks"][0]["checks"], plan["tasks"][0]["checks"])
        # an argv with {files}: the files that differ between the merge base and the merged tree, both sides of a rename
        self.put("x.py", "x = 1\n")
        git(self.dir, "mv", "y.py", "z.py")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "the merged work")
        self.put("hunsu.lock.json", json.dumps({"roles": {"coherence": self.scoped()}}))
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "the scoped role")
        plan = merge_plan(self.dir, base)
        checks = [ck for ck in plan["tasks"][0]["checks"] if self.fake in ck]
        self.assertEqual(len(checks), 1, plan["tasks"][0]["checks"])
        words = checks[0]
        self.assertNotIn("{files}", words, "a literal {files} reached the merge's check: %r" % words)
        for path in ("x.py", "y.py", "z.py"):
            self.assertIn(path, words, words)
        self.assertEqual(self.base_of(words), base, words)


# ====================================================================== C1.10: unchanged

class C1_10_Unchanged(Base):

    def test_C1_10_recheck_reruns_the_tasks_own_checks_not_its_coherence(self):
        self.prepare(self.scoped())
        self.add("T", "--check", self.own_check())
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.one_call(out)
        self.assertEqual(self.task("T")["def"]["checks"], [shlex.split(self.own_check())], "task.checks holds no coherence argv")
        # recheck looks only at runs that ended: close the session run first
        code, out = run("close", *UNCOMMITTED, "--target", self.dir)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lines("order.log"), ["own", "coherence"], "closing the run runs neither check again:\n" + out)
        code, out = self.cli("recheck")
        self.assertEqual(code, 0, out)
        self.assertIn("still green", out)
        self.assertEqual(self.lines("order.log"), ["own", "coherence", "own"], "recheck reruns the own check, not the coherence check:\n" + out)
        self.assertEqual(len(self.calls()), 1, out)


# ====================================================================== C1.11: the documentation says so

def paragraphs(path):
    with open(os.path.join(HERE, path), encoding="utf-8") as fh:
        text = fh.read()
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


class C1_11_Docs(unittest.TestCase):

    def test_C1_11_readme_names_files_and_base_where_a_tasks_coherence_check_is_described(self):
        paras = paragraphs(os.path.join("plugin", "README.md"))
        about = [p for p in paras if "coherence" in p and "{files}" in p and "{base}" in p and re.search(r"\btasks?\b", p)]
        self.assertTrue(about, "no README paragraph describes a task's coherence check with `{files}` and `{base}`")
        unscoped = [p for p in paras if "coherence" in p and "unscoped" in p and re.search(r"\btasks?\b", p)]
        self.assertTrue(unscoped, "no README paragraph says an unscoped coherence role is not run for tasks")

    def test_C1_11_run_skill_says_a_failed_coherence_check_is_answered_inside_the_task(self):
        paras = paragraphs(os.path.join("plugin", "skills", "run", "SKILL.md"))
        about = [p for p in paras if "coherence" in p and re.search(r"re-?read", p) and re.search(r"\b(inside|in) (the|that|this) task\b", p)]
        self.assertTrue(about, "the run skill does not say a failed coherence check is answered inside the task by re-reading the relations")


# ====================================================================== C3: the notice and the merge plan's {files}

UNKNOWN_BASE = "0123456789abcdef0123456789abcdef01234567"   # well-formed, and no commit of the test project


class C3_NoRewriteNoVacuum(Base):
    """Contract C3: the unscoped-coherence notice never writes into a run that is not running and says what it means; the
    merge plan refuses a `{files}` it cannot substitute instead of raising or passing an empty list."""

    def state_path(self):
        return os.path.join(c.run_dir(self.dir), "state.json")

    def runs(self):
        root = os.path.join(self.dir, ".chongdae")
        return sorted(n for n in (os.listdir(root) if os.path.isdir(root) else []) if n.startswith("run-"))

    def notices(self):
        """The run's non-claims about the lock's coherence role (a leading clause of LOCK_STANDING, about coherence)."""
        standing = getattr(c, "LOCK_STANDING", None)
        self.assertIsInstance(standing, tuple, "chongdae.LOCK_STANDING is gone")
        return [n for n in self.run_non_claims() if "coherence" in n and n.startswith(standing)]

    def init_merge(self, base):
        """`init --merge --base BASE` through the CLI: (code, stdout + stderr). Any exception other than the CLI's own exit
        is a failure of the test, not an error."""
        import contextlib
        import io
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                code, out = self.cli("init", "--merge", "--base", base)
        except Exception as exc:   # noqa: BLE001 — the contract: a usage message, never a traceback
            self.fail("`init --merge` raised %s out of the CLI instead of refusing with a usage message: %s" % (type(exc).__name__, exc))
        return code, out + err.getvalue()

    # -- C3.1 ---------------------------------------------------------------------------------------------------------

    def test_C3_1_run_and_add_against_a_closed_run_leave_its_state_byte_for_byte(self):
        self.prepare([PY, self.fake])
        self.add("T", "--check", self.own_check())
        self.put("src/a.py", "a = 1\n")
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)
        code, out = run("close", *UNCOMMITTED, "--target", self.dir)
        self.assertEqual(code, 0, out)
        self.assertNotEqual(self.pj.state().get("status"), "running", "the run is not closed:\n" + out)
        path = self.state_path()
        with open(path, "rb") as fh:
            before = fh.read()
        claims = self.run_non_claims()
        runs = self.runs()

        _, out = self.cli("run")
        with open(path, "rb") as fh:
            after_run = fh.read()
        self.assertEqual(self.run_non_claims(), claims, "`run` against a closed run added a non-claim to its record:\n" + out)
        self.assertEqual(after_run, before, "`run` against a closed run rewrote its state.json:\n" + out)

        code, out = self.cli("add", "X", "--brief", "b", "--why", "w")
        self.assertNotEqual(code, 0, "`add` against a closed run is refused as before:\n" + out)
        with open(path, "rb") as fh:
            after_add = fh.read()
        self.assertEqual(self.run_non_claims(), claims, "`add` against a closed run added a non-claim to its record:\n" + out)
        self.assertEqual(after_add, before, "`add` against a closed run rewrote its state.json:\n" + out)
        self.assertNotIn("X", self.pj.state().get("tasks") or {}, "the refused task reached the closed run")
        self.assertEqual(self.runs(), runs, "neither call starts a run of its own")

    # -- C3.2 ---------------------------------------------------------------------------------------------------------

    def test_C3_2_the_notice_names_the_argv_both_placeholders_that_no_task_is_held_and_that_a_merge_run_runs_it(self):
        self.prepare([PY, self.fake, "--whole-model"])
        said = self.notices()
        self.assertEqual(len(said), 1, "init of a session run records the unscoped-coherence non-claim %d time(s), under a leading "
                         "clause of LOCK_STANDING: %r" % (len(said), self.run_non_claims()))
        notice = said[0]
        self.assertIn("--whole-model", notice, "the notice does not name the unscoped argv")
        self.assertIn(os.path.basename(self.fake), notice, "the notice does not name the unscoped argv")
        self.assertIn("{files}", notice, "the notice does not say the argv names no `{files}`")
        self.assertIn("{base}", notice, "the notice does not say the argv names no `{base}`")
        self.assertRegex(notice, r"\bneither\b|\bno\b|\bnot\b|\bwithout\b", "the notice does not say the placeholders are absent")
        self.assertRegex(notice, r"\bheld\b", "the notice does not say no task of the run is held to the argv")
        self.assertRegex(notice, r"\btasks?\b", "the notice does not say no task of the run is held to the argv")
        self.assertRegex(notice, r"\bmerge\b", "the notice does not say only a merge run runs the argv")
        told = [l for l in self.init_out.splitlines() if "--whole-model" in l and "{files}" in l]
        self.assertTrue(told, "the non-claim is printed when it is recorded:\n" + self.init_out)

    def test_C3_2_a_mixed_list_names_only_the_unscoped_argv_in_the_notice(self):
        self.prepare([self.scoped(), [PY, self.fake, "--whole-model"]])
        said = self.notices()
        self.assertEqual(len(said), 1, self.run_non_claims())
        notice = said[0]
        self.assertIn("--whole-model", notice, "the notice does not name the unscoped argv")
        for word in ("{files}", "{base}"):
            self.assertIn(word, notice, "the notice does not say the unscoped argv names no `%s`" % word)
        self.assertRegex(notice, r"\bheld\b")
        self.assertRegex(notice, r"\bmerge\b", "the notice does not say only a merge run runs the argv")
        self.assertNotIn("--files", notice, "the notice names the scoped argv, which tasks are held to")

    def test_C3_2_the_reworded_notice_is_not_printed_again_at_the_close_of_the_next_run(self):
        self.prepare([PY, self.fake, "--whole-model"])
        said = self.notices()
        self.assertEqual(len(said), 1, self.run_non_claims())
        notice = said[0]
        self.assertRegex(notice, r"\bmerge\b", "the notice does not say only a merge run runs the argv")
        self.assertIn("{files}", notice)
        code, out = run("close", *UNCOMMITTED, "--target", self.dir)
        self.assertEqual(code, 0, out)
        code, out = self.cli("init", "--session", "--goal", "the next run")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.notices(), [notice], "the next run carries the same notice, once")
        code, out = run("close", *UNCOMMITTED, "--target", self.dir)
        self.assertEqual(code, 0, out)
        self.assertNotIn(notice, out, "the close of a run prints the lock's standing notice again although the run that ended before carried it")

    # -- C3.3 ---------------------------------------------------------------------------------------------------------

    def test_C3_3_files_inside_a_larger_word_is_refused_with_a_usage_message_and_no_run(self):
        self.prepare([PY, self.fake, "--files={files}"], init=False)
        self.assertEqual(self.runs(), [])
        code, out = self.init_merge(self.head())
        self.assertNotEqual(code, 0, "`init --merge` accepted a coherence argv holding `{files}` inside a word:\n" + out)
        self.assertIn("--files={files}", out, "the refusal does not name the misdeclared word")
        self.assertNotIn("Traceback", out, "a traceback, not a usage message")
        self.assertEqual(self.runs(), [], "the refused `init --merge` left a run behind")
        self.assertEqual(self.calls(), [], "nothing is run for a misdeclared role")

    def test_C3_3_files_inside_a_larger_word_beside_a_sound_argv_is_still_refused(self):
        self.prepare([self.scoped(), [PY, self.fake, "x{files}y"]], init=False)
        code, out = self.init_merge(self.head())
        self.assertNotEqual(code, 0, "`init --merge` accepted a coherence argv holding `{files}` inside a word:\n" + out)
        self.assertIn("x{files}y", out, "the refusal does not name the misdeclared word")
        self.assertNotIn("Traceback", out)
        self.assertEqual(self.runs(), [], "the refused `init --merge` left a run behind")

    def test_C3_3_an_unlistable_base_is_refused_not_given_an_empty_file_list(self):
        # an argv without {files}: as before, whatever the base
        self.prepare([PY, self.fake, "--at", "{base}"], init=False)
        merge_plan = getattr(c, "merge_plan", None)
        self.assertTrue(callable(merge_plan), "chongdae.merge_plan is gone")
        try:
            plan = merge_plan(self.dir, UNKNOWN_BASE)
        except (Exception, SystemExit) as exc:   # noqa: BLE001
            self.fail("merge_plan no longer builds the plan for an argv without `{files}` on an unknown base: %s: %s" % (type(exc).__name__, exc))
        self.assertIn([PY, self.fake, "--at", UNKNOWN_BASE], plan["tasks"][0]["checks"], plan["tasks"][0]["checks"])
        # an argv with {files}: git cannot list what differs from a commit it does not have
        self.put("hunsu.lock.json", json.dumps({"roles": {"coherence": [PY, self.fake, "--files", "{files}"]}}))
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "the scoped role")
        code, out = self.init_merge(UNKNOWN_BASE)
        self.assertNotEqual(code, 0, "`init --merge` on a base git cannot list files from went on with an empty file list:\n" + out)
        self.assertNotIn("Traceback", out)
        self.assertIn("git", out, "the refusal does not say git could not list the files")
        self.assertRegex(out, r"could not|cannot|can't|unable", "the refusal does not say git could not list the files:\n" + out)
        self.assertRegex(out, r"\bfiles\b", "the refusal does not say what could not be listed:\n" + out)
        self.assertRegex(out, r"0123456789abcdef|\bbase\b", "the refusal does not name the base:\n" + out)
        self.assertEqual(self.runs(), [], "the refused `init --merge` left a run behind")
        self.assertEqual(self.calls(), [], "the scoped check was run on a list git could not give")


# ====================================================================== C4: paths as they are

class C4_PathsAsTheyAre(Base):
    """Contract C4: the words a `{files}` expansion inserts reach the coherence command exactly as the work set has them (no
    `{plugin:NAME}` replacement, no `~` expansion, wherever the declared words are resolved), and the merge plan names the
    files relative to the project directory, as a task does."""

    def guarded(self, *argv):
        """A CLI call whose exception (other than the CLI's own exit) is a failure of the test, not an error."""
        try:
            return self.cli(*argv)
        except Exception as exc:   # noqa: BLE001
            self.fail("`chongdae %s` raised %s out of the CLI: %s" % (" ".join(argv), type(exc).__name__, exc))

    def decide(self, paths, roles=None, fake_dir=None, coherence=None):
        """A task T that changes every one of `paths` (each committed at the base), decided once: (code, out)."""
        self.prepare(coherence or self.scoped(), files=tuple((p, "old\n") for p in paths) + (("src/a.py", "a = 0\n"),), roles=roles)
        self.add("T", "--check", self.own_check())
        for p in paths:
            self.put(p, "new\n")
        self.put("src/a.py", "a = 1\n")
        return self.guarded("run", "T")

    def as_they_are(self, paths, out):
        """The fake ran once, the words after --files are `paths` and src/a.py, sorted, and the task finished."""
        argv = self.one_call(out)
        self.assertEqual(self.files_of(argv), sorted(list(paths) + ["src/a.py"]),
                         "the work files did not reach the coherence command as they are: %r\n%s" % (argv, out))
        self.assertEqual(self.task("T")["status"], "done", out)

    def recorded_words(self, tid="T"):
        """The words of the one coherence command kept in the task's checks-passed.ran, and the record itself."""
        ts = self.task(tid)
        self.assertIn("checks-passed", ts, "the task keeps no passed checks: %s" % sorted(ts))
        ran = ts["checks-passed"].get("ran") or []
        hits = [r for r in ran if isinstance(r, dict) and "coherence.py" in str(r.get("command"))]
        self.assertEqual(len(hits), 1, "checks-passed.ran keeps no coherence record: %r" % ran)
        command = hits[0].get("command")
        self.assertIsInstance(command, str, hits[0])
        try:
            return shlex.split(command), hits[0]
        except ValueError as exc:
            self.fail("the recorded coherence command is not a shell line: %r (%s)" % (command, exc))

    # -- C4.1 ---------------------------------------------------------------------------------------------------------

    def test_C4_1_a_plugin_placeholder_name_and_a_tilde_directory_reach_the_command_and_the_record_as_they_are(self):
        paths = ["{plugin:nothere}.txt", "~/note.txt"]
        code, out = self.decide(paths)
        self.assertEqual(code, 0, "a task whose file is named after an undeclared plugin did not finish:\n" + out)
        self.as_they_are(paths, out)
        words, rec = self.recorded_words()
        for p in paths:
            self.assertIn(p, words, "the recorded command does not name %r as it is: %r" % (p, rec))
        self.assertNotIn(os.path.expanduser("~/note.txt"), words, rec)

    def test_C4_1_a_file_named_after_a_plugin_that_is_not_installed_reaches_the_command_and_the_check_runs(self):
        paths = ["{plugin:mangsang}.txt"]
        code, out = self.decide(paths)
        self.assertEqual(len(self.calls()), 1, "the coherence check did not run for a file named after a plugin that is not installed:\n" + out)
        self.assertEqual(code, 0, out)
        self.as_they_are(paths, out)
        words, rec = self.recorded_words()
        self.assertIn(paths[0], words, rec)

    def test_C4_1_a_file_under_a_directory_named_tilde_is_not_a_home_path(self):
        paths = ["~/note.txt"]
        code, out = self.decide(paths)
        self.assertEqual(code, 0, out)
        argv = self.one_call(out)
        self.assertNotIn(os.path.expanduser("~/note.txt"), argv, "the project's own ~/note.txt reached the command as a home path")
        self.as_they_are(paths, out)
        words, rec = self.recorded_words()
        self.assertIn("~/note.txt", words, rec)

    def test_C4_1_a_file_named_tilde_alone_is_one_word_as_it_is(self):
        paths = ["~"]
        code, out = self.decide(paths)
        self.assertEqual(code, 0, out)
        self.as_they_are(paths, out)
        words, rec = self.recorded_words()
        self.assertIn("~", words, rec)

    def test_C4_1_a_nested_path_holding_a_plugin_placeholder_keeps_its_text(self):
        paths = ["docs/{plugin:nothere}/notes ~/a.txt"]
        code, out = self.decide(paths)
        self.assertEqual(code, 0, out)
        self.as_they_are(paths, out)
        words, rec = self.recorded_words()
        self.assertIn(paths[0], words, rec)

    def test_C4_1_the_declared_words_keep_their_home_resolution_while_the_file_words_are_not_resolved(self):
        # the role is declared with a leading `~/` word (resolved as before); the task's file under a literal `~` directory is not
        import tempfile
        import shutil
        home = tempfile.mkdtemp(prefix="chongdae-test-home-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("HOME")
        self.addCleanup(lambda: os.environ.pop("HOME", None) if old is None else os.environ.__setitem__("HOME", old))
        os.environ["HOME"] = home
        write(os.path.join(home, "cfake", "coherence.py"), FAKE_COHERENCE)
        code, out = self.decide(["~/note.txt"], coherence=[PY, "~/cfake/coherence.py", "--files", "{files}", "--base", "{base}"])
        log = os.path.join(home, "cfake", "coherence.jsonl")
        self.assertTrue(os.path.exists(log), "the declared word `~/cfake/coherence.py` was not resolved to the home path, so the check never ran:\n" + out)
        with open(log, encoding="utf-8") as fh:
            calls = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(self.files_of(calls[0]), ["src/a.py", "~/note.txt"],
                         "a declared `~/` word is resolved; a file word is not: %r" % calls[0])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)

    def test_C4_1_the_identical_tree_reuse_keeps_the_paths_as_they_are(self):
        paths = ["~/note.txt"]
        code, out = self.decide(paths, roles={"verifier": self.fake_verifier(("reject", "accept"))})
        self.assertEqual(len(self.seen()), 1, "the verifier was not asked:\n" + out)
        self.as_they_are_call_only(paths, out)
        code, out = self.guarded("retry", "T")
        self.assertEqual(code, 0, out)
        code, out = self.guarded("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T")["status"], "done", out)
        self.assertEqual(len(self.calls()), 1, "the coherence check ran again on an identical tree:\n" + out)
        words, rec = self.recorded_words()
        self.assertIn("reused", rec, "the second decision's coherence pass is not recorded as reused: %r" % rec)
        self.assertIn("~/note.txt", words, "the reused record does not keep the path as it is: %r" % rec)
        reqs = self.seen()
        self.assertEqual(len(reqs), 2, out)
        checked = [e.get("command") if isinstance(e, dict) else e for e in reqs[-1].get("checked") or []]
        checked = [cmd for cmd in checked if "coherence.py" in str(cmd)]
        self.assertEqual(len(checked), 1, reqs[-1].get("checked"))
        self.assertIn("~/note.txt", shlex.split(checked[0]), "the verifier is shown an altered path: %r" % checked[0])

    def as_they_are_call_only(self, paths, out):
        argv = self.one_call(out)
        self.assertEqual(self.files_of(argv), sorted(list(paths) + ["src/a.py"]), "%r\n%s" % (argv, out))

    # -- C4.2 ---------------------------------------------------------------------------------------------------------

    def merge_checks(self, project, base):
        merge_plan = getattr(c, "merge_plan", None)
        self.assertTrue(callable(merge_plan), "chongdae.merge_plan is gone")
        try:
            plan = merge_plan(project, base)
        except (Exception, SystemExit) as exc:   # noqa: BLE001
            self.fail("merge_plan did not build the plan: %s: %s" % (type(exc).__name__, exc))
        checks = [ck for ck in plan["tasks"][0]["checks"] if self.fake in ck]
        self.assertEqual(len(checks), 1, plan["tasks"][0]["checks"])
        return checks[0]

    def merged_work(self, project):
        """In `project` (inside the repository at self.dir): the scoped role, x.py and y.py committed as the base; then x.py
        changed and y.py renamed to z.py, committed. Returns the base."""
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        write(os.path.join(self.dir, ".gitignore"), "fakes/\n")
        write(os.path.join(project, "hunsu.lock.json"), {"roles": {"coherence": self.scoped()}})
        write(os.path.join(project, "x.py"), "x = 0\n")
        write(os.path.join(project, "y.py"), "y = 0\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "base")
        base = self.head()
        write(os.path.join(project, "x.py"), "x = 1\n")
        git(project, "mv", "y.py", "z.py")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "the merged work")
        return base

    def test_C4_2_a_project_in_a_subdirectory_of_its_repository_gets_project_relative_files(self):
        project = os.path.join(self.dir, "proj")
        base = self.merged_work(project)
        words = self.merge_checks(project, base)
        self.assertNotIn("{files}", words, words)
        self.assertEqual(self.base_of(words), base, words)
        self.assertEqual(self.files_of(words), ["x.py", "y.py", "z.py"],
                         "the merge's files are not named relative to the project directory, as its tasks name them: %r" % words)
        for w in words:
            self.assertFalse(w.startswith("proj/"), "a repository-relative path reached the project's check: %r" % words)

    def test_C4_2_a_file_outside_the_project_is_not_a_word_and_a_nested_one_keeps_its_project_relative_path(self):
        project = os.path.join(self.dir, "proj")
        write(os.path.join(self.dir, "other", "o.py"), "o = 0\n")
        write(os.path.join(project, "deep", "d.py"), "d = 0\n")
        base = self.merged_work(project)
        write(os.path.join(self.dir, "other", "o.py"), "o = 1\n")
        write(os.path.join(project, "deep", "d.py"), "d = 1\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "more merged work, inside and beside the project")
        words = self.merge_checks(project, base)
        self.assertEqual(self.files_of(words), ["deep/d.py", "x.py", "y.py", "z.py"], words)

    def test_C4_2_at_the_repository_root_the_words_are_unchanged_and_a_subdirectory_names_the_same_files(self):
        # the project at the repository root: as before
        base = self.merged_work(self.dir)
        root_words = self.merge_checks(self.dir, base)
        self.assertEqual(self.files_of(root_words), ["x.py", "y.py", "z.py"], root_words)
        self.assertEqual(self.base_of(root_words), base, root_words)
        # the same work one directory down, in a repository of its own: the same words
        import tempfile
        import shutil
        other = tempfile.mkdtemp(prefix="chongdae-test-")
        self.addCleanup(shutil.rmtree, other, True)
        subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        root, self.dir = self.dir, other
        try:
            sub_base = self.merged_work(os.path.join(other, "proj"))
        finally:
            self.dir = root
        sub_words = self.merge_checks(os.path.join(other, "proj"), sub_base)
        self.assertEqual(self.files_of(sub_words), self.files_of(root_words),
                         "a project in a subdirectory names its merge's files differently from one at the root: %r" % sub_words)


if __name__ == "__main__":
    unittest.main(verbosity=2)
