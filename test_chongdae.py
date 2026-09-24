"""Self-check for chongdae. A temp project; a fake provider that replays recorded responses; every stop fires once.

  python test_chongdae.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chongdae  # noqa: E402

# Recorded from real provider runs, trimmed. The runner is tested against what a real provider said.
RESPONSE_DONE = {"status": "done", "summary": "added count", "verified": [{"check": "python test_memo.py -k S4", "exit": 0}], "decisions": [], "non-claims": ["count with extra args is untested"]}
RESPONSE_DECISIONS = {"status": "done", "summary": "added tag", "verified": [{"check": "python test_memo.py -k S5", "exit": 0}],
                      "decisions": [{"what": "how a tag is shown in list", "chosen": "appended as [tag]", "alternatives": ["#tag", "[tag] before text"]},
                                    {"what": "repeating a tag", "chosen": "no-op", "alternatives": ["error", "duplicate"]}],
                      "non-claims": []}
RESPONSE_BLOCKED = {"status": "blocked", "summary": "the contract does not say what done means", "verified": [], "decisions": [], "non-claims": ["nothing built"]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, indent=1))


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = chongdae.main(list(argv))
        except SystemExit as err:
            code = err.code if isinstance(err.code, int) else 1
            out.write(str(err) + "\n")
    return code, out.getvalue()


class Project:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="chongdae-test-")
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)

    def state(self):
        return chongdae.load_state(chongdae.run_dir(self.dir))

    def fake_provider(self, response, name="provider"):
        """A provider command: writes the given response to {response}. Records nothing else — that is the runner's job."""
        script = os.path.join(self.dir, name + ".py")
        write(script, "import json, sys\nresp = json.loads(%r)\njson.dump(resp, open(sys.argv[2], 'w', encoding='utf-8'))\n" % json.dumps(response))
        return [sys.executable, script, "{request}", "{response}"]



class Skip(Exception):
    """Raised by a test that cannot run on this host; the runner reports it as SKIP, never as PASS."""

def test_plan_shape_is_refused_when_nothing_can_decide_a_task():
    p = chongdae.plan_problems({"artifact-type": "chongdae/plan@1", "goal": "g", "tasks": [
        {"id": "a", "role": "r"}, {"id": "a", "role": "r", "checks": [["x"]]}, {"id": "b", "role": "r", "path": "p", "needs": ["zzz"]}, {"id": "c", "checks": [["x"]]}]})
    text = "\n".join(p)
    for needle in ("unique ids", "a: needs `path`", "b: needs unknown task zzz", "c: no role"):
        assert needle in text, (needle, text)
    assert chongdae.plan_problems({"artifact-type": "x"})


def test_bootstrap_stops_at_each_step_and_records_gates_and_non_claims():
    with Project() as pj:
        assert run("init", "--goal", "a memo cli", "--target", pj.dir)[0] == 0
        assert run("init", "--goal", "again", "--target", pj.dir)[0] != 0, "a running run blocks a second init"
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "produce plan/questions@1" in out, out
        write(os.path.join(pj.dir, "plan", "questions.json"), {"questions": [{"id": "bad", "text": "x"}]})
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "shape check" in out and "lack an id" in out, out
        write(os.path.join(pj.dir, "plan", "questions.json"), {"questions": [{"id": "Q1", "text": "what is added?"}, {"id": "Q2", "text": "what is listed?"}]})
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review" in out, out
        assert run("confirm", "questions", "--target", pj.dir)[0] != 0, "confirm needs --by or --delegated"
        assert run("confirm", "plan", "--by", "x", "--target", pj.dir)[0] != 0, "only a produced task can be confirmed"
        assert run("confirm", "questions", "--by", "kim", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "produce plan/document@1" in out, out
        write(os.path.join(pj.dir, "plan", "PLAN.md"), "# plan\n\n## Q1 add\n\nAcceptance: x.\n\n## slices\n\n- S1: Q1\n")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "no `## <id>` section for Q2" in out, out
        write(os.path.join(pj.dir, "plan", "PLAN.md"), "# plan\n\n## Q1 add\n\nAcceptance: x.\n\n## Q2 list\n\nAcceptance: y.\n\n## slices\n\n- S1: Q1, Q2\n")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review plan/document@1" in out, out
        assert run("confirm", "plan", "--delegated", "owner said go", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "complete" in out and "skipped model" in out, out
        st = pj.state()
        q, pl = dict(st["tasks"]["questions"]["confirmed"]), dict(st["tasks"]["plan"]["confirmed"])
        assert q.pop("at", "").endswith("+00:00") and pl.pop("at", "").endswith("+00:00")   # a judgment carries its moment, in UTC
        assert q.pop("chongdae") == pl.pop("chongdae") == chongdae.engine()   # and the chongdae that recorded it
        assert q == {"by": "kim"} and pl == {"delegated": "owner said go", "verifier": None}
        assert st["tasks"]["model"]["status"] == "skipped" and any("no provider for role 'modeler'" in n for n in chongdae.non_claims(st))
        assert not os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "PLAN.md")), "artifacts live in the project, not the run dir"


def test_session_code_task_is_decided_by_checks_only():
    with Project() as pj:
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "providers": {"implementer": "session"},
                "tasks": [{"id": "S1", "role": "implementer", "gate": "human", "checks": [[sys.executable, "check.py"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", os.path.join(pj.dir, "plan.json"), "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "make these checks pass" in out and "check.py" in out, out
        write(os.path.join(pj.dir, "check.py"), "import sys; sys.exit(0)\n")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review task S1" in out, out
        assert pj.state()["tasks"]["S1"]["touched"] == ["check.py"], pj.state()["tasks"]["S1"]["touched"]   # plan.json was dirty before the task started: not its change
        assert run("confirm", "S1", "--by", "kim", "--target", pj.dir)[0] == 0 and run("run", "--target", pj.dir)[0] == 0
        # recheck: still green, then red once the check breaks
        assert run("recheck", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "check.py"), "import sys; sys.exit(3)\n")
        code, out = run("recheck", "--target", pj.dir)
        assert code == 1 and "RED" in out, out


def test_command_provider_done_decisions_and_blocked():
    with Project() as pj:
        write(os.path.join(pj.dir, "check.py"), "import sys; sys.exit(0)\n")
        def plan_with(response, tid):
            p = {"artifact-type": "chongdae/plan@1", "goal": "g", "providers": {"implementer": pj.fake_provider(response)},
                 "tasks": [{"id": tid, "role": "implementer", "gate": "human", "checks": [[sys.executable, "check.py"]], "closes": ["Q1"]}]}
            write(os.path.join(pj.dir, "plan.json"), p)
            assert run("init", "--plan", os.path.join(pj.dir, "plan.json"), "--target", pj.dir)[0] == 0
        # done, no decisions -> straight to the gate; non-claims copied into the run
        plan_with(RESPONSE_DONE, "A")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review task A" in out, out
        st = pj.state()
        assert st["tasks"]["A"]["response"]["status"] == "done" and any("count with extra args" in n for n in chongdae.non_claims(st))
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "A.request.json")), "the request file is part of the record"
        assert run("confirm", "A", "--by", "kim", "--target", pj.dir)[0] == 0 and run("run", "--target", pj.dir)[0] == 0
        # decisions -> not done until accepted; accept needs by/delegated; then the gate
        plan_with(RESPONSE_DECISIONS, "B")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "made 2 decision(s)" in out and "how a tag is shown" in out, out
        assert run("accept", "B", "--target", pj.dir)[0] != 0
        assert run("accept", "A", "--by", "kim", "--target", pj.dir)[0] != 0, "A made no decisions"
        assert run("accept", "B", "--delegated", "owner ok", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review task B" in out, out
        acc = dict(pj.state()["tasks"]["B"]["accepted"]); acc.pop("at", None); acc.pop("chongdae", None)
        assert acc == {"delegated": "owner ok"}
        assert run("confirm", "B", "--by", "kim", "--target", pj.dir)[0] == 0 and run("run", "--target", pj.dir)[0] == 0
        # blocked -> stop with the provider's summary; no response -> stop
        plan_with(RESPONSE_BLOCKED, "C")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "provider stopped" in out and "what done means" in out, out
        # retry: the blocked attempt stays in the record; the next call's request carries it and the tree's current diff
        assert run("retry", "A", "--by", "kim", "--target", pj.dir)[0] != 0, "A is done, nothing to retry"
        assert run("retry", "C", "--target", pj.dir)[0] != 0, "retry needs by/delegated"
        assert run("retry", "C", "--by", "kim", "--target", pj.dir)[0] == 0
        st = pj.state()["tasks"]["C"]
        ret = dict(st["attempts"][0]["retried"]); ret.pop("at", None); ret.pop("chongdae", None)
        assert "response" not in st and st["attempts"][0]["status"] == "blocked" and ret == {"by": "kim"}
        pj.fake_provider(RESPONSE_DONE)   # the same script path: the human "wrote the decision into the plan", the next call succeeds
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review task C" in out, out
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "C.request.json"), encoding="utf-8"))
        assert req["attempts"][0]["summary"] == "the contract does not say what done means" and "touched" in req
        os.remove(os.path.join(chongdae.run_dir(pj.dir), "state.json"))   # abandon C
        shutil.rmtree(chongdae.run_dir(pj.dir))
        p = {"artifact-type": "chongdae/plan@1", "goal": "g", "providers": {"implementer": [sys.executable, "-c", "pass"]},
             "tasks": [{"id": "D", "role": "implementer", "checks": [[sys.executable, "check.py"]]}]}
        write(os.path.join(pj.dir, "plan.json"), p)
        run("init", "--plan", os.path.join(pj.dir, "plan.json"), "--target", pj.dir)
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "did not finish (no-response)" in out, out


# Recorded from a real verifier run (dwitbuk eyes), trimmed.
REVIEW_REJECT = {"artifact-type": "dwitbuk/review@1", "verdict": "reject", "findings": [
    {"kind": "plan-vs-code", "where": "plan Q10 vs memo.py:clear", "record_quote": "ids of the remaining memos do not change",
     "tree_quote": "store[\"next\"] = 1", "why": "clear resets the counter, so the next id repeats an old one"}]}
REVIEW_ACCEPT = {"artifact-type": "dwitbuk/review@1", "verdict": "accept", "findings": []}


def test_verifier_before_the_gate_protected_tests_and_delegation_policy():
    with Project() as pj:
        write(os.path.join(pj.dir, "check.py"), "import sys; sys.exit(0)\n")
        write(os.path.join(pj.dir, "test_x.py"), "# the contract's test\n")
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g",
                "providers": {"implementer": pj.fake_provider(RESPONSE_DONE), "verifier": pj.fake_provider(REVIEW_REJECT, "verifier")},
                "tasks": [{"id": "S1", "role": "implementer", "gate": {"human": True, "delegate": "after-verifier"}, "tests": ["test_x.py"],
                           "checks": [[sys.executable, "check.py"]], "closes": ["Q1"]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        # the build passes its checks; the verifier says no -> the failed path, with the findings in the stop message
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "verifier rejected" in out and "clear resets the counter" in out, out
        ts = pj.state()["tasks"]["S1"]
        assert ts["rejected"]["by"] == "verifier" and ts["review"]["verdict"] == "reject" and "start" in ts
        # before asking a person, the rejected work went back to the hands on its own — twice, then the stop is a person's
        autos = [a for a in ts.get("attempts", []) if (a.get("retried") or {}).get("auto")]
        assert len(autos) == chongdae.AUTO_RESENDS and all(a["review"]["verdict"] == "reject" and a["retried"]["by"] == "chongdae" for a in autos), ts.get("attempts")
        assert "sent back to the provider automatically" in out, out
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "S1.verify.request.json")), "the verifier's request is part of the record"
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "S1.verify.request.json"), encoding="utf-8"))
        assert req["stage"] == "verify" and req["role"] == "verifier" and req["built"]["summary"] == "added count" and req["tests"] == ["test_x.py"]
        assert req["touched"] == [] and "touched_since" in req, req   # the fake provider changed nothing; a human's edits would be in touched_since
        assert run("confirm", "S1", "--by", "kim", "--target", pj.dir)[0] != 0, "nothing produced yet"
        code, out = run("status", "--target", pj.dir)
        assert code == 0 and "is running" in out and "1 open: S1" in out, out
        # retry keeps the review with the attempt; the next verifier accepts; the gate delegates only after that accept
        assert run("retry", "S1", "--by", "kim", "--target", pj.dir)[0] == 0
        ts = pj.state()["tasks"]["S1"]
        assert ts["attempts"][-1]["review"]["verdict"] == "reject" and ts["attempts"][-1]["retried"]["by"] == "kim" and "review" not in ts and "rejected" not in ts and "start" in ts   # the task keeps its start: attempts accumulate
        pj.fake_provider(REVIEW_ACCEPT, "verifier")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review task S1" in out, out
        rd = chongdae.run_dir(pj.dir)
        assert os.path.exists(os.path.join(rd, "S1.verify.request.json")) and os.path.exists(os.path.join(rd, "S1.verify.4.request.json")), os.listdir(rd)   # every verdict's files survive the retries
        assert run("confirm", "S1", "--delegated", "verifier said ok", "--target", pj.dir)[0] == 0
        cf = dict(pj.state()["tasks"]["S1"]["confirmed"]); cf.pop("at", None); cf.pop("chongdae", None)
        assert cf == {"delegated": "verifier said ok", "verifier": "accept"}
        assert run("run", "--target", pj.dir)[0] == 0
        # a build that edits the contract's tests is rejected whoever built it — here the session agent
        plan["providers"] = {"implementer": "session"}
        plan["tasks"][0]["id"] = "S2"
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        run("run", "--target", pj.dir)   # takes the start snapshot; checks already pass, so this stops... at the gate? no: tests untouched -> produced
        assert pj.state()["tasks"]["S2"]["status"] == "produced", pj.state()["tasks"]["S2"]
        run("retry", "S2", "--by", "kim", "--target", pj.dir)   # not stopped: refused
        # a fresh task whose builder touches the test file
        plan["tasks"][0]["id"] = "S3"
        plan["tasks"][0]["checks"] = [[sys.executable, "check2.py"]]
        write(os.path.join(pj.dir, "plan.json"), plan)
        shutil.rmtree(chongdae.run_dir(pj.dir))
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "make these checks pass" in out, out   # start snapshot taken here
        write(os.path.join(pj.dir, "check2.py"), "import sys; sys.exit(0)\n")
        write(os.path.join(pj.dir, "test_x.py"), "# the builder rewrote the contract's test\n")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "changed the contract's tests (test_x.py)" in out, out
        assert pj.state()["tasks"]["S3"]["rejected"]["by"] == "contract"
        subprocess.run(["git", "checkout", "--", "test_x.py"], cwd=pj.dir, check=True)
        assert run("retry", "S3", "--by", "kim", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review task S3" in out, out
        assert pj.state()["tasks"]["S3"]["touched"] == ["check2.py"], pj.state()["tasks"]["S3"]["touched"]   # measured from the task's start, not from HEAD
        # no verifier in this plan: the after-verifier gate refuses delegation; a person confirms
        code, out = run("confirm", "S3", "--delegated", "busy", "--target", pj.dir)
        assert code != 0 and "delegates only after a verifier accepts" in out, out
        assert run("confirm", "S3", "--by", "kim", "--target", pj.dir)[0] == 0


def hook(name, payload):
    done = subprocess.run([sys.executable, os.path.join(HERE, "hooks", name)], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8")
    return done.returncode, done.stdout + done.stderr


def test_add_check_argv_is_shell_quoted_not_whitespace_split():
    """A --check argument with a quoted phrase (e.g. `grep -q 'two words' file`) must keep the phrase as one
    argv token. Splitting on whitespace instead (the bug found on a real run) silently breaks the check into
    the wrong number of arguments — grep then errors on an extra positional arg, or worse, a check with a
    typo'd/impossible pattern can accidentally "pass" for the wrong reason."""
    with Project() as pj:
        write(os.path.join(pj.dir, "README.md"), "run: python3 memo.py add\n")
        assert run("init", "--session", "--goal", "check quoting", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--check", "grep -q 'python3 memo.py add' README.md", "--target", pj.dir)[0] == 0
        task = chongdae.load(os.path.join(chongdae.run_dir(pj.dir), "tasks", "T1.json"))
        assert task["def"]["checks"] == [["grep", "-q", "python3 memo.py add", "README.md"]], task["def"]["checks"]
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "1 task(s), 0 open" in out, out   # the check actually runs and passes on the real file


def test_judgments_are_notarized_as_record_only_commits_with_utc_times():
    """git is the notary: every judgment (init, confirm, close, landing) commits the run's record — and only the record —
    so a later edit of a task file is a visible diff, the committer date fixes when the judgment happened, and completed
    runs order by ancestry (`based_on`/`landed`), never by the id's clock. A dirty tree (someone's work in flight) must
    not be swept into a notary commit."""
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "code.py"), "x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()

        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        st = pj.state()
        assert st["created"]["based_on"] == base and st["created"]["at"].endswith("+00:00"), st["created"]

        write(os.path.join(pj.dir, "code.py"), "x = 2\n")   # work in flight: a notary commit must never include it
        assert run("add", "T1", "--gate", "human", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == 2   # produced, stopped at the gate
        assert run("confirm", "T1", "--by", "kim", "--target", pj.dir)[0] == 0
        assert run("close", "--target", pj.dir)[0] == 0

        log = subprocess.run(["git", "log", "--format=§%s", "--name-only"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert "init (session)" in log and "confirm T1 (by kim)" in log and "close (0 open)" in log, log
        for block in log.split("§"):   # per commit: the notary commits (run-*) carry record files only
            lines = [l for l in block.splitlines() if l.strip()]
            if lines and lines[0].startswith("run-"):
                assert all(f.startswith(".chongdae/") for f in lines[1:]), lines   # records only — code.py stays uncommitted
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "code.py"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert dirty.strip().startswith("M"), dirty   # the work in flight is still the worker's
        ts = pj.state()["tasks"]["T1"]
        assert ts["confirmed"]["at"].endswith("+00:00"), ts["confirmed"]
        # tamper-evidence: editing a task file after the fact is a visible diff against the notarized record
        tf = os.path.join(chongdae.run_dir(pj.dir), "tasks", "T1.json")
        d = chongdae.load(tf)
        d["confirmed"] = {"by": "someone-else", "at": d["confirmed"]["at"]}
        write(tf, json.dumps(d))
        diff = subprocess.run(["git", "diff", "--stat"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert "T1.json" in diff, diff


def test_a_landed_worktree_run_records_the_merge_commit():
    """`landed` pins the merge commit into the record in main: run order among completed runs is git ancestry."""
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "code.py"), "x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        assert run("init", "--session", "--goal", "g", "--worktree", "--target", pj.dir)[0] == 0
        wt_root = os.path.join(pj.dir, ".chongdae", "wt")
        wt_path = os.path.join(wt_root, os.listdir(wt_root)[0])   # the record lives in the worktree's branch until it lands
        write(os.path.join(wt_path, "code.py"), "x = 2\n")
        assert run("add", "T1", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", wt_path)[0] == 0
        assert run("run", "--target", wt_path)[0] == 0
        code, out = run("close", "--target", wt_path)
        assert code == 0, out
        st = pj.state()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()
        assert st.get("landed", {}).get("commit"), st
        # the landing judgment is itself notarized after the merge, so `landed` names the merge commit, an ancestor of HEAD
        anc = subprocess.run(["git", "merge-base", "--is-ancestor", st["landed"]["commit"], head], cwd=pj.dir)
        assert anc.returncode == 0, (st["landed"], head)


def test_performed_by_is_recorded_like_an_author_line():
    """Every produced task records who did it: a session task gets the host's self-identification from the env
    (AI_AGENT = host_version_kind; the host's session id, which is the key into the host's own log where the model
    is recorded), a command-provider task gets the provider argv. A run without this cannot be attributed later."""
    keys = ("AI_AGENT", "CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ID", "AGENT_HOST", "CODEX_THREAD_ID", "CODEX_VERSION", "HUNSU_CODEX_DIR")
    saved = {k: os.environ.pop(k, None) for k in keys}   # the host running this test sets these too; own them all
    try:
        with Project() as pj:
            os.environ["AI_AGENT"] = "claude-code_9-9-9_agent"
            os.environ["CLAUDE_EFFORT"] = "high"
            os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-123"
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
            assert run("run", "--target", pj.dir)[0] == 0
            ts = pj.state()["tasks"]["T1"]
            assert ts["performed_by"] == {"provider": "session", "host": "claude-code", "agent": "claude-code_9-9-9_agent", "effort": "high", "session": "sess-123",
                                          "model-unknown": "no transcript for this session on this host (no SessionStart record here, none under the host's projects)",
                                          "versions": {"used": {"chongdae": chongdae.engine().split(" ", 1)[1]}}}, ts["performed_by"]
            # the session is this machine's: the committed task file does not name it, the local part does
            rd = chongdae.run_dir(pj.dir)
            assert "sess-123" not in open(os.path.join(rd, "tasks", "T1.json"), encoding="utf-8").read()
            assert "sess-123" in open(os.path.join(rd, "local", "tasks", "T1.json"), encoding="utf-8").read()
        with Project() as pj:
            # a Codex session started from a Claude Code shell sees both hosts' markers: the products' AGENT_HOST decides, and the
            # model comes from the rollout Codex keeps for the thread — never from the ancestor's AI_AGENT
            os.environ["AGENT_HOST"], os.environ["CODEX_THREAD_ID"], os.environ["CODEX_VERSION"] = "codex", "thread-1", "0.155.0"
            os.environ["HUNSU_CODEX_DIR"] = os.path.join(pj.dir, "codex-home")
            write(os.path.join(pj.dir, "codex-home", "sessions", "2026", "rollout-2026-thread-1.jsonl"),
                  json.dumps({"type": "session_meta", "payload": {}}) + "\n" + json.dumps({"type": "turn_context", "payload": {"model": "gpt-test", "effort": None}}) + "\n")
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
            assert run("run", "--target", pj.dir)[0] == 0
            assert pj.state()["tasks"]["T1"]["performed_by"] == {"provider": "session", "host": "codex", "agent": "codex_0.155.0", "session": "thread-1", "model": "gpt-test",
                                                                   "versions": {"used": {"chongdae": chongdae.engine().split(" ", 1)[1]}}}, pj.state()["tasks"]["T1"]["performed_by"]
            del os.environ["AGENT_HOST"], os.environ["CODEX_THREAD_ID"], os.environ["CODEX_VERSION"], os.environ["HUNSU_CODEX_DIR"]
        with Project() as pj:
            del os.environ["CLAUDE_EFFORT"]   # unset -> absent, never an empty field
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            # the model is not in the env; the SessionStart hook records where the host keeps the transcript, and the transcript names it
            transcript = os.path.join(pj.dir, "host-transcript.jsonl")
            hook = os.path.join(HERE, "hooks", "session_start.py")
            done = subprocess.run([sys.executable, hook], input=json.dumps({"cwd": pj.dir, "session_id": "sess-123", "transcript_path": transcript, "source": "startup"}),
                                  capture_output=True, text=True, encoding="utf-8")
            assert done.returncode == 0 and os.path.exists(os.path.join(pj.dir, ".chongdae", "sessions", "sess-123.json")), done.stderr
            assert io.open(os.path.join(pj.dir, ".chongdae", "sessions", ".gitignore")).read() == "*\n"   # machine-local: ignores itself
            assert run("add", "T1", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
            io.open(transcript, "w", encoding="utf-8").write(json.dumps({"type": "user", "message": {}}) + "\n" + json.dumps({"type": "assistant", "message": {"model": "claude-test-1"}}) + "\n")
            assert run("run", "--target", pj.dir)[0] == 0
            pb = pj.state()["tasks"]["T1"]["performed_by"]
            assert pb["model"] == "claude-test-1" and pb["host"] == "claude-code" and "effort" not in pb and "model-unknown" not in pb, pb
            # a session the host did not persist: the record says so instead of guessing
            os.remove(transcript)
            assert run("add", "T2", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
            assert run("run", "--target", pj.dir)[0] == 0
            assert pj.state()["tasks"]["T2"]["performed_by"]["model-unknown"] .startswith("no transcript for this session on this host")
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    with Project() as pj:
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "kind": "slice",
                "providers": {"builder": pj.fake_provider(RESPONSE_DONE)},
                "tasks": [{"id": "T1", "role": "builder", "needs": [], "checks": [[sys.executable, "-c", "raise SystemExit(0)"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == 0
        ts = pj.state()["tasks"]["T1"]
        assert ts["performed_by"]["provider"] == "command" and "provider.py" in " ".join(ts["performed_by"]["argv"]), ts["performed_by"]
        assert "model" not in ts["performed_by"], "a provider that says nothing about itself gets nothing invented"
    with Project() as pj:
        # a worker's own account of its call (`worker` in the response) becomes part of the author line, verifier included
        worker = {"host": "claude-code", "model": "claude-test-2", "turns": 7, "cost_usd": 0.12, "session": "w-1", "transcript": "T1.response.transcript.jsonl"}
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "kind": "slice",
                "providers": {"builder": pj.fake_provider(dict(RESPONSE_DONE, worker=worker)),
                              "verifier": pj.fake_provider({"artifact-type": "dwitbuk/review@1", "verdict": "accept", "findings": [], "worker": dict(worker, model="claude-eyes", turns=3)}, name="eyes")},
                "tasks": [{"id": "T1", "role": "builder", "needs": [], "checks": [[sys.executable, "-c", "raise SystemExit(0)"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        run("run", "--target", pj.dir)
        ts = pj.state()["tasks"]["T1"]
        assert ts["performed_by"]["model"] == "claude-test-2" and ts["performed_by"]["turns"] == 7 and ts["performed_by"]["transcript"] == "T1.response.transcript.jsonl", ts["performed_by"]
        assert ts["verified_by"]["provider"] == "command" and ts["verified_by"]["model"] == "claude-eyes" and ts["verified_by"]["turns"] == 3, ts.get("verified_by")


def test_provider_survives_the_runner_and_a_second_run_consumes_its_response():
    """The provider is detached with a pending record. If the `run` that spawned it dies, the provider keeps
    working; the next `chongdae run` finds the pending pid (or the response it already wrote) and does NOT
    spawn a second provider — the work is paid for once. Seen live: two sessions backgrounded `run` and exited,
    killing their providers mid-build."""
    with Project() as pj:
        # a slow provider: takes ~4s, then writes a marker of how many times it ran plus a valid response
        marker = os.path.join(pj.dir, "runs.txt")
        script = os.path.join(pj.dir, "slow_provider.py")
        write(script, "import json, sys, time\ntime.sleep(4)\n"
                      "open(%r, 'a').write('x')\n"
                      "json.dump({'status': 'done', 'summary': 's', 'verified': [], 'decisions': [], 'non-claims': []}, open(sys.argv[2], 'w'))\n" % marker)
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "kind": "slice", "providers": {"builder": [sys.executable, script, "{request}", "{response}"]},
                "tasks": [{"id": "T1", "role": "builder", "needs": [], "checks": [[sys.executable, "-c", "raise SystemExit(0)"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        # first `run` is killed 1s in — after the provider is spawned+detached, before it answers
        runner = subprocess.Popen([sys.executable, os.path.join(HERE, "chongdae.py"), "run", "--target", pj.dir],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time
        time.sleep(1.5)
        runner.kill(); runner.wait()
        d = chongdae.run_dir(pj.dir)
        assert os.path.exists(os.path.join(d, "T1.pending.json")), "the pending record survives the dead runner"
        # second `run` resumes the SAME provider (waits for it) instead of spawning another
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        assert io.open(marker, encoding="utf-8").read() == "x", "the provider ran once, not twice"
        assert not os.path.exists(os.path.join(d, "T1.pending.json")), "consumed pending is cleaned up"
        st = pj.state()
        assert st["tasks"]["T1"]["status"] == "done" and st["tasks"]["T1"]["response"]["status"] == "done"


def test_recheck_skips_its_own_recursion():
    """A completed merge run's check is `chongdae recheck` itself. recheck (and close's merge-back recheck)
    must skip that check instead of re-running it — re-running recurses without end (seen live: 231 processes)."""
    assert chongdae.is_self_recheck(["python3", "{plugin:chongdae}/chongdae.py", "recheck"])
    assert chongdae.is_self_recheck(["python", "/x/chongdae/chongdae.py", "recheck"])
    assert not chongdae.is_self_recheck(["python3", "test_memo.py"])
    assert not chongdae.is_self_recheck(["python3", "{plugin:mangsang}/mangsang.py", "impact"])
    with Project() as pj:
        write(os.path.join(pj.dir, "ok.py"), "")
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--check", sys.executable + " ok.py", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == 0
        assert run("close", "--target", pj.dir)[0] == 0
        # a fake completed merge run whose only check is chongdae's own recheck
        d = os.path.join(pj.dir, chongdae.RUNS, "run-99999999-999999-ffff")
        write(os.path.join(d, "plan.json"), {"artifact-type": "chongdae/plan@1", "goal": "merge", "kind": "merge",
                                             "tasks": [{"id": "merge", "role": "merger", "needs": [], "checks": [["python3", "{plugin:chongdae}/chongdae.py", "recheck"]]}]})
        write(os.path.join(d, "state.json"), {"artifact-type": "chongdae/run@1", "status": "complete", "tasks": {"merge": {"status": "done"}}})
        code, out = run("recheck", "--target", pj.dir)   # would hang forever before the fix
        assert code == 0 and "no checks" in out and "run-99999999-999999-ffff/merge" in out, out


def test_worktree_run_merges_back_and_a_conflict_becomes_a_decision():
    """--worktree: init makes a worktree+branch, close commits it, merges into main (green recheck) and removes it.
    A conflicting main commit turns close into a decision (exit 2) and the worktree survives for the merge run."""
    def git(cwd, *a):
        subprocess.run(["git", *a], cwd=cwd, capture_output=True, check=False)

    with Project() as pj:
        git(pj.dir, "config", "user.email", "t@t")
        git(pj.dir, "config", "user.name", "t")
        write(os.path.join(pj.dir, "a.txt"), "base\n")
        git(pj.dir, "add", "-A"); git(pj.dir, "commit", "-qm", "base")
        # happy path: work in the worktree, close merges back
        code, out = run("init", "--session", "--goal", "wt", "--worktree", "--target", pj.dir)
        assert code == 0 and "worktree" in out, out
        wt = os.path.join(pj.dir, chongdae.RUNS, "wt", os.listdir(os.path.join(pj.dir, chongdae.RUNS, "wt"))[0])
        assert run("add", "T1", "--brief", "b", "--target", wt)[0] == 0
        write(os.path.join(wt, "b.txt"), "new\n")
        assert run("run", "--target", wt)[0] == 0
        code, out = run("close", "--target", wt)
        assert code == 0 and "merged" in out and "recheck green" in out, out
        assert os.path.exists(os.path.join(pj.dir, "b.txt")), "the work landed in main"
        assert not os.path.isdir(wt), "the worktree is gone after a clean merge"
        # conflict path: main moves the same file the worktree edits
        code, out = run("init", "--session", "--goal", "wt2", "--worktree", "--target", pj.dir)
        assert code == 0, out
        wt2 = os.path.join(pj.dir, chongdae.RUNS, "wt", os.listdir(os.path.join(pj.dir, chongdae.RUNS, "wt"))[0])
        assert run("add", "T1", "--brief", "b", "--target", wt2)[0] == 0
        write(os.path.join(wt2, "a.txt"), "from the run\n")
        write(os.path.join(pj.dir, "a.txt"), "from main\n")
        git(pj.dir, "add", "-A"); git(pj.dir, "commit", "-qm", "main moved")
        assert run("run", "--target", wt2)[0] == 0
        code, out = run("close", "--target", wt2)
        assert code == chongdae.DECISION and "conflicts" in out and "init --merge" in out, out
        assert os.path.isdir(wt2), "the worktree stays for the merge run"
        # the write gate re-anchors inside a worktree: from main's cwd a path under .chongdae/wt/<run>/ is that worktree's project
        # file, judged by that worktree's run state — not waved through by main's exempt `.chongdae/` prefix
        code, out = hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": os.path.join(wt2, "c.py")}})
        assert code == 2 and "no run in progress" in out, "wt2's run was closed above: a write into it is refused like any project write with no run"
        git(pj.dir, "checkout", "-q", "--", "a.txt")
        code, out = run("init", "--goal", "boot", "--worktree", "--target", pj.dir)
        assert code == 0, out
        wt3 = [os.path.join(pj.dir, chongdae.RUNS, "wt", n) for n in os.listdir(os.path.join(pj.dir, chongdae.RUNS, "wt")) if n not in os.path.basename(wt2)][-1]
        write(os.path.join(wt3, "plan", "questions.json"), [])   # complete the bootstrap's first task badly enough to stop it running: state stays running
        code, out = hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": os.path.join(wt3, "d.py")}})
        assert code == 0, "a bootstrap run is running in wt3: allowed"
        assert hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": os.path.join(wt3, ".chongdae", "note.json")}})[0] == 0, "the worktree's own record is exempt"
        # a plan (non-session) worktree run has its way back: `run` completes it, `close` merges it
        code, out = run("close", "--target", wt3)
        assert code != 0 and "`chongdae run` completes it, then `close` merges" in out, out
        # --base: two independent slices branch from the same commit, not from whatever HEAD is now
        base = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=pj.dir, capture_output=True, text=True, encoding="utf-8").stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True, encoding="utf-8").stdout.strip()
        assert base and base != head
        code, out = run("init", "--session", "--goal", "from base", "--worktree", "--base", base, "--target", pj.dir)
        assert code == 0, out
        wt4 = out.split("--target ")[-1].strip()
        assert chongdae.load_state(chongdae.run_dir(wt4))["created"]["based_on"] == base, "the record says what it branched from"   # HEAD itself is one record commit past it
        assert io.open(os.path.join(wt4, "a.txt")).read() == "base\n" and io.open(os.path.join(pj.dir, "a.txt")).read() != "base\n"


def test_a_plan_from_stdin_in_a_worktree_completes_and_close_merges_it_back():
    """`init --plan -` reads the plan from stdin: the plan is intent written before its run exists, so the write gate would
    refuse it in the tree and a file elsewhere was the workaround. A plan run in a worktree ends by `run` (complete) and
    `close` is its way back to main — before, only session runs could return."""
    def git(cwd, *a):
        subprocess.run(["git", *a], cwd=cwd, capture_output=True, check=False)

    with Project() as pj:
        git(pj.dir, "config", "user.email", "t@t"); git(pj.dir, "config", "user.name", "t")
        write(os.path.join(pj.dir, "a.txt"), "base\n"); git(pj.dir, "add", "-A"); git(pj.dir, "commit", "-qm", "base")
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "kind": "slice", "providers": {"builder": pj.fake_provider(RESPONSE_DONE)},
                "tasks": [{"id": "T1", "role": "builder", "needs": [], "checks": [[sys.executable, "-c", "raise SystemExit(0)"]]}]}
        stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(plan))
        try:
            code, out = run("init", "--plan", "-", "--worktree", "--target", pj.dir)
        finally:
            sys.stdin = stdin
        assert code == 0 and "worktree" in out, out
        wt = os.path.join(pj.dir, chongdae.RUNS, "wt", os.listdir(os.path.join(pj.dir, chongdae.RUNS, "wt"))[0])
        assert json.load(open(os.path.join(chongdae.run_dir(wt), "plan.json")))["goal"] == "g", "the run keeps the only copy that matters"
        code, out = run("close", "--target", wt)
        assert code != 0 and "`chongdae run` completes it" in out, out
        write(os.path.join(wt, "b.txt"), "built\n")
        assert run("run", "--target", wt)[0] == 0 and chongdae.load_state(chongdae.run_dir(wt))["status"] == "complete"
        code, out = run("close", "--target", wt)
        assert code == 0 and "merged" in out, out
        assert os.path.exists(os.path.join(pj.dir, "b.txt")) and not os.path.isdir(wt)
        sys.stdin = io.StringIO("not json")
        try:
            code, out = run("init", "--plan", "-", "--target", pj.dir)
        finally:
            sys.stdin = stdin
        assert code != 0 and "stdin is not JSON" in out, out


def test_a_session_task_can_be_handed_to_the_locked_implementer():
    """A session run's tasks are the session's own by default (`role: session`); `add --role implementer` hands one to the
    lock's implementer — a fresh process — inside the same run. Before, `init --session` overrode the lock with `session`,
    so the locked hands could only be used from a separate plan run."""
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE)}})
        write(os.path.join(pj.dir, "plan", "PLAN.md"), "# plan\n\n## Q-add\n\n`add` appends one item.\n\n## Q-list\n\nlists them.\n")
        assert run("init", "--session", "--goal", "g", "--from", "plan/PLAN.md", "--target", pj.dir)[0] == 0
        assert run("add", "mine", "--brief", "the session does this", "--target", pj.dir)[0] == 0
        assert run("add", "theirs", "--role", "implementer", "--brief", "a fresh process does this", "--closes", "Q-add", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        tasks = pj.state()["tasks"]
        assert tasks["mine"]["status"] == "done" and tasks["mine"]["performed_by"]["provider"] == "session"
        assert tasks["theirs"]["status"] == "done" and tasks["theirs"]["performed_by"]["provider"] == "command" and tasks["theirs"]["response"]["status"] == "done", tasks["theirs"]
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "theirs.request.json")))
        assert req["contract"] == {"Q-add": "## Q-add\n\n`add` appends one item."}, "a session run's --from names the document whose sections are the contract"
        assert run("add", "nobody", "--role", "modeler", "--brief", "no such provider", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "role 'modeler' has no provider" in out, out


def test_a_native_provider_is_dispatched_by_the_session_and_its_answer_consumed_as_a_providers():
    """`native:` providers: the host's own subagent does the work, dispatched by the session. chongdae writes the request as for
    a worker, then stops with the dispatch instruction (the worker's `--prompt-only` argv, the response path); the session runs
    the subagent, writes its JSON answer verbatim where a worker would, and `run` consumes it — attributed `native`, with the
    session on record as the relay and a non-claim that chongdae never saw the subagent. Asked again before the answer: the
    same instruction, no new request."""
    with Project() as pj:
        worker = os.path.join(pj.dir, "worker.py")
        write(worker, "import sys\nif '--prompt-only' in sys.argv:\n    print('THE PROMPT for ' + sys.argv[sys.argv.index('--request') + 1])\nelse:\n    raise SystemExit('a native provider never runs the worker')\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": {"native": [sys.executable, worker, "--request", "{request}", "--response", "{response}"]}}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--role", "implementer", "--brief", "b", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "session agent: dispatch T1" in out and "--prompt-only" in out and "VERBATIM" in out, out
        d = chongdae.run_dir(pj.dir)
        req, res = os.path.join(d, "T1.request.json"), os.path.join(d, "T1.response.json")
        assert os.path.exists(req) and not os.path.exists(res) and chongdae.load(os.path.join(d, "T1.pending.json")).get("native")
        # the prompt the instruction names is the worker's own
        argv = [a.strip('"') for a in out.split("get the prompt with `")[1].split("`")[0].split(" ")]
        assert subprocess.run(argv, capture_output=True, text=True).stdout.strip() == "THE PROMPT for " + req
        code2, out2 = run("run", "--target", pj.dir)
        assert code2 == chongdae.DECISION and out2.split("decision:")[-1] == out.split("decision:")[-1], "asked again: the same instruction"
        # a blocked answer, retried: the attempt's files move aside so the next `run` dispatches again instead of re-reading them
        write(res, {"status": "blocked", "summary": "the contract is silent on x", "verified": [], "decisions": [{"what": "x", "chosen": "?", "alternatives": []}], "non-claims": []})
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "the provider stopped" in out, out
        assert run("retry", "T1", "--delegated", "test", "--target", pj.dir)[0] == 0
        assert not os.path.exists(res) and os.path.exists(os.path.join(d, "T1.response.1.json")) and os.path.exists(os.path.join(d, "T1.request.1.json")), os.listdir(d)
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "session agent: dispatch T1" in out, out
        write(res, dict(RESPONSE_DONE, worker={"host": "claude-code", "model": "claude-native-1"}))
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        ts = pj.state()["tasks"]["T1"]
        pb = ts["performed_by"]
        assert ts["status"] == "done" and pb["provider"] == "native" and pb["model"] == "claude-native-1" and pb["argv"][1] == worker, pb
        assert pb["relayed_by"]["provider"] == "session", pb
        assert len(ts["attempts"]) == 1 and ts["attempts"][0]["status"] == "blocked"
        assert any("native subagent" in n for n in ts.get("non-claims", [])), ts.get("non-claims")
        assert not os.path.exists(os.path.join(d, "T1.pending.json"))


def test_people_hired_before_and_after_a_task_answer_with_findings_the_record_keeps():
    """`before` roles (a quibbler) run before any hands move: findings are plan questions, so the task waits until a human
    `accept`s them; an empty answer lets the work through. `after` roles (a newbie) run once the checks pass, before the
    gate; their findings go to the record and the report, never a verdict. A role with no provider is a non-claim."""
    QUIBBLE = {"status": "done", "summary": "two open", "non-claims": [],
               "findings": [{"kind": "undecided", "where": "Q-add", "quote": "`add` appends.", "why": "empty text?"},
                            {"kind": "unchecked", "where": "brief", "quote": "every test passes", "why": "no check selects all"}]}
    NEWBIE = {"status": "done", "summary": "tried it", "non-claims": [], "tried": [],
              "findings": [{"kind": "unclear", "quote": "# todo", "observed": "nothing to type", "why": "the README has no command"}]}
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"quibble": pj.fake_provider(QUIBBLE, name="sibi"), "newbie": pj.fake_provider(NEWBIE, name="chojja")}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--brief", "b", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--before", "quibble", "modeler", "--after", "newbie", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "quibble found 2 thing(s)" in out and "undecided @ Q-add: empty text? — “`add` appends.”" in out, out
        ts = pj.state()["tasks"]["T1"]
        assert ts["stages"]["quibble"]["response"]["findings"][0]["kind"] == "undecided" and ts["stages"]["quibble"]["by"]["provider"] == "command" and ts["stages"]["quibble"]["when"] == "before"
        assert ts["status"] == "todo" and "response" not in ts, "the hands did not move"
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "T1.quibble.request.json"))
        assert json.load(open(os.path.join(chongdae.run_dir(pj.dir), "T1.quibble.request.json")))["role"] == "quibble"
        code2, out2 = run("run", "--target", pj.dir)
        assert code2 == chongdae.DECISION and "quibble found 2" in out2, "asked again: still waiting, not re-run"
        assert run("accept", "T1", "--target", pj.dir)[0] != 0, "who accepted?"
        code, out = run("accept", "T1", "--by", "kim", "--target", pj.dir)
        assert code == 0 and "accepted 2 finding(s) from quibble on T1" in out, out
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        ts = pj.state()["tasks"]["T1"]
        assert ts["status"] == "done" and ts["stages"]["quibble"]["accepted"]["by"] == "kim"
        assert ts["stages"]["modeler"] == {"skipped": "no provider"} and any("no provider for role 'modeler' (before)" in n for n in ts["non-claims"]), ts
        assert ts["stages"]["newbie"]["when"] == "after" and ts["stages"]["newbie"]["response"]["findings"][0]["kind"] == "unclear"
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "T1.newbie.request.json"))
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "T1.newbie.request.json")))
        assert req["role"] == "newbie" and "touched" in req and "built" in req
        # the report: both stages' findings, and the acceptance if it was delegated
        code, out = run("report", "--target", pj.dir)
        doc = json.loads(out[out.index("{"):])
        sf = [f for f in doc["findings"] if f["kind"] == "stage-finding"]
        assert len(sf) == 3 and any("(quibble, before)" in f["where"] for f in sf) and any("(newbie, after)" in f["where"] and "the README has no command" in f["text"] for f in sf), sf
    with Project() as pj:
        # a stage answer that did not finish is not an answer: kept under `failed`, the role is asked again on the next run
        # (seen live: every hacheong member came back `failed` on a validator that mistook its own transcript for a tree change)
        flaky = os.path.join(pj.dir, "flaky.py")
        write(flaky, "import json, os, sys\nn = os.path.join(os.path.dirname(sys.argv[2]), 'flaky.count')\nk = int(open(n).read()) if os.path.exists(n) else 0\nopen(n, 'w').write(str(k + 1))\n"
                     "json.dump({'status': 'failed' if k == 0 else 'done', 'summary': 'try %d' % k, 'non-claims': ['validator x'] if k == 0 else [], 'findings': []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"quibble": [sys.executable, flaky, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--brief", "b", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--before", "quibble", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "quibble (before) did not finish (failed: validator x)" in out and "asks again" in out, out
        st = pj.state()["tasks"]["T1"]["stages"]["quibble"]
        assert "response" not in st and len(st["failed"]) == 1 and st["failed"][0]["response"]["status"] == "failed"
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        st = pj.state()["tasks"]["T1"]["stages"]["quibble"]
        assert st["response"]["status"] == "done" and len(st["failed"]) == 1, "the failed try stays in the record next to the answer"
    with Project() as pj:
        # a role that cannot work on this task comes off it, with the reason: the task goes on, the record says the role did not look
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"newbie": [sys.executable, "-c", "import json,sys; json.dump({'status': 'failed', 'summary': 'no README', 'non-claims': ['readme-only: nothing a newbie can read'], 'findings': []}, open(sys.argv[2], 'w'))", "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--brief", "b", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--after", "newbie", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "chongdae unstage T1 newbie --why WHY" in out, out
        assert run("unstage", "T1", "quibble", "--why", "x", "--target", pj.dir)[0] != 0, "not hired on T1"
        code, out = run("unstage", "T1", "newbie", "--why", "the project has no README yet", "--by", "kim", "--target", pj.dir)
        assert code == 0, out
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        ts = pj.state()["tasks"]["T1"]
        assert ts["status"] == "done" and ts["unstaged"]["newbie"]["by"] == "kim" and "newbie" not in ts.get("stages", {})
        assert any("newbie did not look at this task (taken off: the project has no README yet)" in n for n in ts["non-claims"]), ts["non-claims"]
    with Project() as pj:
        # an empty quibble lets the work through; a plan's `stages` are the defaults for tasks that say neither; the shape check refuses junk
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"quibble": pj.fake_provider(dict(QUIBBLE, findings=[]), name="sibi")}})
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "kind": "slice", "stages": {"before": ["quibble"]}, "providers": {"builder": pj.fake_provider(RESPONSE_DONE)},
                "tasks": [{"id": "T1", "role": "builder", "needs": [], "checks": [[sys.executable, "-c", "raise SystemExit(0)"]]},
                          {"id": "T2", "role": "builder", "needs": ["T1"], "before": [], "checks": [[sys.executable, "-c", "raise SystemExit(0)"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        tasks = pj.state()["tasks"]
        assert tasks["T1"]["stages"]["quibble"]["response"]["findings"] == [] and "stages" not in tasks["T2"], "T2 opted out of the plan's default"
        assert chongdae.plan_problems({"artifact-type": "chongdae/plan@1", "goal": "g", "stages": {"during": []}, "tasks": [{"id": "x", "role": "r", "checks": [["x"]], "before": "quibble"}]}) == [
            "x: `before` is a list of role names (people the plan hires around this task: [\"quibble\"], [\"newbie\"])",
            "`stages` is {\"before\": [roles], \"after\": [roles]} — the plan's defaults for tasks that say neither"]


def test_a_disputed_contract_test_goes_back_to_its_writer_and_the_build_goes_out_again():
    """The builder says a contract test contradicts the contract. Nobody edits the test by hand between attempts: the task
    that wrote it is reopened with the dispute (`amending` in its request), rewrites it, the build re-baselines that file
    (so the rewrite is not read as the build changing its tests) and goes out again — all inside `run`."""
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        writer = os.path.join(pj.dir, "writer.py")
        write(writer, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\nroot = os.path.dirname(os.path.abspath(sys.argv[1]))\n"
                      "open(os.path.join(req['target'], 'test_a.py'), 'w').write('# amended\\n' if req.get('amending') else '# wrong fixture\\n')\n"
                      "json.dump({'status': 'done', 'summary': 'amended' if req.get('amending') else 'wrote', 'non-claims': [], 'tests': ['test_a.py']}, open(sys.argv[2], 'w'))\n")
        builder = os.path.join(pj.dir, "builder.py")
        write(builder, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\n"
                       "wrong = open(os.path.join(req['target'], 'test_a.py')).read().startswith('# wrong')\n"
                       "json.dump({'status': 'blocked' if wrong else 'done', 'summary': 'disputed' if wrong else 'built', 'verified': [], 'decisions': [], 'non-claims': [],\n"
                       "           'disputed-tests': [{'test': 'test_a.py::test_x', 'contract_quote': 'Q', 'why': 'fixture breaks Q'}] if wrong else []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": [sys.executable, writer, "{request}", "{response}"],
                                                                  "implementer": [sys.executable, builder, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "tests", "--role", "nitpick", "--tests", "test_a.py", "--target", pj.dir)[0] == 0
        assert run("add", "build", "--role", "implementer", "--tests", "test_a.py", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "reopened with the dispute" in out, out
        rd = chongdae.run_dir(pj.dir)
        st = pj.state()["tasks"]
        assert st["tests"]["status"] == "done" and st["tests"]["attempts"][0]["disputed-tests"][0]["why"] == "fixture breaks Q", st["tests"]
        assert json.load(open(os.path.join(rd, "tests.request.json")))["amending"][0]["test"] == "test_a.py::test_x"
        assert json.load(open(os.path.join(rd, "tests.request.1.json")))["checks"] == [[sys.executable, "-c", "raise SystemExit(0)"]], "the writer's request carries the build's check"
        assert st["build"]["status"] == "done" and st["build"]["rebaselined"][0]["tests"] == ["test_a.py"], st["build"]
        assert str(st["build"]["attempts"][0]["retried"]["auto"]).startswith("tests disputed"), st["build"]["attempts"]
        assert open(os.path.join(pj.dir, "test_a.py")).read() == "# amended\n"


def test_a_session_tasks_done_carries_what_the_session_did_in_its_window():
    """A session task without a check is done on the agent's word. The host keeps a transcript; the SessionStart hook said
    where. The task's trace is cut from it at the time the task was added: what the session actually ran and changed for it."""
    keys = ("CLAUDE_CODE_SESSION_ID", "AGENT_HOST", "AI_AGENT", "CLAUDE_EFFORT")
    old = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-1"
        with Project() as pj:
            tr = os.path.join(pj.dir, "sess-1.jsonl")
            write(os.path.join(pj.dir, chongdae.RUNS, "sessions", "sess-1.json"), {"transcript": tr})
            before = {"type": "assistant", "timestamp": "2000-01-01T00:00:00Z", "message": {"model": "m", "content": [{"type": "tool_use", "id": "t0", "name": "Bash", "input": {"command": "echo earlier work"}}]}}
            write(tr, json.dumps(before) + "\n")
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--brief", "b", "--target", pj.dir)[0] == 0
            after = {"type": "assistant", "timestamp": "2999-01-01T00:00:00Z", "cwd": pj.dir, "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "python3 build.py"}},
                {"type": "tool_use", "id": "t2", "name": "Write", "input": {"file_path": os.path.join(pj.dir, "NOTES.md")}}]}}
            # the same session also worked somewhere else: that stays out of this project's record
            other = {"type": "assistant", "timestamp": "2999-01-01T00:00:01Z", "cwd": "/somewhere/else", "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "grep secret notes.txt"}}]}}
            with open(tr, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(after) + "\n" + json.dumps(other) + "\n")
            assert run("run", "--target", pj.dir)[0] == 0
            trace = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "T1.session.trace.json"), encoding="utf-8"))
            assert trace["commands-run"] == 1 and "commands" not in trace and trace["changed"] == ["write ./NOTES.md"], trace   # lines stay local
            assert "session" not in trace["worker"] and trace["worker"]["model"] == "m", trace   # the session is this machine's (local/)
            assert "secret" not in json.dumps(trace) and trace["elsewhere"].startswith("1 command"), trace
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_a_plugin_resolves_to_the_copy_this_project_declares_not_the_first_install_record():
    """Install records are per project. The first record with a plugin's name may be another project's old copy (a site's
    builds once ran another project's 1.0.0 workers that way); the copy is the one from the marketplace hunsu.json declares
    — or `hunsu dev`'s local one — installed for this project, and a directory marketplace's is its source, loaded in place."""
    with Project() as pj:
        home = os.path.join(pj.dir, "claude-home")
        other = os.path.join(pj.dir, "elsewhere")
        write(os.path.join(home, "plugins", "installed_plugins.json"), {"plugins": {
            "w@oldmarket": [{"scope": "project", "projectPath": other, "installPath": "/old/w/1.0.0"}],
            "w@pub": [{"scope": "project", "projectPath": pj.dir, "installPath": "/pub/w/1.2.0"}]}})
        devsrc = os.path.join(pj.dir, "devmarket")
        os.makedirs(os.path.join(devsrc, "w"))
        write(os.path.join(home, "plugins", "known_marketplaces.json"), {"devm": {"source": {"source": "directory", "path": devsrc}}})
        write(os.path.join(pj.dir, "hunsu.json"), {"plugins": {"w": {"marketplace": "pub", "version": "1.2.0"}}})
        old = os.environ.get("HUNSU_CLAUDE_DIR"); os.environ["HUNSU_CLAUDE_DIR"] = home
        try:
            assert chongdae.plugin_root(pj.dir, "w") == "/pub/w/1.2.0"
            write(os.path.join(pj.dir, "hunsu.local.json"), {"dev": {"w": "devm"}})
            assert chongdae.plugin_root(pj.dir, "w") == os.path.join(devsrc, "w"), "in development: the source, in place"
            write(os.path.join(pj.dir, "hunsu.local.json"), {})
            write(os.path.join(pj.dir, "hunsu.json"), {"plugins": {"w": {"marketplace": "gone"}}})
            try:
                chongdae.plugin_root(pj.dir, "w"); assert False, "declared but not installed for this project must not fall back to another's"
            except SystemExit as err:
                assert "not installed for it here" in str(err)
        finally:
            os.environ.pop("HUNSU_CLAUDE_DIR") if old is None else os.environ.__setitem__("HUNSU_CLAUDE_DIR", old)


def test_the_record_carries_what_replays_a_run_and_nothing_of_this_machine():
    """A reader elsewhere needs the contract, who did it with which versions, what changed and what was judged. Not this
    machine's sessions, snapshots of unrelated files, interpreter leftovers or home paths — those stay in <run>/local/."""
    home = os.path.expanduser("~")
    with Project() as pj:
        os.environ["CHONGDAE_USER"] = "kim"
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-local"
        try:
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE)}})
            write(os.path.join(pj.dir, "unrelated.png"), "not this run's\n")   # dirt before the run: nobody's business
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            # a check given with this machine's paths is recorded portably, and still runs here
            plugin_check = "%s/.claude/plugins/cache/m/mangsang/1.5.0/mangsang.py" % home
            assert run("add", "T1", "--check", "python3 -c pass " + plugin_check + " " + home + "/x", "--target", pj.dir)[0] == 0
            ts = pj.state()["tasks"]["T1"]
            assert ts["def"]["checks"] == [["python3", "-c", "pass", "{plugin:mangsang}/mangsang.py", "~/x"]], ts["def"]["checks"]
            assert chongdae.resolve_argv(pj.dir, ["~/x"]) == [home + "/x"]
            write(os.path.join(pj.dir, "a.py"), "x = 1\n")
            write(os.path.join(pj.dir, "__pycache__", "a.cpython-312.pyc"), "bytecode")
            assert run("run", "--target", pj.dir)[0] == 0
            rd = chongdae.run_dir(pj.dir)
            task_file = open(os.path.join(rd, "tasks", "T1.json"), encoding="utf-8").read()
            task = json.loads(task_file)
            assert task["touched"] == ["a.py"], task["touched"]   # neither the interpreter's leftovers nor the dirt before
            assert "start" not in task and "sess-local" not in task_file and home not in task_file and "unrelated.png" not in task_file, task_file
            assert task["written_by"] == chongdae.engine() and task["performed_by"]["versions"]["used"]["chongdae"] == chongdae.engine().split(" ", 1)[1]
            local = json.load(open(os.path.join(rd, "local", "tasks", "T1.json"), encoding="utf-8"))
            assert "unrelated.png" in local["start"] and local["performed_by"]["session"] == "sess-local", local
            assert pj.state()["tasks"]["T1"]["performed_by"]["session"] == "sess-local", "the engine still reads its own machine's part"
            for name in os.listdir(rd):
                if name.endswith(".json"):
                    assert "sess-local" not in open(os.path.join(rd, name), encoding="utf-8").read(), name   # no committed file names the session
            # a provider's task: what it was asked is committed, portably; the request as sent stays local
            assert run("add", "T2", "--role", "implementer", "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0
            assert run("run", "--target", pj.dir)[0] == 0
            asked = open(os.path.join(rd, "T2.asked.json"), encoding="utf-8").read()
            assert json.loads(asked)["task"] == "T2" and pj.dir not in asked and home not in asked, asked
            assert run("close", "--target", pj.dir)[0] == 0
            tracked = subprocess.run(["git", "ls-files"], cwd=pj.dir, capture_output=True, text=True).stdout.split()
            assert any(t.endswith("T2.asked.json") for t in tracked) and not any("/local/" in t or t.endswith(".request.json") for t in tracked), tracked
            # committed records written by a working source are named for the reviewer
            doc = json.loads(run("report", "--target", pj.dir)[1])
            unreleased = [f for f in doc["findings"] if f["kind"] == "unreleased-writer"]
            assert ("+g" in chongdae.engine()) == bool(unreleased), (chongdae.engine(), unreleased)
            # `commit-records: false` (here in this machine's overlay, as `hunsu dev` applies a project's dev-settings):
            # the record is written and not committed
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout
            write(os.path.join(pj.dir, "hunsu.local.json"), {"settings": {"chongdae": {"commit-records": False}}})
            code, out = run("init", "--session", "--goal", "trial", "--target", pj.dir)
            assert code == 0 and "record written, not committed" in out, out
            assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout == head
            assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "state.json")), "the record is on disk"
        finally:
            os.environ.pop("CHONGDAE_USER", None)
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)


def test_a_session_run_keeps_each_tasks_word_its_own():
    """Seen on a site's about page: two no-check tasks added ahead of their work were both done by one `run`, the second
    claiming the first's file; a session build named tests it then wrote itself; a verifier's reject went back to the
    session twice with the tree unchanged."""
    with Project() as pj:
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            # a session build's tests must exist when it is added
            code, out = run("add", "build", "--check", sys.executable + " -c pass", "--tests", "test_a.py", "--target", pj.dir)
            assert code != 0 and "does not exist yet" in out, out
            # two no-check tasks added ahead: the first's file is not the second's work
            assert run("add", "plan", "--brief", "p", "--target", pj.dir)[0] == 0
            assert run("add", "tests", "--brief", "t", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "PLAN.md"), "# plan\n")
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "done plan" in out and "tests has changed nothing of its own" in out and "PLAN.md were the task before it" in out, out
            assert pj.state()["tasks"]["tests"]["status"] == "todo"
            write(os.path.join(pj.dir, "test_a.py"), "# the contract's test\n")
            code, out = run("run", "--target", pj.dir)
            assert code == 0 and "done tests" in out and pj.state()["tasks"]["tests"]["touched"] == ["test_a.py"], (out, pj.state()["tasks"]["tests"])
            # the tests exist now: the session build is accepted; its verifier's reject stops at once, no automatic resend
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"verifier": pj.fake_provider(REVIEW_REJECT, "verifier")}})
            assert run("add", "build", "--check", sys.executable + " -c pass", "--tests", "test_a.py", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "a.py"), "x = 1\n")
            code, out = run("run", "--target", pj.dir)
            ts = pj.state()["tasks"]["build"]
            assert code == chongdae.DECISION and "verifier rejected" in out and "sent back" not in out and not ts.get("attempts"), (out, ts.get("attempts"))
        finally:
            os.environ.pop("CHONGDAE_USER", None)


def test_added_tasks_run_in_the_order_added_and_a_providers_task_starts_when_spawned():
    """Task files are read in name order; a session run's tasks must advance in the order they were added (seen live: a session
    renamed `tests-core` to `a-tests-core` to get the tests before the build). And a provider's task takes its `start`
    snapshot when it is spawned, not at `add` — a build added alongside its test task saw the test-writer's file as its own
    change and was rejected for touching protected tests, twice."""
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "z-tests", "--brief", "the session writes the tests", "--target", pj.dir)[0] == 0
        assert run("add", "a-build", "--role", "implementer", "--brief", "build", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--tests", "tests/test_x.py", "--target", pj.dir)[0] == 0
        st = pj.state()["tasks"]
        assert st["z-tests"]["seq"] == 1 and st["a-build"]["seq"] == 2 and "start" in st["z-tests"] and "start" not in st["a-build"]
        assert [t["id"] for t in chongdae.all_tasks(chongdae.load(os.path.join(chongdae.run_dir(pj.dir), "plan.json")), pj.state())] == ["z-tests", "a-build"]
        write(os.path.join(pj.dir, "tests", "test_x.py"), "# written by the tests task, before the build starts\n")
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        st = pj.state()["tasks"]
        assert st["z-tests"]["status"] == "done" and "tests/test_x.py" in st["z-tests"]["touched"]
        assert st["a-build"]["status"] == "done" and "tests/test_x.py" not in (st["a-build"]["touched"] or []) and "rejected" not in st["a-build"], st["a-build"]
        # recheck leaves a record
        assert run("close", "--target", pj.dir)[0] == 0
        code, out = run("recheck", "--target", pj.dir)
        assert code == 0 and "recorded -> .chongdae/rechecks/" in out, out
        recs = os.listdir(os.path.join(pj.dir, ".chongdae", "rechecks"))
        assert len(recs) == 1 and json.load(open(os.path.join(pj.dir, ".chongdae", "rechecks", recs[0])))["green"] == [os.path.basename(chongdae.run_dir(pj.dir)) + "/a-build"]


def test_run_waits_a_bounded_time_then_hands_back_and_the_next_run_resumes():
    """A host's tool call has its own timeout; a `run` that waits longer gets backgrounded by the session and the provider dies
    with it (three sessions did exactly that). So `run` waits WAIT_BUDGET seconds, then stops with "still working — run again";
    the pending record lets the next `run` resume waiting for the same work and consume its answer."""
    with Project() as pj:
        slow = os.path.join(pj.dir, "slow.py")
        write(slow, "import json, sys, time\ntime.sleep(4)\njson.dump(%r, open(sys.argv[2], 'w'))\n" % RESPONSE_DONE)
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "kind": "slice", "providers": {"builder": [sys.executable, slow, "{request}", "{response}"]},
                "tasks": [{"id": "T1", "role": "builder", "needs": [], "checks": [[sys.executable, "-c", "raise SystemExit(0)"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        old = chongdae.WAIT_BUDGET; chongdae.WAIT_BUDGET = 1
        try:
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "T1: the provider is still working (pid" in out and "again keeps waiting" in out, out
            d = chongdae.run_dir(pj.dir)
            assert os.path.exists(os.path.join(d, "T1.pending.json")) and "response" not in pj.state()["tasks"]["T1"]
            chongdae.WAIT_BUDGET = 30
            code, out = run("run", "--target", pj.dir)
            assert code == 0, out
            assert pj.state()["tasks"]["T1"]["status"] == "done" and not os.path.exists(os.path.join(d, "T1.pending.json"))
        finally:
            chongdae.WAIT_BUDGET = old


def test_a_retry_keeps_a_before_answer_whose_contract_did_not_change_and_the_budget_is_per_call():
    """A retry for a report-format refusal used to re-hire 시비 (ten minutes) though the contract was what it was. Now a
    `before` answer carries the contract's fingerprint; retry keeps it while the text stands and drops it when the plan
    section or brief changed. And one `run` call has one wait budget, however many providers it starts."""
    QUIBBLE = {"status": "done", "summary": "", "non-claims": [], "findings": []}
    with Project() as pj:
        write(os.path.join(pj.dir, "plan", "PLAN.md"), "# p\n\n## Q-a\n\nfirst wording.\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"quibble": pj.fake_provider(QUIBBLE, name="sibi"), "implementer": pj.fake_provider({"status": "failed", "summary": "bad report", "verified": [], "decisions": [], "non-claims": []}, name="builder")}})
        assert run("init", "--session", "--goal", "g", "--from", "plan/PLAN.md", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--role", "implementer", "--before", "quibble", "--closes", "Q-a", "--brief", "b", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "did not finish" in out, out
        fp = pj.state()["tasks"]["T1"]["stages"]["quibble"]["contract-fingerprint"]
        assert fp and len(fp) == 12
        assert run("retry", "T1", "--delegated", "format", "--target", pj.dir)[0] == 0
        ts = pj.state()["tasks"]["T1"]
        assert "quibble" in ts["stages"] and "stages" not in ts["attempts"][0], "the contract did not change: 시비's answer stands"
        # the plan section changes: the next retry drops the answer (the role is hired again by the next run)
        write(os.path.join(pj.dir, "plan", "PLAN.md"), "# p\n\n## Q-a\n\nsecond wording.\n")
        run("run", "--target", pj.dir)
        assert run("retry", "T1", "--delegated", "format", "--target", pj.dir)[0] == 0
        ts = pj.state()["tasks"]["T1"]
        assert "stages" not in ts and "quibble" in ts["attempts"][1]["stages"], ts.get("stages")
    with Project() as pj:
        slow = os.path.join(pj.dir, "slow.py")
        write(slow, "import json, sys, time\ntime.sleep(2)\njson.dump(%r, open(sys.argv[2], 'w'))\n" % QUIBBLE)
        slow2 = os.path.join(pj.dir, "slow2.py")
        # the builder outlasts the wait loop's 2-second poll past the deadline: at 2s it could finish inside that sleep and be
        # taken as done, which is right for the engine and made this test depend on process start-up time (seen once in 22 runs)
        write(slow2, "import json, sys, time\ntime.sleep(5)\njson.dump(%r, open(sys.argv[2], 'w'))\n" % RESPONSE_DONE)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"quibble": [sys.executable, slow, "{request}", "{response}"], "implementer": [sys.executable, slow2, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--role", "implementer", "--before", "quibble", "--brief", "b", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        old = chongdae.WAIT_BUDGET; chongdae.WAIT_BUDGET = 3
        try:
            t0 = time.time(); code, out = run("run", "--target", pj.dir); dt = time.time() - t0
            assert code == chongdae.DECISION and "still working" in out and dt < 6, (out, dt)   # quibble took ~2s, the builder then hit the call's remaining budget — not a fresh 3s of its own
        finally:
            chongdae.WAIT_BUDGET = old


def test_session_run_tasks_added_as_the_work_goes_claims_and_the_write_hook():
    with Project() as pj:
        env = dict(os.environ, CHONGDAE_USER="alice")
        os.environ["CHONGDAE_USER"] = "alice"
        try:
            # no run: the write hook refuses project files, allows the record and files elsewhere
            code, out = hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": os.path.join(pj.dir, "a.py")}})
            assert code == 2 and "no run in progress" in out, out
            assert hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": os.path.join(pj.dir, ".chongdae", "x.json")}})[0] == 0
            assert hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": os.path.join(pj.dir, "hunsu.json")}})[0] == 0
            assert hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": "C:/elsewhere/a.py" if os.name == "nt" else "/elsewhere/a.py"}})[0] == 0
            code, out = hook("session_start.py", {"cwd": pj.dir})
            assert code == 0 and "no run in progress" in out, out
            assert run("add", "T1", "--target", pj.dir)[0] != 0, "no run to add to"
            code, out = run("status", "--target", pj.dir)
            assert code == 0 and out.startswith("no run"), out
            # a session run: tasks are added as the work goes; each takes its start snapshot at add time
            assert run("init", "--session", "--goal", "tidy", "--target", pj.dir)[0] == 0
            assert hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Edit", "tool_input": {"file_path": os.path.join(pj.dir, "a.py")}})[0] == 0
            assert "run %s in progress" % os.path.basename(chongdae.run_dir(pj.dir)) in hook("session_start.py", {"cwd": pj.dir})[1]
            write(os.path.join(pj.dir, "old.py"), "x = 0\n")   # dirt before the task: not the task's
            assert run("add", "T1", "--brief", "fix a typo", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--target", pj.dir)[0] != 0, "ids are unique"
            write(os.path.join(pj.dir, "a.py"), "x = 1\n")
            code, out = run("run", "--target", pj.dir)
            assert code == 0 and "session run" in out and "1 task(s), 0 open" in out, out
            st = pj.state()
            assert st["tasks"]["T1"]["status"] == "done" and st["tasks"]["T1"]["touched"] == ["a.py"] and st["tasks"]["T1"]["def"]["brief"] == "fix a typo"
            assert any("no check decides" in n for n in chongdae.non_claims(st)), chongdae.non_claims(st)
            assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "tasks", "T1.json")), "one file per task"
            assert "tasks" not in chongdae.load(os.path.join(chongdae.run_dir(pj.dir), "state.json")), "state.json carries no task"
            # a task with a check and a gate; a task claimed by someone else is not this machine's to advance
            write(os.path.join(pj.dir, "check.py"), "import sys; sys.exit(0)\n")
            assert run("add", "T2", "--check", sys.executable + " check.py", "--gate", "human", "--target", pj.dir)[0] == 0
            assert run("add", "T3", "--brief", "bob's piece", "--target", pj.dir)[0] == 0
            assert run("claim", "T3", "--by", "bob", "--target", pj.dir)[0] == 0
            assert run("claim", "T3", "--target", pj.dir)[0] != 0, "alice cannot take bob's task from chongdae"
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "human: review task T2" in out, out   # the loop stops at the first gate; T3 comes after
            assert run("confirm", "T2", "--by", "alice", "--target", pj.dir)[0] == 0
            code, out = run("run", "--target", pj.dir)
            assert code == 0 and "T3 is claimed by bob" in out and "1 open (T3)" in out, out
            # a task that will not be done is dropped with its reason — not left open for the run to close around it
            assert run("add", "T4", "--brief", "mis-specified", "--target", pj.dir)[0] == 0
            assert run("drop", "T2", "--why", "x", "--target", pj.dir)[0] != 0, "done: nothing to drop"
            write(os.path.join(pj.dir, "t4-work.py"), "x = 1\n")   # work done in T4's window before it was dropped
            code, out = run("drop", "T4", "--why", "the check named a pytest flag; unittest here", "--by", "alice", "--target", pj.dir)
            assert code == 0 and pj.state()["tasks"]["T4"]["status"] == "dropped" and pj.state()["tasks"]["T4"]["dropped"]["by"] == "alice"
            assert "t4-work.py" in pj.state()["tasks"]["T4"]["touched"], "what changed in a dropped task's window stays attributed to it"
            code, out = run("close", "--target", pj.dir)
            assert code == 0 and "2 task(s) done, 1 open (T3), 1 dropped (T4)" in out, out
            assert pj.state()["status"] == "complete" and pj.state()["open"] == ["T3"]
            assert run("close", "--target", pj.dir)[0] != 0
            # the report: the open task is a finding that names the way out; the dropped one is a non-claim, not left-open
            code, out = run("report", "--target", pj.dir)
            doc = json.loads(out[out.index("{"):])
            left = [f for f in doc["findings"] if f["kind"] == "left-open"]
            assert len(left) == 1 and left[0]["where"].endswith("/T3") and "left open when the run closed" in left[0]["text"] and "chongdae drop T3" in left[0]["text"], left
            assert any(f["kind"] == "non-claim" and "dropped, not done: the check named a pytest flag" in f["text"] for f in doc["findings"]), doc["findings"]
            # an older run kept its tasks inside state.json: still read
            legacy = os.path.join(pj.dir, ".chongdae", "run-20200101-000000-0000")
            write(os.path.join(legacy, "plan.json"), {"artifact-type": "chongdae/plan@1", "goal": "old", "tasks": [{"id": "X", "role": "r", "checks": [["x"]]}]})
            write(os.path.join(legacy, "state.json"), {"status": "complete", "tasks": {"X": {"status": "done", "touched": ["old.py"]}}, "non-claims": ["X: nothing"]})
            st = chongdae.load_state(legacy)
            assert st["tasks"]["X"]["touched"] == ["old.py"] and chongdae.non_claims(st) == ["X: nothing"]
        finally:
            os.environ.pop("CHONGDAE_USER", None)


def test_report_emits_findings_typed_for_a_reviewer():
    with Project() as pj:
        write(os.path.join(pj.dir, "a.py"), "x = 1\n")
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            run("init", "--session", "--goal", "g", "--target", pj.dir)
            run("add", "T1", "--brief", "b", "--target", pj.dir)
            write(os.path.join(pj.dir, "a.py"), "x = 2\n")
            run("run", "--target", pj.dir)
            write(os.path.join(pj.dir, "b.py"), "y = 1\n")   # after T1 passed: nobody's
            run("add", "T2", "--check", sys.executable + " -c pass", "--gate", "human", "--target", pj.dir)
            run("run", "--target", pj.dir)
            run("confirm", "T2", "--delegated", "late", "--target", pj.dir)
            run("run", "--target", pj.dir)
            run("close", "--target", pj.dir)
        finally:
            os.environ.pop("CHONGDAE_USER", None)
        code, out = run("report", "--since", base, "--target", pj.dir)
        doc = json.loads(out)
        assert code == 0 and doc["artifact-type"] == "dwitbuk/findings@1" and doc["source"] == "chongdae"
        by_kind = {}
        for f in doc["findings"]:
            by_kind.setdefault(f["kind"], []).append(f)
        assert [f["where"] for f in by_kind["outside-run"]] == ["b.py"], by_kind["outside-run"]   # a.py is T1's
        write(os.path.join(pj.dir, "hunsu.json"), {"x": 1})
        doc = json.loads(run("report", "--since", base, "--target", pj.dir)[1])
        assert not any(f["where"].startswith("hunsu") for f in doc["findings"]), "the environment's files are hunsu's to report"
        assert any("(no verifier): late" in f["text"] for f in by_kind["delegated"])
        assert any("no check decides" in f["text"] for f in by_kind["non-claim"]) and "unattributed" not in by_kind
        # a rejected attempt's findings are reported too
        st = chongdae.load_state(chongdae.run_dir(pj.dir))
        st["tasks"]["T2"]["attempts"] = [{"status": "session", "review": REVIEW_REJECT, "retried": {"by": "kim"}}]
        chongdae.save_state(chongdae.run_dir(pj.dir), st)
        doc = json.loads(run("report", "--since", base, "--target", pj.dir)[1])
        vr = [f for f in doc["findings"] if f["kind"] == "verifier-reject"]
        assert len(vr) == 1 and "attempt 1" in vr[0]["where"] and "clear resets the counter" in vr[0]["text"], vr


def test_outside_runs_declared_in_the_lock_are_the_projects_own_procedure():
    """An author's posts are written by the project's procedure, not in runs: the write hook lets them through without a run,
    and report leaves them out of outside-run — saying so, with how many files it left out."""
    with Project() as pj:
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()
        write(os.path.join(pj.dir, "hunsu.json"), {"settings": {"chongdae": {"outside-runs": ["./content/", "docs", "../up", "/abs"]}}})
        assert chongdae.outside_runs(pj.dir) == ["content", "docs"], "an entry out of the project names nothing"

        def write_hook(*parts):
            return hook("pre_write.py", {"cwd": pj.dir, "tool_name": "Write", "tool_input": {"file_path": os.path.join(pj.dir, *parts)}})[0]
        assert write_hook("content", "posts", "a.md") == 0 and write_hook("docs", "index.html") == 0
        assert write_hook("contents", "a.md") == 2, "a declared directory is not a name prefix"
        assert write_hook("a.py") == 2, "everything else still needs a run"

        write(os.path.join(pj.dir, "content", "posts", "a.md"), "post\n")
        write(os.path.join(pj.dir, "docs", "index.html"), "<p>post</p>\n")
        write(os.path.join(pj.dir, "b.py"), "y = 1\n")
        doc = json.loads(run("report", "--since", base, "--target", pj.dir)[1])
        assert [f["where"] for f in doc["findings"] if f["kind"] == "outside-run"] == ["b.py"], doc
        told = [f for f in doc["findings"] if f["where"] == "settings.chongdae.outside-runs"]
        assert len(told) == 1 and told[0]["kind"] == "non-claim" and "content, docs" in told[0]["text"] and "2 file(s)" in told[0]["text"], told


def test_delegation_is_declared_once_and_referenced_scope_enforced_and_stamps_flagged():
    """A batch pre-approval is ONE judgment: `delegate` writes D-xxxx into the run's delegations/ and notarizes it.
    A `--delegated D-xxxx` is a reference — resolved (it must exist, and cover this judgment kind) and recorded as
    {ref}, never the words repeated. The same literal reason stamped on 3+ judgments is `report`'s delegation-stamp
    finding; refs are exempt — pointing at one declared judgment is their purpose."""
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "base.txt"), "x\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        run_name = os.path.basename(chongdae.run_dir(pj.dir))
        # the delegation: a record in delegations/ and its own notary commit
        code, out = run("delegate", "--scope", "confirm,retry", "--why", "owner pre-approved this run", "--by", "kim", "--target", pj.dir)
        assert code == 0, out
        did = out.strip()
        assert chongdae.DELEGATION_REF.match(did), did
        rec = chongdae.load(os.path.join(chongdae.run_dir(pj.dir), "delegations", did + ".json"))
        assert rec["id"] == did and rec["scope"] == ["confirm", "retry"] and rec["why"] == "owner pre-approved this run" and rec["by"] == "kim" and rec["at"].endswith("+00:00"), rec
        log = subprocess.run(["git", "log", "--format=%s"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert "%s: delegate %s (confirm,retry)" % (run_name, did) in log, log
        # a delegation scoped elsewhere, for the scope check
        code, out = run("delegate", "--scope", "accept", "--why", "decisions only", "--by", "kim", "--target", pj.dir)
        assert code == 0, out
        accept_only = out.strip()
        # six gated tasks: three confirmed by reference, three by the same pasted literal
        for i in range(1, 7):
            assert run("add", "T%d" % i, "--check", sys.executable + " -c 'raise SystemExit(0)'", "--gate", "human", "--target", pj.dir)[0] == 0
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "human: review task T%d" % i in out, out
            if i == 1:
                # an unknown ref is refused with a way out; a ref outside its scope too
                code, out = run("confirm", "T1", "--delegated", "D-deadbeef", "--target", pj.dir)
                assert code != 0 and "no delegation D-deadbeef" in out and "chongdae delegate" in out, out
                code, out = run("confirm", "T1", "--delegated", accept_only, "--target", pj.dir)
                assert code != 0 and "does not cover 'confirm'" in out and "accept" in out, out
            reason = did if i <= 3 else "boss said ship it"
            assert run("confirm", "T%d" % i, "--delegated", reason, "--target", pj.dir)[0] == 0
        cf = dict(pj.state()["tasks"]["T1"]["confirmed"]); cf.pop("at", None); cf.pop("chongdae", None)
        assert cf == {"delegated": {"ref": did}, "verifier": None}, cf   # a ref, not the delegation's words repeated
        cf = dict(pj.state()["tasks"]["T4"]["confirmed"]); cf.pop("at", None); cf.pop("chongdae", None)
        assert cf == {"delegated": "boss said ship it", "verifier": None}, cf   # a literal reason keeps working as before
        assert run("close", "--target", pj.dir)[0] == 0
        doc = json.loads(run("report", "--target", pj.dir)[1])
        stamps = [f for f in doc["findings"] if f["kind"] == "delegation-stamp"]
        assert len(stamps) == 1 and "boss said ship it" in stamps[0]["text"] and "one judgment claiming to be many" in stamps[0]["text"] and "chongdae delegate" in stamps[0]["text"], stamps
        assert all(x in stamps[0]["where"] for x in ("T4", "T5", "T6")) and did not in stamps[0]["where"], stamps   # refs are exempt: that is their purpose
        assert any(f["kind"] == "delegated" and "ref %s" % did in f["text"] for f in doc["findings"]), "a ref'd judgment still shows in the delegated ledger"


def test_merge_plan_takes_coherence_from_the_lock_and_names_no_product():
    with Project() as pj:
        plan = chongdae.merge_plan(pj.dir, "abc123")
        assert plan["tasks"][0]["checks"] == [["python3", "{plugin:chongdae}/chongdae.py", "recheck"]] and any("no `coherence` role" in n for n in plan["non-claims"])
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"coherence": [["python", "{plugin:x}/x.py", "impact", "--at", "{base}"]]}})
        plan = chongdae.merge_plan(pj.dir, "abc123")
        assert plan["tasks"][0]["checks"][1] == ["python", "{plugin:x}/x.py", "impact", "--at", "abc123"] and not plan["non-claims"]
        # a plan that names a role with no provider anywhere stops; chongdae assumes no `session`
        p = {"artifact-type": "chongdae/plan@1", "goal": "g", "tasks": [{"id": "q", "role": "questions", "path": "plan/questions.json", "produces": "plan/questions@1", "gate": "human"}]}
        write(os.path.join(pj.dir, "plan.json"), p)
        run("init", "--plan", "plan.json", "--target", pj.dir)
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "role 'questions' has no provider" in out, out


def test_plugin_placeholders_resolve_from_local_links_never_from_the_plan():
    with Project() as pj:
        os.makedirs(os.path.join(pj.dir, "tools", "alpha"))
        write(os.path.join(pj.dir, "hunsu.local.json"), {"links": {"alpha": os.path.join(pj.dir, "tools").replace(os.sep, "/")}})
        got = chongdae.resolve_argv(pj.dir, ["python", "{plugin:alpha}/engine.py", "x"])
        assert got[1] == os.path.join(pj.dir, "tools", "alpha").replace(os.sep, "/") + "/engine.py", got
        try:
            chongdae.resolve_argv(pj.dir, ["{plugin:nope}/x"])
            raise AssertionError("unknown plugin must refuse")
        except SystemExit as err:
            assert "not linked" in str(err)


def test_run_selection_prefers_the_running_one_and_never_file_time():
    with Project() as pj:
        run("init", "--goal", "one", "--target", pj.dir)
        first = chongdae.run_dir(pj.dir)
        st = chongdae.load(os.path.join(first, "state.json")); st["status"] = "complete"; chongdae.save(os.path.join(first, "state.json"), st)
        import time; time.sleep(1.1)
        run("init", "--goal", "two", "--target", pj.dir)
        second = chongdae.run_dir(pj.dir)
        assert second != first and os.path.basename(second) > os.path.basename(first), "ids sort by time"
        assert chongdae.run_dir(pj.dir, os.path.basename(first)) == first
        os.utime(first, None)   # touching the old run must not make it current
        assert chongdae.run_dir(pj.dir) == second


def test_a_workers_session_stays_local_and_the_record_carries_its_trace():
    """A worker's whole session and the request as sent carry this machine's paths and can be megabytes; they stay on disk,
    out of git. The committed record gets `<tag>.trace.json`: the commands with exit codes and the files changed, the project
    as `.` and home as `~`. A session an earlier version committed leaves the index at the next record commit."""
    tmp = tempfile.mkdtemp(prefix="chongdae-trace-")
    try:
        def git(*a):
            return subprocess.run(["git", *a], cwd=tmp, capture_output=True, text=True)
        git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
        run_dir = os.path.join(tmp, ".chongdae", "run-x")
        home = os.path.expanduser("~")
        lines = [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"type": "command_execution", "command": '/bin/zsh -lc "python3 -m unittest discover -s tests -p \'test_s[12].py\'"', "exit_code": 0}},
            {"type": "item.completed", "item": {"type": "command_execution", "command": '/bin/zsh -lc "cat %s/.codex/skill.md"' % home, "exit_code": 0}},
            {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": os.path.join(tmp, "build.py"), "kind": "update"}]}},
        ]
        write(os.path.join(run_dir, "b.response.transcript.jsonl"), "\n".join(json.dumps(x) for x in lines) + "\n")
        write(os.path.join(run_dir, "b.request.json"), json.dumps({"target": tmp}))
        write(os.path.join(run_dir, "b.response.json"), json.dumps({"status": "done", "worker": {"host": "codex", "model": "m", "transcript": "b.response.transcript.jsonl"}}))
        write(os.path.join(run_dir, "state.json"), "{}")
        # an earlier version committed a session: it must leave the index, and stay on disk
        write(os.path.join(run_dir, "a.response.transcript.1.jsonl"), json.dumps(lines[1]) + "\n")
        git("add", "-f", ".chongdae/run-x/a.response.transcript.1.jsonl"); git("commit", "-qm", "old")
        assert chongdae.commit_record(tmp, "run-x", "test")
        tracked = git("ls-files").stdout.split()
        assert ".chongdae/run-x/b.trace.json" in tracked and ".chongdae/run-x/a.trace.1.json" in tracked, tracked
        assert not any(t.endswith((".jsonl", ".request.json")) for t in tracked), tracked
        assert os.path.exists(os.path.join(run_dir, "a.response.transcript.1.jsonl")), "local copy kept"
        trace = json.load(open(os.path.join(run_dir, "b.trace.json"), encoding="utf-8"))
        assert trace["worker"] == {"host": "codex", "model": "m"} and trace["written_by"] == chongdae.engine(), trace
        # the record keeps what the worker changed and how its commands ended; the command lines stay local
        assert "commands" not in trace and trace["commands-run"] == 2 and trace["commands-failed"] == 0 and trace["changed"] == ["update ./build.py"], trace
        full = json.load(open(os.path.join(run_dir, "local", "b.trace.json"), encoding="utf-8"))
        assert full["commands"][0] == {"command": "python3 -m unittest discover -s tests -p 'test_s[12].py'", "exit": 0}, full
        assert full["commands"][1]["command"] == "cat ~/.codex/skill.md", full
        assert not any("/local/" in t for t in tracked) and ".chongdae/run-x/b.response.json" not in tracked, tracked
        assert chongdae.neutral_path("rg --files %s/.codex/plugins/cache/some-market | rg x" % home, tmp) == "rg --files <codex-plugins> | rg x"
        assert chongdae.neutral_path("sed -n 1p ~/.claude/plugins/cache/m/hacheong/1.2.0/worker.py", tmp) == "sed -n 1p <plugin:hacheong@1.2.0>/worker.py"
        assert chongdae.neutral_path("D=/private/tmp/claude-1/x-y/scratch/a.json && ls", tmp) == "D=<tmp> && ls"
        assert chongdae.neutral_path("cat %s/.claude/projects/%s-src/s.jsonl" % (home, home.replace(os.sep, "-")), tmp) == "cat ~/.claude/projects/~-src/s.jsonl"
        committed = git("show", "HEAD", "--", ".chongdae/run-x/b.trace.json").stdout
        assert tmp not in committed and home not in committed, committed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Skip as why:
                print("SKIP", name, "--", why)
            except (Exception, SystemExit) as err:   # a self-check that dies between tests lies by omission
                failed += 1
                print("FAIL", name, "--", "%s: %s" % (type(err).__name__, err))
    print("all passed" if not failed else "%d failed" % failed)
    sys.exit(1 if failed else 0)
