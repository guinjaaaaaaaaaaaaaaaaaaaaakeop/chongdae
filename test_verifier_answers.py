"""Contract V: what the verifier answered is read as it was meant.

Found in a sibling project's day of real work. (a) A verifier rejected a build with one grounded finding whose record quote
was a sentence of a plan file of about 200 KB named in its `where`; its runner read only files under 200000 bytes, dropped the
finding as "nowhere in the request", and saved `verdict: accept, findings: []` with the finding under `unfounded`. chongdae
printed one line, recorded nothing, and `close` said no non-claims; chongdae's own grounding has the same size limit. (b) A
valid finding whose backticked quote held an elision was dropped. (c) A verifier that accepted without opening a required
file was reported as "did not answer — fix the verifier", and `retry` then refused.

V1 — chongdae never judges a quote unfounded because a file was not read: files are read whole, a file that cannot be read
leaves the finding standing with a non-claim, a backticked quote with an elision is matched piecewise. V2 — a finding the
verifier's runner dropped is weighed again: reinstated when its quote is found, otherwise a drop that turned a reject into an
accept is a non-claim `close` lists. V3 — an accept without reading is said as what it is and asked again with `chongdae run`.
V4 — the README and the run skill say so.

Every test goes through the CLI the way a session meets it: a temporary git project, a session run, a session task with a
check that passes, the lock's verifier a small fake script answering a scripted dwitbuk/review@1. No network, no model.

  python3 -m unittest test_verifier_answers
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import shutil
import unittest

from test_chongdae import Project, run, write, UNCOMMITTED
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PASS_CHECK = PY + " -c pass"
BRIEF = "keep the settled entries"

# a sentence only the plan file holds (never in the brief, the contract or anything else the request carries)
SENTENCE = "The ledger keeps every settled entry for exactly seven years."
NOWHERE = "Every invoice is archived to cold storage on the first Monday."
FILLER = "a line of the plan that says nothing in particular about it\n"


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True)


def big_plan(size=210000, sentence=SENTENCE):
    """A plan file of more than `size` bytes whose one meaningful sentence comes near its end."""
    return "# plan\n\n" + FILLER * (size // len(FILLER) + 1) + "\n" + sentence + "\n"


def finding(where, quote, kind="plan-vs-code"):
    return {"kind": kind, "where": where, "record_quote": quote, "tree_quote": "x = 1", "why": "the code drops settled entries"}


def reject(*findings):
    return {"artifact-type": "dwitbuk/review@1", "verdict": "reject", "findings": list(findings), "summary": "rejected"}


def accept():
    return {"artifact-type": "dwitbuk/review@1", "verdict": "accept", "findings": [], "summary": "accepted"}


def accepted_by_drops(*dropped):
    """What a verifier's runner saves when it dropped every finding of a reject as unfounded: an accept, the findings kept
    beside it under `unfounded`, each with the runner's reason."""
    notes = [dict(f, unfounded="quotes `%s`, which is nowhere in the request" % f["record_quote"].strip("`")) for f in dropped]
    return {"artifact-type": "dwitbuk/review@1", "verdict": "accept", "findings": [], "unfounded": notes,
            "summary": "rejected only on unfounded finding(s) (%s); counted as accept" % "; ".join(n["unfounded"] for n in notes)}


UNREAD_ACCEPT = {"artifact-type": "dwitbuk/review@1", "verdict": None, "answered": "accept", "unread": ["src/a.py"], "findings": [],
                 "summary": "not an accept: required files left unread: `src/a.py`. "}


class VerifierAnswerCase(unittest.TestCase):
    """A temporary git project with the given files committed, the lock's verifier a fake script that copies every request it
    gets to `seen.jsonl` beside it (in the run's local/) and answers what `fakes/review-<task>.json` (else `fakes/review.json`)
    holds, so a test can switch its answer between calls."""

    def setUp(self):
        self.pj = Project()
        self.pj.__enter__()
        self.dir = self.pj.dir
        self.addCleanup(self.pj.__exit__, None, None, None)

    def cli(self, *argv):
        return run(*argv, "--target", self.dir)

    def answer(self, review, task=None):
        write(os.path.join(self.dir, "fakes", "review%s.json" % ("-" + task if task else "")), review)

    def start(self, review, files=(), tasks=("T",), ignore=()):
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        write(os.path.join(self.dir, ".gitignore"), "".join(p + "\n" for p in ("fakes/",) + tuple(ignore)))
        for path, text in files:
            write(os.path.join(self.dir, path), text)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "base")
        script = os.path.join(self.dir, "fakes", "eyes.py")
        write(script,
              "import json, os, sys\n"
              "req = json.load(open(sys.argv[1], encoding='utf-8'))\n"
              "with open(os.path.join(os.path.dirname(sys.argv[1]), 'seen.jsonl'), 'a', encoding='utf-8') as fh:\n"
              "    fh.write(json.dumps(req) + '\\n')\n"
              "here = os.path.dirname(os.path.abspath(__file__))\n"
              "own = os.path.join(here, 'review-%s.json' % req.get('task'))\n"
              "path = own if os.path.exists(own) else os.path.join(here, 'review.json')\n"
              "lock = os.path.join(here, 'unreadable.txt')\n"
              "if os.path.exists(lock):\n"
              "    os.chmod(os.path.join(req['target'], open(lock, encoding='utf-8').read().strip()), 0)\n"
              "json.dump(json.load(open(path, encoding='utf-8')), open(sys.argv[2], 'w', encoding='utf-8'))\n")
        self.answer(review)
        write(os.path.join(self.dir, "hunsu.lock.json"), {"roles": {"verifier": [PY, script, "{request}", "{response}"]}})
        code, out = self.cli("init", "--session", "--goal", "g")
        self.assertEqual(code, 0, out)
        for tid in tasks:
            code, out = self.cli("add", tid, "--check", PASS_CHECK, "--brief", BRIEF)
            self.assertEqual(code, 0, out)
            # the session's own change: a non-empty diff is what the verifier is sent
            write(os.path.join(self.dir, "src", "%s.py" % tid.lower()), "x = 1\n")

    def task(self, tid="T"):
        tasks = self.pj.state()["tasks"]
        self.assertIn(tid, tasks, "no task %s in the run: %s" % (tid, sorted(tasks)))
        return tasks[tid]

    def seen(self):
        path = os.path.join(c.run_dir(self.dir), "local", "seen.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def assertStands(self, code, out, f, tid="T", others_overruled=False):
        """The finding stands: the session task stops (exit 2), the finding is printed whole, it is not overruled, not done.
        Unless others_overruled, nothing at all is overruled; with it, other findings of the same review may be."""
        self.assertEqual(code, 2, "the finding was not left standing — the task did not stop for the session:\n" + out)
        self.assertIn(f["record_quote"], out, "the standing finding is not printed whole:\n" + out)
        self.assertIn(f["why"], out, out)
        ts = self.task(tid)
        if others_overruled:
            over = [o.get("finding") for o in (ts.get("overruled") or {}).get("findings") or []]
            self.assertNotIn(f, over, "a grounded finding was overruled: %s" % ts.get("overruled"))
        else:
            self.assertNotIn("overruled", ts, "a grounded finding was overruled: %s" % ts.get("overruled"))
        self.assertNotEqual(ts.get("status"), "done", ts.get("status"))


# ====================================================================== V1.1 files are read whole, whatever their size

class V1_1_WholeFiles(VerifierAnswerCase):

    def test_V1_1_a_quote_only_in_a_plan_file_over_200000_bytes_stands_and_the_task_stops(self):
        f = finding("brief and plan/big.md", "plan/big.md says `%s`" % SENTENCE)
        self.start(reject(f), files=[("plan/big.md", big_plan())])
        self.assertGreater(os.path.getsize(os.path.join(self.dir, "plan", "big.md")), 200000)
        code, out = self.cli("run", "T")
        self.assertNotIn("unfounded, overruled", out, "a quote in a large plan file was judged unfounded:\n" + out)
        self.assertStands(code, out, f)

    def test_V1_1_unfounded_called_directly_reads_a_named_file_over_200000_bytes_whole(self):
        top = tempfile.mkdtemp(prefix="chongdae-v11-")
        self.addCleanup(shutil.rmtree, top, True)
        write(os.path.join(top, "plan", "small.md"), "# plan\n\n" + SENTENCE + "\n")
        write(os.path.join(top, "plan", "big.md"), big_plan())
        request = {"target": top, "brief": BRIEF, "contract": {}, "touched": [], "tests": []}
        quote = "`%s`" % SENTENCE
        # the fixture's ground: a small named file grounds the quote today; a quote in no file is unfounded
        self.assertIsNone(c.unfounded(finding("brief and plan/small.md", quote), request))
        self.assertTrue(c.unfounded(finding("brief and plan/missing.md", quote), request))
        self.assertIsNone(c.unfounded(finding("brief and plan/big.md", quote), request),
                          "a quote in a named file over 200000 bytes is judged unfounded because the file was not read")

    def test_V1_1_a_named_file_of_exactly_200000_bytes_is_read(self):
        top = tempfile.mkdtemp(prefix="chongdae-v11-")
        self.addCleanup(shutil.rmtree, top, True)
        tail = "\n" + SENTENCE + "\n"
        head = "# plan\n"
        body = head + "x" * (200000 - len(head) - len(tail)) + tail
        write(os.path.join(top, "plan", "edge.md"), body)
        self.assertEqual(os.path.getsize(os.path.join(top, "plan", "edge.md")), 200000)
        request = {"target": top, "brief": BRIEF, "contract": {}, "touched": [], "tests": []}
        self.assertIsNone(c.unfounded(finding("brief and plan/edge.md", "`%s`" % SENTENCE), request),
                          "a named file of exactly 200000 bytes was not read")

    def test_V1_1_a_touched_file_over_200000_bytes_is_read_whole(self):
        top = tempfile.mkdtemp(prefix="chongdae-v11-")
        self.addCleanup(shutil.rmtree, top, True)
        write(os.path.join(top, "small.md"), "# notes\n" + SENTENCE + "\n")
        write(os.path.join(top, "big.md"), big_plan())
        quote = "`%s`" % SENTENCE
        small = {"target": top, "brief": BRIEF, "contract": {}, "touched": ["small.md"], "tests": []}
        self.assertIsNone(c.unfounded(finding("brief", quote), small), "the fixture's ground: a small touched file grounds the quote")
        big = dict(small, touched=["big.md"])
        self.assertIsNone(c.unfounded(finding("brief", quote), big), "a touched file over 200000 bytes was not read")
        tests = dict(small, touched=[], tests=["big.md"])
        self.assertIsNone(c.unfounded(finding("brief", quote), tests), "a tests file over 200000 bytes was not read")


# ====================================================================== V1.2 a file that cannot be read leaves the finding standing

class V1_2_CannotRead(VerifierAnswerCase):
    """The verifier's fake takes the read permission off a named file just before it answers (when `fakes/unreadable.txt`
    names one): what chongdae's own checks read before is an ordinary tree. The file is one git ignores (a local copy of a
    plan, say), so that only the grounding of the quote — not the tree's own fingerprint — meets it unreadable."""

    def check_cannot_read(self, out, path):
        ts = self.task()
        prefix = "T: chongdae could not check the record quote of the verifier's plan-vs-code finding at "
        lines = [n for n in ts.get("non-claims") or [] if n.startswith(prefix)]
        self.assertTrue(lines, "no non-claim says the record quote could not be checked: %s" % ts.get("non-claims"))
        line = lines[0]
        self.assertIn("against %s (" % path, line, line)
        self.assertTrue(line.endswith("; the finding stands"), line)
        self.assertIn(line, out, "run does not print the non-claim:\n" + out)

    def test_V1_2_a_named_path_that_is_a_directory_leaves_the_finding_standing_with_a_non_claim(self):
        f = finding("brief and plan/notes.md", "plan/notes.md says `%s`" % SENTENCE)
        self.start(reject(f), files=[("plan/notes.md/inner.txt", "a file inside a directory named like a file\n")])
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "plan", "notes.md")))
        code, out = self.cli("run", "T")
        self.assertStands(code, out, f)
        self.check_cannot_read(out, "plan/notes.md")

    def test_V1_2_a_named_file_whose_permissions_are_removed_leaves_the_finding_standing_with_a_non_claim(self):
        f = finding("brief and plan/locked.md", "plan/locked.md says `%s`" % SENTENCE)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            # root reads any file: the unreadable path is a directory instead
            files, path = [("plan/locked.md/inner.txt", "x\n")], "plan/locked.md"
        else:
            files, path = [("plan/locked.md", "# plan\n\n" + SENTENCE + "\n")], "plan/locked.md"
        self.start(reject(f), files=files, ignore=(path,))
        self.assertTrue(os.path.exists(os.path.join(self.dir, path)))
        full = os.path.join(self.dir, path)
        if os.path.isfile(full):
            # the verifier read the file; it is unreadable by the time chongdae weighs the answer
            write(os.path.join(self.dir, "fakes", "unreadable.txt"), path)
            self.addCleanup(os.chmod, full, stat.S_IRUSR | stat.S_IWUSR)
        try:
            code, out = self.cli("run", "T")
        except OSError as err:
            self.fail("run raised on a named file it cannot read instead of leaving the finding standing: %r" % err)
        self.assertStands(code, out, f)
        self.check_cannot_read(out, path)


# ====================================================================== V1.3 a backticked quote with an elision is matched piecewise

PLAN_PIECES = "# plan\n\nThe ledger keeps every settled entry.\nSome unrelated text sits between.\nEntries expire after exactly seven years.\n"


class V1_3_Elisions(VerifierAnswerCase):

    def test_V1_3_a_backticked_quote_with_an_ellipsis_character_whose_pieces_are_in_the_named_file_stands(self):
        f = finding("brief and plan/p.md", "plan/p.md says `The ledger keeps every settled entry … Entries expire after exactly seven years.`")
        self.start(reject(f), files=[("plan/p.md", PLAN_PIECES)])
        code, out = self.cli("run", "T")
        self.assertStands(code, out, f)

    def test_V1_3_a_backticked_quote_with_three_dots_whose_pieces_are_in_the_request_and_the_file_stands(self):
        # the first piece is the brief's own words, the second only the named file's
        f = finding("brief and plan/p.md", "`keep the settled entries ... Entries expire after exactly seven years.`")
        self.start(reject(f), files=[("plan/p.md", PLAN_PIECES)])
        code, out = self.cli("run", "T")
        self.assertStands(code, out, f)

    def test_V1_3_a_piece_shorter_than_8_characters_is_not_checked(self):
        f = finding("brief and plan/p.md", "`The ledger keeps every settled entry … zq … Entries expire after exactly seven years.`")
        self.start(reject(f), files=[("plan/p.md", PLAN_PIECES)])
        code, out = self.cli("run", "T")
        self.assertStands(code, out, f)

    def test_V1_3_with_one_piece_absent_from_everything_the_finding_is_overruled_while_a_grounded_one_stands(self):
        grounded = finding("brief and plan/p.md", "`The ledger keeps every settled entry … Entries expire after exactly seven years.`")
        absent = dict(finding("brief and plan/p.md", "`The ledger keeps every settled entry … %s`" % NOWHERE), why="a second charge")
        self.start(reject(grounded, absent), files=[("plan/p.md", PLAN_PIECES)])
        code, out = self.cli("run", "T")
        self.assertStands(code, out, grounded, others_overruled=True)
        ts = self.task()
        self.assertIn("overruled", ts, "the finding with a piece found nowhere is not overruled: %s" % sorted(ts))
        over = [o.get("finding") for o in ts["overruled"].get("findings") or []]
        self.assertEqual(over, [absent], ts["overruled"])


# ====================================================================== V2.1 a dropped finding whose quote is found is reinstated

class V2_1_Reinstated(VerifierAnswerCase):

    def test_V2_1_a_dropped_finding_quoting_a_210_kb_plan_file_is_reinstated_and_the_task_stops(self):
        f = finding("brief and plan/big.md", "`%s`" % SENTENCE)
        review = accepted_by_drops(f)
        self.start(review, files=[("plan/big.md", big_plan())])
        code, out = self.cli("run", "T")
        self.assertEqual(code, 2, "a dropped finding whose quote is in the plan file was not reinstated:\n" + out)
        self.assertIn(f["record_quote"].strip("`"), out, out)
        self.assertIn(f["why"], out, "the reinstated finding is not printed whole:\n" + out)
        self.assertIn(f["tree_quote"], out, out)
        ts = self.task()
        self.assertNotEqual(ts.get("status"), "done", "a reinstated reject left the task done")
        self.assertIn("reinstated", ts, "the task records nothing reinstated: %s" % sorted(ts))
        rec = ts["reinstated"]
        self.assertIn("at", rec, rec)
        self.assertIn("chongdae", rec, rec)
        found = rec.get("findings") or []
        self.assertEqual(len(found), 1, rec)
        kept = found[0].get("finding") or {}
        for key in ("kind", "where", "record_quote", "tree_quote", "why"):
            self.assertEqual(kept.get(key), f[key], found[0])
        self.assertIn("plan/big.md", str(found[0].get("found-in")), found[0])
        notes = [n for n in ts.get("non-claims") or []
                 if n.startswith("T: the verifier's runner dropped its plan-vs-code finding at brief and plan/big.md as unfounded")]
        self.assertTrue(notes, "no non-claim says the finding was reinstated: %s" % ts.get("non-claims"))
        self.assertIn("plan/big.md", notes[0])
        self.assertTrue(notes[0].endswith("reinstated"), notes[0])
        # the response file and `review` stay as the verifier's runner wrote them
        self.assertEqual(ts.get("review", {}).get("verdict"), "accept", ts.get("review"))
        self.assertEqual(ts.get("review", {}).get("unfounded"), review["unfounded"], ts.get("review"))


# ====================================================================== V2.2 a drop that turned a reject into an accept is a non-claim

class V2_2_DroppedIntoAccept(VerifierAnswerCase):

    def test_V2_2_a_drop_chongdae_cannot_ground_goes_on_as_accepted_with_a_non_claim_run_prints_and_close_lists(self):
        f = finding("brief and plan/big.md", "`%s`" % NOWHERE)
        review = accepted_by_drops(f)
        reason = review["unfounded"][0]["unfounded"]
        self.start(review, files=[("plan/big.md", big_plan())], tasks=("T", "U"))
        self.answer(accept(), task="U")   # an ordinary accept, nothing dropped
        code, out = self.cli("run")
        self.assertEqual(code, 0, out)
        ts = self.task("T")
        self.assertEqual(ts.get("status"), "done", ts.get("status"))
        self.assertNotIn("reinstated", ts, "a quote found nowhere was reinstated: %s" % ts.get("reinstated"))
        head = "T: the verifier's reject was counted as an accept by its runner, which dropped 1 finding(s) as unfounded: "
        notes = [n for n in ts.get("non-claims") or [] if n.startswith(head)]
        self.assertTrue(notes, "no non-claim says the reject was counted as an accept: %s" % ts.get("non-claims"))
        line = notes[0]
        self.assertIn(NOWHERE, line, line)
        self.assertIn(reason, line, "the runner's reason is not on the line: " + line)
        self.assertIn(line, out, "run does not print the non-claim:\n" + out)
        code, closed = self.cli("close", *UNCOMMITTED)
        self.assertEqual(code, 0, closed)
        self.assertIn(head.strip(), closed, "close does not list the dropped-into-accept non-claim:\n" + closed)
        self.assertNotIn("non-claims: none", closed, closed)
        # an accept with nothing dropped adds no such non-claim
        u = self.task("U")
        self.assertEqual(u.get("status"), "done", u.get("status"))
        self.assertFalse([n for n in u.get("non-claims") or [] if "counted as an accept" in n], u.get("non-claims"))


# ====================================================================== V3 an accept without reading is said as what it is

class V3_UnreadAccept(VerifierAnswerCase):

    def first_run(self):
        self.start(UNREAD_ACCEPT)
        return self.cli("run", "T")

    def test_V3_1_run_stops_saying_the_eyes_accepted_without_reading_and_names_chongdae_run(self):
        code, out = self.first_run()
        self.assertEqual(code, 2, out)
        lines = [l for l in out.splitlines() if re.search(r"accepted\b.*without reading.*src/a\.py", l)]
        self.assertTrue(lines, "no line says the eyes accepted without reading src/a.py:\n" + out)
        self.assertIn("chongdae run T", lines[0], "the line does not name `chongdae run T`: " + lines[0])
        self.assertNotIn("fix the verifier", out, out)
        self.assertNotIn("did not answer", out, out)

    def test_V3_2_the_task_keeps_the_unread_accept(self):
        code, out = self.first_run()
        ts = self.task()
        self.assertIn("unread-accepts", ts, "the unread accept is not kept on the task: %s" % sorted(ts))
        kept = ts["unread-accepts"]
        self.assertIsInstance(kept, list, kept)
        self.assertEqual(len(kept), 1, kept)
        self.assertEqual(kept[0].get("unread"), ["src/a.py"], kept[0])
        self.assertEqual(kept[0].get("summary"), UNREAD_ACCEPT["summary"], kept[0])
        self.assertIn("at", kept[0])
        self.assertIn("chongdae", kept[0])
        # a second occurrence is appended
        code, out = self.cli("run", "T")
        self.assertEqual(len(self.task().get("unread-accepts") or []), 2, self.task().get("unread-accepts"))

    def test_V3_3_retry_names_chongdae_run_and_does_not_say_not_stopped(self):
        code, out = self.first_run()
        self.assertEqual(code, 2, out)
        code, said = self.cli("retry", "T")
        self.assertNotIn("not stopped on a provider response or a rejection", said, said)
        self.assertIn("chongdae run T", said, "retry does not name the command that asks the eyes again:\n" + said)

    def test_V3_4_the_next_run_sends_a_new_request_and_its_accept_completes_the_task(self):
        code, out = self.first_run()
        self.assertEqual(code, 2, out)
        self.assertEqual(len(self.seen()), 1, "the fake verifier saw %d request(s)" % len(self.seen()))
        self.answer(accept())
        code, out = self.cli("run", "T")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.seen()), 2, "the next run did not ask the verifier again")
        ts = self.task()
        self.assertEqual(ts.get("status"), "done", ts.get("status"))
        self.assertIn("unread-accepts", ts, "the earlier unread accept is not kept on the task: %s" % sorted(ts))


# ====================================================================== V4 the README and the run skill

def sentences(text):
    return [s.replace("\n", " ") for s in re.split(r"(?<=[.!?])\s+", text)]


class V4_Docs(unittest.TestCase):

    def read(self, *path):
        with open(os.path.join(HERE, "plugin", *path), encoding="utf-8") as fh:
            return fh.read()

    def test_V4_the_readme_names_reinstated_and_unread_accepts(self):
        text = self.read("README.md")
        self.assertIn("`reinstated`", text, "the README does not name the task field `reinstated`")
        self.assertIn("`unread-accepts`", text, "the README does not name the task field `unread-accepts`")

    def test_V4_the_readme_says_a_quote_is_checked_against_whole_files(self):
        text = self.read("README.md")
        hits = [s for s in sentences(text) if "quote" in s and re.search(r"whole files?|files?\b.{0,60}\bwhole\b|whatever (its|their) size", s)]
        self.assertTrue(hits, "no sentence of the README says a record quote is held against whole files")

    def test_V4_the_readme_says_how_an_unread_accept_and_an_elision_are_read(self):
        text = self.read("README.md")
        self.assertTrue([s for s in sentences(text) if re.search(r"without (reading|opening)", s) and "chongdae run" in s],
                        "no sentence of the README says an unread accept is asked again with `chongdae run`")
        self.assertTrue([s for s in sentences(text) if "quote" in s and ("…" in s or "..." in s or "elision" in s) and "piece" in s],
                        "no sentence of the README says an elided quote is matched piecewise")

    def test_V4_the_run_skill_says_an_unread_accept_is_asked_again_with_chongdae_run(self):
        text = self.read("skills", "run", "SKILL.md")
        hits = [s for s in sentences(text) if "unread" in s.lower() and "chongdae run" in s]
        self.assertTrue(hits, "the run skill does not say an unread accept is asked again with `chongdae run TASK`")


if __name__ == "__main__":
    unittest.main()
