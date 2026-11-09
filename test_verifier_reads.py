"""C5: the committed review keeps the paths the verifier opened.

A session run whose lock declares a fake implementer and a fake verifier; the verifier leaves a Claude Code transcript in
the run's local/ and names it in `worker.transcript`. The committed task file (`.chongdae/run-*/tasks/<id>.json`, read from
disk — not `load_state`, which merges the overlay back) must carry `verified_by.trace.opened`.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_chongdae import Project, run, write
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW_ACCEPT = {"artifact-type": "dwitbuk/review@1", "verdict": "accept", "findings": []}
REVIEW_REJECT = {"artifact-type": "dwitbuk/review@1", "verdict": "reject", "findings": [
    {"kind": "plan-vs-code", "where": "a.py", "record_quote": "x", "tree_quote": "x = 1", "why": "a reason"}]}
RESPONSE_DONE = {"status": "done", "summary": "built", "verified": [], "decisions": [], "non-claims": []}


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True)


def tool_use(i, name, **inp):
    return {"type": "tool_use", "id": "tu-%d" % i, "name": name, "input": inp}


def reads_transcript(project, outside):
    """The reproducer's verifier session: one assistant line holding its tool calls."""
    calls = [
        tool_use(1, "Read", file_path=os.path.join(project, "a.py")),
        tool_use(2, "Read", file_path=os.path.join(project, "src", "b.py")),
        tool_use(3, "Glob", pattern="**/*.py", path=os.path.join(project, "src")),
        tool_use(4, "Grep", pattern="TOKEN_[A-Z]+"),
        tool_use(5, "Grep", pattern="x", path=project),
        tool_use(6, "Read", file_path=outside),
        tool_use(7, "Read", file_path=os.path.join(project, "a.py")),
    ]
    return [{"type": "assistant", "message": {"model": "claude-test", "content": calls}}]


def bash_only_transcript(project):
    """A transcript with no read event: one command and its result."""
    return [{"type": "assistant", "cwd": project, "message": {"model": "claude-test", "content": [
                tool_use(1, "Bash", command="cd %s && python -c pass" % project)]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu-1", "is_error": False}]}}]


def provider_script(path, responses, transcript_lines, counter):
    """A fake provider: writes `transcript_lines` (if any) beside its response file in local/, then the n-th response
    (the last one repeats); the response's `worker.transcript` names the transcript it left."""
    write(path,
          "import json, os, sys\n"
          "counter = %r\n"
          "n = len(open(counter).read()) if os.path.exists(counter) else 0\n"
          "open(counter, 'a').write('x')\n"
          "responses = json.loads(%r)\n"
          "resp = dict(responses[min(n, len(responses) - 1)])\n"
          "lines = json.loads(%r)\n"
          "if lines is not None:\n"
          "    name = os.path.basename(sys.argv[2])[:-len('.json')] + '.session.%%d.jsonl' %% n\n"
          "    with open(os.path.join(os.path.dirname(sys.argv[2]), name), 'w') as fh:\n"
          "        fh.write(''.join(json.dumps(l) + '\\n' for l in lines))\n"
          "    resp['worker'] = {'host': 'claude-code', 'model': 'claude-test', 'session': 's-%%d' %% n, 'transcript': name}\n"
          "req = json.load(open(sys.argv[1]))\n"
          "if req.get('stage') != 'verify':\n"
          "    open(os.path.join(req['target'], 'built.py'), 'a').write('n = %%d\\n' %% n)   # the build's own change: a verifier reads a non-empty diff\n"
          "json.dump(resp, open(sys.argv[2], 'w'))\n"
          % (counter, json.dumps(responses), json.dumps(transcript_lines)))
    return [sys.executable, path, "{request}", "{response}"]


class VerifierReads(unittest.TestCase):
    def setUp(self):
        self.pj = Project()
        self.pj.__enter__()
        self.addCleanup(self.pj.__exit__, None, None, None)
        self.scratch = tempfile.mkdtemp(prefix="chongdae-c5-")
        self.addCleanup(shutil.rmtree, self.scratch, True)
        fd, self.outside = tempfile.mkstemp(prefix="chongdae-c5-outside-", suffix=".txt")
        os.close(fd)
        self.addCleanup(os.remove, self.outside)
        d = self.pj.dir
        write(os.path.join(d, "a.py"), "x = 1\n")
        write(os.path.join(d, "src", "b.py"), "TOKEN_A = 1\n")

    def session_run(self, verifier_lines, verdicts=(REVIEW_ACCEPT,), builder_lines=None, tid="b"):
        """Init a session run with the lock's implementer and verifier, add `tid` with a --check, run until it stops.
        Returns (committed task record, overlay, output)."""
        d = self.pj.dir
        lock = {"roles": {
            "implementer": provider_script(os.path.join(d, "builder.py"), [RESPONSE_DONE], builder_lines,
                                           os.path.join(self.scratch, "builder-n")),
            "verifier": provider_script(os.path.join(d, "eyes.py"), list(verdicts), verifier_lines,
                                        os.path.join(self.scratch, "eyes-n"))}}
        write(os.path.join(d, "hunsu.lock.json"), lock)
        git(d, "add", "-A")
        git(d, "commit", "-qm", "base")
        self.assertEqual(run("init", "--session", "--goal", "g", "--target", d)[0], 0)
        code, out = run("add", tid, "--role", "implementer", "--brief", "build it", "--check", sys.executable + " -c pass", "--target", d)
        self.assertEqual(code, 0, out)
        outs = []
        for _ in range(6):
            code, out = run("run", "--target", d)
            outs.append(out)
            if c.load_state(c.run_dir(d))["tasks"][tid].get("status") == "done":
                break
        text = "\n".join(outs)
        rd = c.run_dir(d)
        files = glob.glob(os.path.join(d, ".chongdae", "run-*", "tasks", tid + ".json"))
        self.assertEqual(len(files), 1, (files, text))
        with open(files[0], encoding="utf-8") as fh:
            pub = json.load(fh)
        self.assertEqual(pub.get("status"), "done", text)
        overlay_path = os.path.join(rd, "local", "tasks", tid + ".json")
        overlay = json.load(open(overlay_path, encoding="utf-8")) if os.path.exists(overlay_path) else {}
        return pub, overlay, text

    # ---------------------------------------------------------------- C5.1

    def test_C5_1_committed_verified_by_lists_opened_project_paths_once_in_order(self):
        pub, _, out = self.session_run(reads_transcript(self.pj.dir, self.outside))
        trace = (pub.get("verified_by") or {}).get("trace") or {}
        self.assertIn("opened", trace, ("the committed verifier line says nothing of what it opened", pub.get("verified_by")))
        self.assertEqual(trace["opened"], ["a.py", "src/b.py", "src", "."])

    def test_C5_1_outside_paths_are_counted_not_listed(self):
        pub, _, _ = self.session_run(reads_transcript(self.pj.dir, self.outside))
        trace = (pub.get("verified_by") or {}).get("trace") or {}
        self.assertEqual(trace.get("opened-outside"), 1, trace)
        blob = json.dumps(trace.get("opened"))
        self.assertNotIn(os.path.basename(self.outside), blob)
        self.assertNotIn("<tmp>", blob)

    def test_C5_1_never_a_pattern_and_no_leading_dot_slash(self):
        pub, _, _ = self.session_run(reads_transcript(self.pj.dir, self.outside))
        opened = ((pub.get("verified_by") or {}).get("trace") or {}).get("opened")
        self.assertIsInstance(opened, list, pub.get("verified_by"))
        for p in opened:
            self.assertFalse(p.startswith("./") or p.startswith("/") or "\\" in p, p)
            self.assertNotIn("*", p)
            self.assertNotIn("TOKEN_", p)
        self.assertEqual(len(opened), len(set(opened)), opened)

    def test_C5_1_no_opened_outside_when_nothing_was_outside(self):
        lines = reads_transcript(self.pj.dir, self.outside)
        lines[0]["message"]["content"] = [x for x in lines[0]["message"]["content"] if x["input"].get("file_path") != self.outside]
        pub, _, _ = self.session_run(lines)
        trace = (pub.get("verified_by") or {}).get("trace") or {}
        self.assertEqual(trace.get("opened"), ["a.py", "src/b.py", "src", "."], trace)
        self.assertNotIn("opened-outside", trace)

    # ---------------------------------------------------------------- C5.2

    def test_C5_2_overlay_keeps_the_full_read_list_and_record_has_no_read(self):
        pub, overlay, _ = self.session_run(reads_transcript(self.pj.dir, self.outside))
        self.assertIn("opened", ((pub.get("verified_by") or {}).get("trace") or {}), pub.get("verified_by"))
        self.assertNotIn('"read"', json.dumps(pub), "`read` stays out of the committed record")
        read = (overlay.get("verified_by") or {}).get("read")
        self.assertIsInstance(read, list, overlay)
        self.assertIn("TOKEN_[A-Z]+", read, "the overlay keeps the pattern of a Grep with no path")
        # the overlay keeps the outside read as the overlay writes every read entry now: through neutral_path (<tmp> for a
        # temporary file)
        self.assertIn(c.neutral_path(self.outside, self.pj.dir), read, ("the overlay keeps the outside path", read))
        self.assertIn("read", c.PRIVATE_KEYS)

    def test_C5_2_the_builders_performed_by_gets_no_opened(self):
        # the builder read files too: its line still carries no `opened`, only the verifier's does
        pub, overlay, _ = self.session_run(reads_transcript(self.pj.dir, self.outside),
                                           builder_lines=reads_transcript(self.pj.dir, self.outside))
        self.assertIn("opened", ((pub.get("verified_by") or {}).get("trace") or {}), pub.get("verified_by"))
        pb = pub.get("performed_by") or {}
        self.assertIn("trace", pb, ("the builder's transcript was read for its trace", pb))
        self.assertNotIn("opened", pb.get("trace") or {}, pb)
        self.assertNotIn("opened", pb, pb)
        self.assertNotIn("opened", json.dumps(overlay.get("performed_by") or {}))

    # ---------------------------------------------------------------- C5.3

    def test_C5_3_a_rejected_verifier_line_kept_in_the_attempt_keeps_its_opened(self):
        pub, _, out = self.session_run(reads_transcript(self.pj.dir, self.outside), verdicts=(REVIEW_REJECT, REVIEW_ACCEPT))
        attempts = pub.get("attempts") or []
        self.assertTrue(attempts, ("the reject sent the task back once", out))
        vb = attempts[0].get("verified_by")
        self.assertIsInstance(vb, dict, ("the attempt keeps the verifier line of its review", attempts[0].keys()))
        self.assertEqual((vb.get("trace") or {}).get("opened"), ["a.py", "src/b.py", "src", "."], vb)
        self.assertEqual(((pub.get("verified_by") or {}).get("trace") or {}).get("opened"), ["a.py", "src/b.py", "src", "."])

    def test_C5_3_resend_moves_the_verifier_line_with_its_opened_into_the_attempt(self):
        d = self.pj.dir
        self.assertEqual(run("init", "--session", "--goal", "g", "--target", d)[0], 0)
        self.assertEqual(run("add", "b", "--brief", "x", "--check", sys.executable + " -c pass", "--role", "session",
                             "--why", "direct", "--target", d)[0], 0)
        rd = c.run_dir(d)
        state = c.load_state(rd)
        vb = {"provider": "command", "argv": ["eyes"], "trace": {"changed": [], "commands-run": 0, "commands-failed": 0,
                                                                "opened": ["a.py", "src"], "opened-outside": 2}}
        state["tasks"]["b"].update({"status": "stopped", "response": dict(RESPONSE_DONE), "review": dict(REVIEW_REJECT),
                                    "verified_by": vb})
        c.save_state(rd, state)
        c.resend(d, rd, c.load_state(rd), "b", {"by": "t"})
        pub = json.load(open(os.path.join(rd, "tasks", "b.json"), encoding="utf-8"))
        attempt = (pub.get("attempts") or [{}])[-1]
        self.assertIn("verified_by", attempt, ("the resent attempt keeps its verifier line", attempt.keys()))
        self.assertEqual(attempt["verified_by"]["trace"].get("opened"), ["a.py", "src"])
        self.assertEqual(attempt["verified_by"]["trace"].get("opened-outside"), 2)

    # ---------------------------------------------------------------- C5.4

    def test_C5_4_no_read_events_means_no_opened_key(self):
        # task `r` is reviewed by eyes that read; `n` by eyes whose transcript has no read event: one says what it
        # opened, the other has no `opened` at all (not an empty list)
        pub_r, _, _ = self.session_run(reads_transcript(self.pj.dir, self.outside), tid="r")
        self.assertIn("opened", ((pub_r.get("verified_by") or {}).get("trace") or {}), pub_r.get("verified_by"))
        self.assertEqual(run("add", "n", "--role", "implementer", "--brief", "again", "--check", sys.executable + " -c pass",
                             "--target", self.pj.dir)[0], 0)
        os.remove(os.path.join(self.scratch, "eyes-n"))
        provider_script(os.path.join(self.pj.dir, "eyes.py"), [REVIEW_ACCEPT], bash_only_transcript(self.pj.dir),
                        os.path.join(self.scratch, "eyes-n"))
        for _ in range(6):
            run("run", "--target", self.pj.dir)
            if c.load_state(c.run_dir(self.pj.dir))["tasks"]["n"].get("status") == "done":
                break
        pub_n = json.load(open(os.path.join(c.run_dir(self.pj.dir), "tasks", "n.json"), encoding="utf-8"))
        trace = (pub_n.get("verified_by") or {}).get("trace")
        self.assertIsInstance(trace, dict, ("the transcript was read for a trace", pub_n.get("verified_by")))
        self.assertNotIn("opened", trace)
        self.assertNotIn("opened-outside", trace)

    def test_C5_4_no_transcript_means_no_opened_key(self):
        pub_r, _, _ = self.session_run(reads_transcript(self.pj.dir, self.outside), tid="r")
        self.assertIn("opened", ((pub_r.get("verified_by") or {}).get("trace") or {}), pub_r.get("verified_by"))
        self.assertEqual(run("add", "n", "--role", "implementer", "--brief", "again", "--check", sys.executable + " -c pass",
                             "--target", self.pj.dir)[0], 0)
        provider_script(os.path.join(self.pj.dir, "eyes.py"), [REVIEW_ACCEPT], None, os.path.join(self.scratch, "eyes-m"))
        for _ in range(6):
            run("run", "--target", self.pj.dir)
            if c.load_state(c.run_dir(self.pj.dir))["tasks"]["n"].get("status") == "done":
                break
        pub_n = json.load(open(os.path.join(c.run_dir(self.pj.dir), "tasks", "n.json"), encoding="utf-8"))
        self.assertEqual(pub_n.get("status"), "done")
        self.assertNotIn("opened", json.dumps(pub_n.get("verified_by") or {}))

    # ---------------------------------------------------------------- C5.5

    def test_C5_5_readme_task_record_fields_say_verified_by_trace_opened(self):
        with open(os.path.join(HERE, "plugin", "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        m = re.search(r"^## Files in your project\n(.*?)(?=^## )", text, re.S | re.M)
        self.assertTrue(m, "README has a Files in your project section")
        section = m.group(1)
        self.assertIn("verified_by.trace.opened", section)
        para = next(p for p in re.split(r"\n\s*\n", section) if "verified_by.trace.opened" in p)
        low = para.lower()
        self.assertIn("transcript", low, para)
        self.assertTrue("project" in low and ("path" in low), para)
        self.assertTrue(any(w in low for w in ("absen", "missing", "no `opened`", "without")), para)


if __name__ == "__main__":
    unittest.main()
