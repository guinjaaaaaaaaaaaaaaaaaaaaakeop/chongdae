"""Contract R: a task the session does without a check says why, and a reader is placed by one rule.

Found in a day's runs across several projects: model tasks changed hundreds of record files as session tasks with no
check; each record said "no check decides this task; done means the agent said so", none said why no check decided it,
and none reached the declared verifier. The opposite also happened: check-only tasks whose diff was empty (a full-suite
run) were sent to the verifier, which accepted with nothing to read.

R1 — `add` of a session task with no check and no inspection is refused without `--why`; with it, the reason is recorded
as `no-check`, signed as every session judgment is. R2 — one rule places the verifier: a non-empty diff is sent, whoever
did it and with or without checks; an empty one records `nothing-to-review` and is not. R3 — the README, the run skill
and `add --help` say so.

Every test here goes through the CLI the way a session meets it: a temporary git project, fake providers that are small
scripts, no network, no model. Run with ``python3 test_task_reader.py``.
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
NON_CLAIM = "no check decides this task; done means the agent said so"
REVIEW_FINDING = {"kind": "plan-vs-code", "where": "a.py", "record_quote": "x", "tree_quote": "x = 1", "why": "a reason"}
RESPONSE_DONE = {"status": "done", "summary": "built", "verified": [], "decisions": [], "non-claims": []}
RESPONSE_BLOCKED = {"status": "blocked", "summary": "never sent", "verified": [], "decisions": [], "non-claims": []}


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True)


def prepare(pj, files=()):
    """A project with a git identity, the fakes directory ignored, and a base commit holding `files`."""
    git(pj.dir, "config", "user.email", "t@t")
    git(pj.dir, "config", "user.name", "t")
    write(os.path.join(pj.dir, ".gitignore"), "fakes/\n")
    for path, text in files:
        write(os.path.join(pj.dir, path), text)
    git(pj.dir, "add", "-A")
    git(pj.dir, "commit", "-qm", "base")


def fake_verifier(pj, verdict="accept", edit=None):
    """A verifier command: appends every request it gets to `seen.jsonl` beside the request (in the run's local/), optionally
    edits one file under the request's target once (`edit` = (path, text)), then writes a dwitbuk/review@1 verdict."""
    script = os.path.join(pj.dir, "fakes", "eyes.py")
    write(script,
          "import json, os, sys\n"
          "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
          "with open(os.path.join(os.path.dirname(sys.argv[1]), 'seen.jsonl'), 'a', encoding='utf-8') as fh:\n"
          "    fh.write(json.dumps(req) + '\\n')\n"
          "edit = json.loads(%r)\n"
          "if edit:\n"
          "    path = os.path.join(req['target'], edit[0])\n"
          "    if not os.path.exists(path) or open(path, encoding='utf-8').read() != edit[1]:\n"
          "        open(path, 'w', encoding='utf-8').write(edit[1])\n"
          "verdict = %r\n"
          "findings = [] if verdict == 'accept' else [json.loads(%r)]\n"
          "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': verdict, 'findings': findings}, open(sys.argv[2], 'w', encoding='utf-8'))\n"
          % (json.dumps(list(edit) if edit else None), verdict, json.dumps(REVIEW_FINDING)))
    return [PY, script, "{request}", "{response}"]


def fake_tests_writer(pj, test_file="test_a.py"):
    """A nitpick command: writes a test file under the request's target, then answers done naming it."""
    script = os.path.join(pj.dir, "fakes", "writer.py")
    write(script,
          "import json, os, sys\n"
          "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
          "open(os.path.join(req['target'], %r), 'w', encoding='utf-8').write('def test_x():\\n    assert False\\n')\n"
          "json.dump({'status': 'done', 'summary': 'wrote the tests', 'non-claims': [], 'tests': [%r]}, open(sys.argv[2], 'w', encoding='utf-8'))\n"
          % (test_file, test_file))
    return [PY, script, "{request}", "{response}"]


def fake_answer(pj, response, name="plain"):
    """A command provider that only writes `response` (changes nothing in the tree)."""
    script = os.path.join(pj.dir, "fakes", name + ".py")
    write(script, "import json, sys\njson.dump(json.loads(%r), open(sys.argv[2], 'w', encoding='utf-8'))\n" % json.dumps(response))
    return [PY, script, "{request}", "{response}"]


def lock(pj, roles, **more):
    write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": roles, **more})


def seen_requests(pj):
    """Every request the fake verifier was sent, in order."""
    path = os.path.join(c.run_dir(pj.dir), "local", "seen.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def verify_request(pj, tid):
    return os.path.join(c.run_dir(pj.dir), "local", "%s.verify.request.json" % tid)


def find_dict(obj, **want):
    """A dict somewhere inside `obj` whose items include `want`."""
    if isinstance(obj, dict):
        if all(obj.get(k) == v for k, v in want.items()):
            return obj
        for v in obj.values():
            hit = find_dict(v, **want)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = find_dict(v, **want)
            if hit is not None:
                return hit
    return None


def said_nothing_to_review(text):
    return re.search(r"nothing[ -]to[ -]review", text, re.IGNORECASE) is not None


class TaskReaderCase(unittest.TestCase):
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

    def task(self, tid):
        tasks = self.pj.state()["tasks"]
        self.assertIn(tid, tasks, "no task %s in the run: %s" % (tid, sorted(tasks)))
        return tasks[tid]

    def init_session(self, roles, files=(), **more):
        prepare(self.pj, files)
        lock(self.pj, roles, **more)
        code, out = self.cli("init", "--session", "--goal", "g")
        self.assertEqual(code, 0, out)


# ====================================================================== R1: `add` of a no-check session task says why

class R1_AddSaysWhy(TaskReaderCase):

    def test_R1_a_no_check_session_task_without_why_is_refused_and_nothing_is_created(self):
        """The lock declares nobody: the task is the session's own. With no --check, no --inspect and no --why it is refused —
        a non-zero exit, no task, nothing recorded — and the refusal names both ways out."""
        self.init_session({})
        code, out = self.cli("add", "T", "--brief", "a piece with no check")
        self.assertNotEqual(code, 0, "a no-check session task was added without --why:\n" + out)
        self.assertIn("--why", out, out)
        self.assertIn("chongdae add T --check", out, "the refusal gives the command that adds a check:\n" + out)
        self.assertNotIn("T", self.pj.state()["tasks"], "refused, yet the task exists")
        self.assertFalse(os.path.exists(os.path.join(c.run_dir(self.dir), "tasks", "T.json")), "refused, yet a record was written")

    def test_R1_the_refusal_gives_the_general_form_when_the_project_declares_no_check(self):
        self.init_session({})
        code, out = self.cli("add", "T", "--brief", "b")
        self.assertNotEqual(code, 0, out)
        self.assertIn('chongdae add T --check "COMMAND"', out, "the refusal's general form names the task and the --check form:\n" + out)
        self.assertIn('--why', out, out)

    def test_R1_the_refusal_carries_the_exact_offered_line_when_checks_for_covers_the_scope(self):
        """hunsu.json settings.chongdae.checks-for declares a check for the task's scope: the refusal prints the exact
        `chongdae add T --check "COMMAND"` line the offer already makes."""
        cmd = "%s check_lex.py" % shlex.quote(PY)
        self.init_session({}, files=[("check_lex.py", "pass\n"), ("lexicons/a.json", "{}\n"),
                                     ("hunsu.json", json.dumps({"settings": {"chongdae": {"checks-for": {"lexicons/": cmd}}}}))])
        offer = c.check_offer(self.dir, {"id": "T", "scope": ["lexicons"], "checks": []})
        self.assertTrue(offer and "`chongdae add T --check" in offer, "the fixture's checks-for is not offered: %r" % offer)
        line = re.search(r"`(chongdae add T --check [^`]*)`", offer).group(1)
        code, out = self.cli("add", "T", "--brief", "describe every lexicon", "--scope", "lexicons")
        self.assertNotEqual(code, 0, "a no-check session task whose scope a declared check covers was added without --why:\n" + out)
        self.assertIn(line, out, "the refusal does not carry the exact offered line %r:\n%s" % (line, out))
        self.assertNotIn("T", self.pj.state()["tasks"])

    def test_R1_1_with_why_the_task_is_added_and_no_check_is_recorded_signed_by_the_session(self):
        self.init_session({})
        code, out = self.cli("add", "T", "--brief", "b", "--why", "a decision, nothing a check can see")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts["status"], "todo")
        self.assertIn("start", ts, "added as before: a session task takes its start at add")
        self.assertIn(NON_CLAIM, ts.get("non-claims") or [], "the non-claim stays exactly as today")
        self.assertIn("no-check", ts, "the reason is not recorded on the task: %s" % sorted(ts))
        rec = ts["no-check"]
        self.assertEqual(rec.get("why"), "a decision, nothing a check can see")
        self.assertIn("at", rec)
        self.assertTrue(c.is_agent(rec.get("by")), "signed as the session, never a person: %r" % (rec.get("by"),))
        self.assertNotIn("self-performed", ts, "no role was due: nothing was taken from anyone")

    def test_R1_1_by_name_signs_the_no_check_record_with_the_person(self):
        self.init_session({})
        code, out = self.cli("add", "T", "--brief", "b", "--why", "the owner said so", "--by", "kim")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertIn("no-check", ts, sorted(ts))
        self.assertEqual(ts["no-check"].get("by"), "kim")
        self.assertEqual(ts["no-check"].get("why"), "the owner said so")

    def test_R1_2_one_why_serves_self_performed_and_no_check(self):
        """A tests task the lock gives to the nitpick, taken by the session: `--role session --why W` records self-performed
        with W, as today, and no-check with W."""
        self.init_session({"nitpick": fake_answer(self.pj, RESPONSE_BLOCKED)})
        code, out = self.cli("add", "T", "--role", "session", "--tests", "t.py", "--why", "w")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        own = ts.get("self-performed")
        self.assertIsInstance(own, dict, "self-performed as today: %s" % sorted(ts))
        self.assertEqual((own.get("instead-of"), own.get("why")), ("nitpick", "w"))
        self.assertIn("no-check", ts, "the same --why is not recorded as no-check: %s" % sorted(ts))
        self.assertEqual(ts["no-check"].get("why"), "w")
        self.assertTrue(c.is_agent(ts["no-check"].get("by")), ts["no-check"])

    def test_R1_3_a_check_task_an_inspection_a_subagent_task_and_a_nitpick_task_need_no_why_while_the_sessions_own_does(self):
        self.init_session({"implementer": fake_answer(self.pj, RESPONSE_BLOCKED, "builder"),
                           "nitpick": fake_answer(self.pj, RESPONSE_BLOCKED, "writer")})
        for argv in (("add", "A", "--check", PASS_CHECK, "--brief", "a build"),
                     ("add", "I", "--inspect", "src", "--evidence", "reviews/", "--brief", "a review"),
                     ("add", "S", "--role", "subagent", "--brief", "a sub-agent's piece"),
                     ("add", "N", "--tests", "t.py", "--brief", "the contract's tests")):
            code, out = self.cli(*argv)
            self.assertEqual(code, 0, "%s needs no --why: %s" % (argv[1], out))
            self.assertNotIn("no-check", self.task(argv[1]), "%s records no no-check" % argv[1])
        code, out = self.cli("add", "T", "--brief", "the session's own piece")
        self.assertNotEqual(code, 0, "the session's own no-check task is the one refused without --why:\n" + out)
        self.assertNotIn("T", self.pj.state()["tasks"])

    def test_R1_3_a_tests_task_chongdae_makes_for_a_dispute_records_its_own_no_check_reason(self):
        """No nitpick is declared: `dispute BUILD --tests F --why` makes a session tests task with no check. chongdae made it,
        so it carries chongdae's own reason (`by: chongdae`), not a refusal."""
        self.init_session({"implementer": fake_answer(self.pj, RESPONSE_DONE, "builder")}, files=[("test_a.py", "# the contract's test\n")])
        code, out = self.cli("add", "B", "--check", PASS_CHECK, "--tests", "test_a.py", "--brief", "a build")
        self.assertEqual(code, 0, out)
        code, out = self.cli("dispute", "B", "--tests", "test_a.py", "--why", "the fixture contradicts the contract")
        self.assertEqual(code, 0, out)
        tasks = self.pj.state()["tasks"]
        made = [tid for tid, ts in tasks.items() if tid != "B" and (ts.get("def") or {}).get("tests") == ["test_a.py"]]
        self.assertEqual(len(made), 1, "a tests task is made for the dispute: %s" % sorted(tasks))
        ts = tasks[made[0]]
        self.assertEqual(ts["def"].get("role"), "session")
        self.assertIn(NON_CLAIM, ts.get("non-claims") or [])
        self.assertIn("no-check", ts, "chongdae's own tests task records no reason: %s" % sorted(ts))
        self.assertEqual(ts["no-check"].get("by"), "chongdae")
        self.assertTrue(str(ts["no-check"].get("why") or "").strip(), ts["no-check"])

    def test_R1_4_attaching_a_check_moves_no_check_into_the_checks_added_entry(self):
        self.init_session({})
        code, out = self.cli("add", "T", "--brief", "b", "--why", "nothing to check yet")
        self.assertEqual(code, 0, out)
        code, out = self.cli("add", "T", "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertNotIn(NON_CLAIM, ts.get("non-claims") or [], "the non-claim is removed, as today")
        self.assertNotIn("no-check", ts, "the task is decided by a check now: no-check leaves the task")
        added = ts.get("checks-added") or []
        self.assertEqual(len(added), 1, ts)
        kept = find_dict(added[0], why="nothing to check yet")
        self.assertIsNotNone(kept, "the no-check record is not kept as history in the checks-added entry: %s" % added[0])
        self.assertIn("by", kept)
        self.assertIn("at", kept)

    def test_R1_5_show_prints_the_reason_who_decided_it_and_when(self):
        why = "the answer is a decision written into the plan"
        self.init_session({})
        self.assertEqual(self.cli("add", "T", "--brief", "the plan section", "--why", why)[0], 0)
        write(os.path.join(self.dir, "plan.md"), "## Q1\n")
        code, out = self.cli("run")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertIn("no-check", ts, sorted(ts))
        code, out = self.cli("show")
        self.assertEqual(code, 0, out)
        lines = [l for l in out.splitlines() if why in l]
        self.assertTrue(lines, "show does not print the no-check reason:\n" + out)
        line = lines[0]
        self.assertIn("no check", line.lower(), line)
        self.assertIn(c.signer_text(ts["no-check"].get("by")), line, "who decided it is on the line: " + line)
        # a task recorded before this contract (no `no-check`) shows as today
        self.assertEqual(self.cli("add", "P", "--brief", "an older piece", "--why", "w")[0], 0)
        write(os.path.join(self.dir, "older.md"), "x\n")
        self.assertEqual(self.cli("run")[0], 0)
        d = c.run_dir(self.dir)
        st = c.load_state(d)
        st["tasks"]["P"].pop("no-check", None)
        c.save_state(d, st)
        code, out = self.cli("show")
        self.assertEqual(code, 0, out)
        self.assertIn("\nP  done", out)

    def test_R1_5_report_gives_a_session_judged_observation_for_a_no_check_the_session_signed(self):
        self.init_session({})
        self.assertEqual(self.cli("add", "T1", "--brief", "b", "--why", "R-why: nothing a check sees")[0], 0)
        write(os.path.join(self.dir, "a1.md"), "x\n")
        self.assertEqual(self.cli("run")[0], 0)
        self.assertEqual(self.cli("add", "T2", "--brief", "b", "--why", "K-why: the owner's word", "--by", "kim")[0], 0)
        write(os.path.join(self.dir, "a2.md"), "x\n")
        self.assertEqual(self.cli("run")[0], 0)
        self.assertEqual(self.cli("close", *UNCOMMITTED)[0], 0)
        code, out = self.cli("report")
        self.assertEqual(code, 0, out)
        doc = json.loads(out)
        judged = [f for f in doc["findings"] if f.get("kind") == "session-judged"]
        mine = [f for f in judged if "R-why" in f.get("text", "")]
        self.assertTrue(mine, "no session-judged observation carries the session's no-check reason: %s" % judged)
        self.assertTrue(mine[0].get("where", "").endswith("/T1"), mine[0])
        self.assertEqual(mine[0].get("layer"), "observation", mine[0])
        self.assertIn("no check", mine[0]["text"].lower(), mine[0])
        self.assertFalse([f for f in judged if "K-why" in f.get("text", "")], "a person's --by is not a session judgment: %s" % judged)

    def test_R1_5_the_same_no_check_reason_on_three_tasks_is_one_delegation_stamp_counted_once_per_task(self):
        """Three tasks of one run with the same no-check reason are a delegation-stamp, as a repeated self-performed reason
        is; the task whose self-performed carries the same text is counted once, not twice."""
        self.init_session({"nitpick": fake_answer(self.pj, RESPONSE_BLOCKED)})
        same = "a day's repair: each piece is a decision"
        for tid, argv, path in (("T1", ("--brief", "b"), "a1.md"), ("T2", ("--brief", "b"), "a2.md"),
                                ("T3", ("--role", "session", "--tests", "t3.py"), "t3.py")):
            code, out = self.cli("add", tid, *argv, "--why", same)
            self.assertEqual(code, 0, out)
            write(os.path.join(self.dir, path), "x\n")
            code, out = self.cli("run")
            self.assertEqual(code, 0, out)
        self.assertEqual(self.cli("close", *UNCOMMITTED)[0], 0)
        code, out = self.cli("report")
        self.assertEqual(code, 0, out)
        stamps = [f for f in json.loads(out)["findings"] if f.get("kind") == "delegation-stamp" and same in f.get("text", "")]
        self.assertTrue(stamps, "the same no-check reason on three tasks is not counted as a delegation-stamp:\n" + out)
        wheres = [w.strip() for w in stamps[0].get("where", "").split(",") if w.strip()]
        self.assertEqual(sorted(w.rsplit("/", 1)[-1] for w in wheres), ["T1", "T2", "T3"], "once per task, T3 not twice: %s" % wheres)


# ====================================================================== R2: one rule places the reader

class R2_OneRulePlacesTheReader(TaskReaderCase):

    def test_R2_1_a_session_task_with_no_check_that_changes_a_file_is_sent_to_the_verifier(self):
        self.init_session({"verifier": fake_verifier(self.pj)})
        self.assertEqual(self.cli("add", "T", "--brief", "b", "--why", "no check covers a.py")[0], 0)
        write(os.path.join(self.dir, "a.py"), "x = 1\n")
        code, out = self.cli("run")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(verify_request(self.pj, "T")), "no verify request was written for the no-check session task")
        seen = seen_requests(self.pj)
        self.assertEqual(len(seen), 1, "the verifier was not asked once: %d" % len(seen))
        req = seen[0]
        self.assertEqual((req.get("stage"), req.get("task")), ("verify", "T"))
        self.assertEqual(req.get("touched"), ["a.py"])
        for key in ("contract", "tests", "built", "excluded", "since"):
            self.assertIn(key, req, "the request a task with checks gets today: %s" % sorted(req))
        ts = self.task("T")
        self.assertEqual(ts["status"], "done")
        self.assertEqual((ts.get("review") or {}).get("verdict"), "accept", ts.get("review"))
        self.assertIn("verified_by", ts, sorted(ts))
        self.assertNotIn("nothing-to-review", ts)

    def test_R2_1_a_hired_tests_task_whose_writer_changed_the_tree_is_sent_to_the_verifier(self):
        self.init_session({"nitpick": fake_tests_writer(self.pj), "verifier": fake_verifier(self.pj)})
        self.assertEqual(self.cli("add", "t", "--tests", "test_a.py", "--brief", "the contract's tests")[0], 0)
        code, out = self.cli("run")
        self.assertEqual(code, 0, out)
        ts = self.task("t")
        self.assertEqual(ts.get("touched_by_provider"), ["test_a.py"], ts.get("touched_by_provider"))
        self.assertTrue(os.path.exists(verify_request(self.pj, "t")), "the hired tests task was not sent to the verifier")
        seen = seen_requests(self.pj)
        self.assertEqual(len(seen), 1, len(seen))
        self.assertEqual(seen[0].get("touched"), ["test_a.py"])
        self.assertEqual(seen[0].get("tests"), ["test_a.py"])
        self.assertIn("verified_by", ts, sorted(ts))
        self.assertEqual((ts.get("review") or {}).get("verdict"), "accept")
        self.assertEqual(ts["status"], "done")

    def test_R2_1_a_verifier_reject_of_a_no_check_session_task_stops_for_the_session_and_the_task_stays_open(self):
        self.init_session({"verifier": fake_verifier(self.pj, verdict="reject")})
        self.assertEqual(self.cli("add", "T", "--brief", "b", "--why", "w")[0], 0)
        write(os.path.join(self.dir, "a.py"), "x = 1\n")
        code, out = self.cli("run")
        self.assertEqual(len(seen_requests(self.pj)), 1, "the verifier was not asked")
        self.assertEqual(code, c.DECISION, "a reject of a session task stops for the session (exit 2):\n" + out)
        self.assertIn("rejected", out.lower(), out)
        ts = self.task("T")
        self.assertNotEqual(ts["status"], "done", ts["status"])
        self.assertEqual((ts.get("review") or {}).get("verdict"), "reject", ts.get("review"))
        self.assertEqual((ts.get("rejected") or {}).get("by"), "verifier", ts.get("rejected"))

    def test_R2_2_a_check_task_with_an_empty_diff_is_not_sent_and_records_nothing_to_review(self):
        """A full-suite run as a task: its check passes and nothing in the tree changed in its window (a record file it wrote
        would be its own by the records rule, so none is written here). Nothing is spawned, no request is written; the
        task records nothing-to-review and `run` says so."""
        self.init_session({"verifier": fake_verifier(self.pj)})
        self.assertEqual(self.cli("add", "T", "--check", PASS_CHECK, "--brief", "the full suite")[0], 0)
        code, out = self.cli("run")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(verify_request(self.pj, "T")), "a verify request was written for an empty diff")
        self.assertEqual(seen_requests(self.pj), [], "the verifier was spawned for an empty diff")
        ts = self.task("T")
        self.assertEqual(ts["status"], "done")
        self.assertEqual(ts.get("touched"), [])
        self.assertIn("nothing-to-review", ts, sorted(ts))
        rec = ts["nothing-to-review"]
        self.assertTrue(str(rec.get("why") or "").strip(), rec)
        self.assertIn("at", rec)
        self.assertNotIn("review", ts)
        self.assertNotIn("verified_by", ts)
        self.assertTrue(said_nothing_to_review(out), "run says nothing of it:\n" + out)
        code, shown = self.cli("show")
        self.assertEqual(code, 0, shown)
        self.assertTrue(said_nothing_to_review(shown), "show says nothing of it:\n" + shown)

    def test_R2_2_a_no_check_session_task_finished_by_name_with_nothing_in_the_tree_records_nothing_to_review(self):
        self.init_session({"verifier": fake_verifier(self.pj)})
        self.assertEqual(self.cli("add", "T", "--brief", "a decision, nothing in the tree", "--why", "an answer, no file")[0], 0)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts["status"], "done")
        self.assertFalse(os.path.exists(verify_request(self.pj, "T")), "nothing to read, yet a request was written")
        self.assertEqual(seen_requests(self.pj), [])
        self.assertIn("nothing-to-review", ts, sorted(ts))
        self.assertTrue(str(ts["nothing-to-review"].get("why") or "").strip(), ts["nothing-to-review"])
        self.assertIn("at", ts["nothing-to-review"])
        self.assertTrue(said_nothing_to_review(out), out)

    def test_R2_2_a_gate_that_delegates_only_after_the_verifier_refuses_delegation_when_there_was_nothing_to_review(self):
        """A plan task with a check, done by the session, whose diff is empty: no verifier was asked, so there is no accept, and
        the `after-verifier` gate refuses `confirm --delegated`."""
        prepare(self.pj)
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "providers": {"implementer": "session", "verifier": fake_verifier(self.pj)},
                "tasks": [{"id": "S1", "role": "implementer", "gate": {"human": True, "delegate": "after-verifier"}, "checks": [[PY, "-c", "pass"]]}]}
        write(os.path.join(self.dir, "plan.json"), plan)
        code, out = self.cli("init", "--plan", os.path.join(self.dir, "plan.json"))
        self.assertEqual(code, 0, out)
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        self.assertIn("human: review", out, out)
        ts = self.task("S1")
        self.assertEqual(ts["status"], "produced")
        self.assertFalse(os.path.exists(verify_request(self.pj, "S1")), "a verify request was written for an empty diff")
        self.assertEqual(seen_requests(self.pj), [], "the verifier was spawned for an empty diff")
        self.assertIn("nothing-to-review", ts, sorted(ts))
        code, out = self.cli("confirm", "S1", "--delegated", "the owner handed the run off")
        self.assertNotEqual(code, 0, "delegated past a gate that waits for a verifier's accept, with no accept:\n" + out)
        self.assertEqual(self.task("S1")["status"], "produced")

    def test_R2_3_a_record_file_inside_the_tasks_own_scope_is_its_diff_and_reaches_the_verifier(self):
        """A task whose work is another product's records names them in --scope: inside its scope they are its work, so the
        diff is not empty and the verifier reads it."""
        self.init_session({"verifier": fake_verifier(self.pj)}, **{"record-paths": {"mangsang": ["mangsang/"]}})
        self.assertEqual(self.cli("add", "T", "--brief", "a model confirm", "--scope", "mangsang", "--why", "records, no check")[0], 0)
        write(os.path.join(self.dir, "mangsang", "scope-registered.json"), "{}\n")
        code, out = self.cli("run")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts.get("touched"), ["mangsang/scope-registered.json"], ts.get("touched"))
        self.assertTrue(os.path.exists(verify_request(self.pj, "T")), "the record change inside the task's own scope did not reach the verifier")
        seen = seen_requests(self.pj)
        self.assertEqual(len(seen), 1, len(seen))
        self.assertEqual(seen[0].get("touched"), ["mangsang/scope-registered.json"])
        self.assertNotIn("nothing-to-review", ts)

    def test_R2_4_an_inspection_is_never_sent_while_a_changing_no_check_task_is(self):
        self.init_session({"verifier": fake_verifier(self.pj)})
        self.assertEqual(self.cli("add", "I", "--inspect", "src", "--evidence", "reviews/", "--brief", "late eyes")[0], 0)
        write(os.path.join(self.dir, "reviews", "r.json"), "{}\n")
        code, out = self.cli("run", "I")
        self.assertEqual(code, 0, out)
        ts = self.task("I")
        self.assertEqual(ts["status"], "done")
        self.assertFalse(os.path.exists(verify_request(self.pj, "I")), "an inspection was sent to the verifier")
        self.assertEqual(seen_requests(self.pj), [])
        self.assertNotIn("nothing-to-review", ts, "an inspection is outside the rule: unchanged")
        self.assertNotIn("review", ts)
        # the same lock, the same run: a session task with no check that changed a file is sent
        self.assertEqual(self.cli("add", "T", "--brief", "b", "--why", "w")[0], 0)
        write(os.path.join(self.dir, "a.py"), "x = 1\n")
        code, out = self.cli("run")
        self.assertEqual(code, 0, out)
        self.assertEqual([r.get("task") for r in seen_requests(self.pj)], ["T"], "the changing no-check task was not sent")

    def test_R2_5_a_task_sent_back_by_changed_source_is_measured_again_and_then_reviewed(self):
        """nothing-to-review is recorded for the source as it was: a gated task produced on an empty diff, whose source
        changes before its confirm, goes back to todo (as today) and is measured again — now its diff is a.py, and the
        verifier is asked for the first time."""
        self.init_session({"verifier": fake_verifier(self.pj)})
        self.assertEqual(self.cli("add", "T", "--check", PASS_CHECK, "--gate", "human", "--brief", "b")[0], 0)
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        self.assertEqual(self.task("T")["status"], "produced")
        self.assertEqual(seen_requests(self.pj), [], "the verifier was asked on an empty diff")
        self.assertIn("nothing-to-review", self.task("T"), sorted(self.task("T")))
        write(os.path.join(self.dir, "a.py"), "x = 1\n")
        code, out = self.cli("confirm", "T", "--by", "kim")
        self.assertEqual(code, c.DECISION, "the produced result is not fresh: " + out)
        self.assertEqual(self.task("T")["status"], "todo")
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        seen = seen_requests(self.pj)
        self.assertEqual(len(seen), 1, "measured again with a.py changed, the task is reviewed once: %d" % len(seen))
        self.assertEqual(seen[0].get("touched"), ["a.py"])
        ts = self.task("T")
        self.assertEqual((ts.get("review") or {}).get("verdict"), "accept", ts.get("review"))
        self.assertEqual(ts["status"], "produced")

    def test_R2_5_a_no_check_task_whose_source_changes_during_review_is_asked_again(self):
        """Fresh verification as today, for a task sent under the one rule: the verifier (a fake) edits a.py while reviewing,
        so its verdict is on older source — invalidated, and the next `run T` asks again."""
        self.init_session({"verifier": fake_verifier(self.pj, edit=("a.py", "x = 2\n"))})
        self.assertEqual(self.cli("add", "T", "--brief", "b", "--why", "w")[0], 0)
        write(os.path.join(self.dir, "a.py"), "x = 1\n")
        code, out = self.cli("run")
        self.assertEqual(len(seen_requests(self.pj)), 1, "the verifier was not asked")
        self.assertEqual(code, c.WAITING, "a verdict on older source does not complete the task:\n" + out)
        ts = self.task("T")
        self.assertNotEqual(ts["status"], "done")
        self.assertTrue(ts.get("invalidated-reviews"), sorted(ts))
        self.assertNotIn("review", ts)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(seen_requests(self.pj)), 2, "fresh eyes were not asked")
        ts = self.task("T")
        self.assertEqual(ts["status"], "done")
        self.assertEqual((ts.get("review") or {}).get("verdict"), "accept")


# ====================================================================== R4: a task finished by its name says what the tree holds

R4_RECORDS = {"record-paths": {"mangsang": ["mangsang/"]}}
R4_NOTHING_WORDS = "with nothing of its own in the tree"
R4_TODAY = "T: done on the session's word by name (`run T`), with nothing of its own in the tree and no `did`"


class R4_NamedTaskSaysWhatTheTreeHolds(TaskReaderCase):

    def held_line(self, out, tid="T"):
        lines = [l for l in out.splitlines() if ("%s has changed nothing of its own" % tid) in l]
        self.assertTrue(lines, "no held line saying %s changed nothing of its own:\n%s" % (tid, out))
        return lines[0]

    def test_R4_1_an_unnamed_run_holds_the_task_and_its_held_line_names_only_its_own_records(self):
        """A record file changed before the task was added (and unchanged since) is not the task's own record: the held line
        names the record the task wrote, not every record changed in the tree."""
        self.init_session({"verifier": fake_verifier(self.pj)}, **R4_RECORDS)
        write(os.path.join(self.dir, "mangsang", "old.json"), "{}\n")
        self.assertEqual(self.cli("add", "T", "--brief", "a model confirm", "--why", "records, no check")[0], 0)
        write(os.path.join(self.dir, "mangsang", "x.json"), "{}\n")
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, "a no-check task whose only change is its own record is still held unnamed:\n" + out)
        self.assertNotEqual(self.task("T")["status"], "done")
        self.assertEqual(seen_requests(self.pj), [], "held, yet the verifier was asked")
        line = self.held_line(out)
        self.assertIn("mangsang/x.json", line, "the held line does not name the task's own record:\n" + line)
        self.assertIn("chongdae adopt T", line, "the held line lost its `adopt` line:\n" + line)
        self.assertIn("--scope", line, line)
        self.assertNotIn("mangsang/old.json", line, "the held line names a record changed before the task was added:\n" + line)
        self.assertNotIn("hunsu.lock.json", line, "the held line names a record changed before the task was added:\n" + line)

    def test_R4_2_finished_by_name_with_only_its_own_record_the_non_claim_names_it_and_the_verifier_reads_it(self):
        self.init_session({"verifier": fake_verifier(self.pj)}, **R4_RECORDS)
        write(os.path.join(self.dir, "mangsang", "old.json"), "{}\n")
        self.assertEqual(self.cli("add", "T", "--brief", "a model confirm", "--why", "records, no check")[0], 0)
        write(os.path.join(self.dir, "mangsang", "x.json"), "{}\n")
        code, out = self.cli("run")
        self.assertEqual(code, c.DECISION, out)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts["status"], "done")
        self.assertEqual(ts.get("records"), ["mangsang/x.json"], ts.get("records"))
        self.assertEqual(ts.get("touched"), [], "its own record is still nobody's work: %s" % ts.get("touched"))
        seen = seen_requests(self.pj)
        self.assertEqual([r.get("task") for r in seen], ["T"], "the verifier was not asked once for T's own diff")
        self.assertNotIn("nothing-to-review", ts)
        claims = ts.get("non-claims") or []
        said_nothing = [n for n in claims if R4_NOTHING_WORDS in n]
        self.assertEqual(said_nothing, [], "the record says the tree holds nothing of T's own while the verifier reads its diff: %s" % claims)
        by_name = [n for n in claims if "by name (`run T`)" in n]
        self.assertTrue(by_name, "no non-claim says T was done on the session's word by name: %s" % claims)
        self.assertTrue(any("mangsang/x.json" in n for n in by_name), "the by-name non-claim does not name T's own record: %s" % by_name)
        self.assertFalse(any("mangsang/old.json" in n for n in claims), "a non-claim names a record T did not write: %s" % claims)

    def test_R4_2_finished_by_name_with_a_file_its_brief_names_already_changed_at_start_the_non_claim_names_it(self):
        """A file the task's own brief names, already changed when the task was added and untouched since, is in its own
        diff: the by-name non-claim names it instead of saying the tree holds nothing of the task's own."""
        self.init_session({"verifier": fake_verifier(self.pj)}, files=[("a.py", "x = 0\n")], **R4_RECORDS)
        write(os.path.join(self.dir, "a.py"), "x = 1\n")
        self.assertEqual(self.cli("add", "T", "--brief", "decide whether a.py stays as it is", "--why", "a decision, no check")[0], 0)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts["status"], "done")
        self.assertNotIn("nothing-to-review", ts)
        claims = ts.get("non-claims") or []
        self.assertEqual([n for n in claims if R4_NOTHING_WORDS in n], [], "the tree holds a.py for T, yet: %s" % claims)
        by_name = [n for n in claims if "by name (`run T`)" in n]
        self.assertTrue(by_name, "no non-claim says T was done on the session's word by name: %s" % claims)
        self.assertTrue(any("a.py" in n for n in by_name), "the by-name non-claim does not name the held-at-start file: %s" % by_name)

    def test_R4_2_finished_by_name_with_nothing_at_all_keeps_todays_sentence_and_records_nothing_to_review(self):
        """Another record changed before the task was added is not the task's: with nothing of its own at all, the
        non-claim is today's word for word and nobody is asked to read."""
        self.init_session({"verifier": fake_verifier(self.pj)}, **R4_RECORDS)
        write(os.path.join(self.dir, "mangsang", "old.json"), "{}\n")
        self.assertEqual(self.cli("add", "T", "--brief", "a decision, nothing in the tree", "--why", "an answer, no file")[0], 0)
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts["status"], "done")
        self.assertIn(R4_TODAY, ts.get("non-claims") or [], ts.get("non-claims"))
        self.assertIn("nothing-to-review", ts, sorted(ts))
        self.assertFalse(os.path.exists(verify_request(self.pj, "T")), "nothing to read, yet a request was written")
        self.assertEqual(seen_requests(self.pj), [])
        self.assertFalse(ts.get("records"), ts.get("records"))


# ====================================================================== R3: documentation in the README's own voice

class R3_Documentation(unittest.TestCase):

    def read(self, *parts):
        with open(os.path.join(HERE, "plugin", *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_R3_the_readme_names_the_task_record_fields_no_check_and_nothing_to_review(self):
        text = self.read("README.md")
        self.assertIn("`no-check`", text, "README does not name the `no-check` task record field")
        self.assertIn("`nothing-to-review`", text, "README does not name the `nothing-to-review` task record field")

    def test_R3_the_readme_says_when_add_requires_why_and_what_the_empty_diff_does(self):
        text = self.read("README.md")
        paragraphs = [p for p in re.split(r"\n\s*\n", text)]
        why = [p for p in paragraphs if "--why" in p and "no-check" in p and re.search(r"no (`--check`|check)", p)]
        self.assertTrue(why, "no README passage says a session task with no check needs `--why` and records `no-check`")
        empty = [p for p in paragraphs if "nothing-to-review" in p and "verifier" in p and re.search(r"empty|nothing (in the tree )?changed", p)]
        self.assertTrue(empty, "no README passage on the verifier says an empty diff records `nothing-to-review` instead of a review")

    def test_R3_the_run_skill_says_a_session_task_with_no_check_needs_why(self):
        text = self.read("skills", "run", "SKILL.md")
        named = [l for l in text.splitlines() if "no check" in l and "name" in l]
        self.assertTrue(named, "the run skill no longer says a no-check session task is finished by naming it")
        self.assertTrue(any("--why" in l for l in named), "where the skill says a session task with no check is done when named, it does not say it needs --why:\n" + "\n".join(named))
        sentences = re.split(r"(?<=[.!?])\s+", text)
        yours = [s for s in sentences if "neither" in s and ("yours" in s or "session's" in s)]
        self.assertTrue(yours, "the run skill no longer says a task with neither check nor tests is the session's")
        self.assertTrue(any("--why" in s for s in yours), "the sentence giving the session a task with neither check nor tests does not say it needs --why:\n" + "\n".join(yours))

    def test_R3_add_help_says_why_is_required_for_a_session_task_with_no_check(self):
        code, out = run("add", "--help")
        self.assertEqual(code, 0, out)
        # the option's own help block (not the usage line): from `  --why WHY` to the next option
        m = re.search(r"^  --why WHY(.*?)(?=^  --)", out, re.S | re.M)
        self.assertIsNotNone(m, "add --help has no --why option:\n" + out)
        block = " ".join(m.group(1).split())
        self.assertIn("check", block, "the --why help says nothing of a task with no check: " + block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
