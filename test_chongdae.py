"""Self-check for chongdae. A temp project; a fake provider that replays recorded responses; every stop fires once.

  python test_chongdae.py
"""
import contextlib
import glob
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



# a test that closes a session run on work it never commits says so: `close` stops on a finished task's uncommitted work
UNCOMMITTED = ("--anyway", "--why", "a test project: its work is never committed")


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
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "local", "A.request.json")), "the request as sent is kept, in the run's local/"
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
        # decisions nobody accepts: the other answer is to reject the work — `retry` takes it, the attempt (decisions and
        # the provider's non-claims) stays with the attempt, and the task's own list holds only what is still true
        plan_with(RESPONSE_DECISIONS, "B2")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "chongdae retry B2" in out, out
        ts = pj.state()["tasks"]["B2"]
        ts_nc = [n for n in ts.get("non-claims", []) if n.startswith("(provider) ")]
        assert run("retry", "B2", "--by", "kim", "--target", pj.dir)[0] == 0
        ts = pj.state()["tasks"]["B2"]
        assert ts["attempts"][-1]["decisions"] and "response" not in ts and not [n for n in ts.get("non-claims", []) if n.startswith("(provider) ")], ts
        run("run", "--target", pj.dir)   # the second attempt (the same fake answer): accepted this time, then the gate
        assert run("accept", "B2", "--by", "kim", "--target", pj.dir)[0] == 0 and run("run", "--target", pj.dir)[0] == chongdae.DECISION
        assert run("confirm", "B2", "--by", "kim", "--target", pj.dir)[0] == 0 and run("run", "--target", pj.dir)[0] == 0
        # a `tests` entry is one path: a shell-joined list arrives as one string and would be watched by nothing
        probs = chongdae.plan_problems({"artifact-type": "chongdae/plan@1", "goal": "g", "tasks": [
            {"id": "T9", "role": "implementer", "checks": [["x"]], "tests": ["tests/a.py tests/b.py"]}]})
        assert any("holds several paths" in x for x in probs), probs
        # blocked -> stop with the provider's summary; no response -> stop
        plan_with(RESPONSE_BLOCKED, "C")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "provider stopped" in out and "what done means" in out, out
        # retry: the blocked attempt stays in the record; the next call's request carries it and the tree's current diff
        assert run("retry", "A", "--by", "kim", "--target", pj.dir)[0] != 0, "A is done, nothing to retry"
        assert run("retry", "C", "--by", "kim", "--target", pj.dir)[0] == 0   # a retry left without --by is the session's: test_an_omitted_by_is_the_session
        st = pj.state()["tasks"]["C"]
        ret = dict(st["attempts"][0]["retried"]); ret.pop("at", None); ret.pop("chongdae", None)
        assert "response" not in st and st["attempts"][0]["status"] == "blocked" and ret == {"by": "kim"}
        pj.fake_provider(RESPONSE_DONE)   # the same script path: the human "wrote the decision into the plan", the next call succeeds
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review task C" in out, out
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "C.request.json"), encoding="utf-8"))
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


def test_a_build_that_puts_uncommitted_contract_tests_back_to_head_is_caught_and_the_tests_restored():
    # the contract's newest tests are in the working tree, not yet committed; a build that takes HEAD for the contract and
    # restores it leaves the file clean — "dirty now" alone never sees that as a change
    with Project() as pj:
        write(os.path.join(pj.dir, "check2.py"), "import sys; sys.exit(1)\n")
        write(os.path.join(pj.dir, "test_x.py"), "# the contract's test, first version\n")
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        newest = "# the contract's test, rewritten for the new decision (uncommitted)\n"
        write(os.path.join(pj.dir, "test_x.py"), newest)
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "providers": {"implementer": "session"},
                "tasks": [{"id": "T1", "role": "implementer", "tests": ["test_x.py"], "checks": [[sys.executable, "check2.py"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "make these checks pass" in out, out   # start taken, the contract's tests kept
        write(os.path.join(pj.dir, "check2.py"), "import sys; sys.exit(0)\n")
        subprocess.run(["git", "checkout", "--", "test_x.py"], cwd=pj.dir, check=True)   # the build "restores" HEAD
        assert chongdae.touched_files(pj.dir, pj.state()["tasks"]["T1"]["start"]) == ["check2.py", "test_x.py"]
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "changed the contract's tests (test_x.py)" in out and "restored as they were when the task started" in out, out
        assert io.open(os.path.join(pj.dir, "test_x.py"), encoding="utf-8").read() == newest
        assert pj.state()["tasks"]["T1"]["rejected"]["restored"] == ["test_x.py"]
        assert run("retry", "T1", "--by", "kim", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 or "human" in out or "produced" in out, out
        assert pj.state()["tasks"]["T1"]["touched"] == ["check2.py"], pj.state()["tasks"]["T1"]["touched"]


def test_verifier_before_the_gate_protected_tests_and_delegation_policy():
    with Project() as pj:
        write(os.path.join(pj.dir, "check.py"), "import sys; sys.exit(0)\n")
        write(os.path.join(pj.dir, "test_x.py"), "# the contract's test\n")
        write(os.path.join(pj.dir, "PLAN.md"), "# plan\n\n## Q1 count\n\nAcceptance: count prints the number.\n")   # the verifier is sent Q1's section, never an empty contract
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "from": "PLAN.md",
                "providers": {"implementer": pj.fake_provider(RESPONSE_DONE), "verifier": pj.fake_provider(REVIEW_REJECT, "verifier")},
                "tasks": [{"id": "S1", "role": "implementer", "gate": {"human": True, "delegate": "after-verifier"}, "tests": ["test_x.py"],
                           "checks": [[sys.executable, "check.py"]], "closes": ["Q1"]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "hunsu.json"), {"plugins": {"mangsang": {}}})   # the environment changed in the tree: a record path, never `touched`
        # the build passes its checks; the verifier says no -> the failed path, with the findings in the stop message
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "verifier rejected" in out and "clear resets the counter" in out, out
        ts = pj.state()["tasks"]["S1"]
        assert ts["rejected"]["by"] == "verifier" and ts["review"]["verdict"] == "reject" and "start" in ts
        # before asking a person, the rejected work went back to the hands on its own — twice, then the stop is a person's
        autos = [a for a in ts.get("attempts", []) if (a.get("retried") or {}).get("auto")]
        assert len(autos) == chongdae.AUTO_RESENDS and all(a["review"]["verdict"] == "reject" and a["retried"]["by"] == "chongdae" for a in autos), ts.get("attempts")
        assert "sent back to the provider automatically" in out, out
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "local", "S1.verify.request.json")), "the verifier's request as sent is kept in local/"
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "S1.verify.request.json"), encoding="utf-8"))
        assert req["stage"] == "verify" and req["role"] == "verifier" and req["built"]["summary"] == "added count" and req["tests"] == ["test_x.py"]
        assert req["touched"] == [] and "touched_since" in req, req   # the fake provider changed nothing; a human's edits would be in touched_since
        # what the record paths left out is said, so `touched: []` beside a changed hunsu.json is not a record that lies (guin-site, 2026-09-28)
        assert req["excluded"] == {"record-paths": ["hunsu.json"]}, req.get("excluded")
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
        assert os.path.exists(os.path.join(rd, "local", "S1.verify.request.json")) and os.path.exists(os.path.join(rd, "local", "S1.verify.4.request.json")), os.listdir(os.path.join(rd, "local"))   # every verdict's files survive the retries
        # the first verification reads the slice; every later one is a re-verification: the last reject's findings, the files changed since
        assert "recheck" not in json.load(open(os.path.join(rd, "local", "S1.verify.request.json")))
        again = json.load(open(os.path.join(rd, "local", "S1.verify.2.request.json")))["recheck"]
        assert again["findings"] == REVIEW_REJECT["findings"] and isinstance(again["changed_since"], list), again
        assert run("confirm", "S1", "--delegated", "verifier said ok", "--target", pj.dir)[0] == 0
        cf = dict(pj.state()["tasks"]["S1"]["confirmed"]); cf.pop("at", None); cf.pop("chongdae", None)
        assert cf == {"delegated": "verifier said ok", "verifier": "accept"}
        # the rejects before that accept were answered by the accepted work: facts of the record, not charges still owed
        code, out = run("report", "--target", pj.dir)
        rej = [f for f in json.loads(out)["findings"] if f["kind"] == "verifier-reject"]
        assert rej and all(f.get("layer") == "observation" and "later attempt was accepted" in f["text"] for f in rej), rej
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


def hook(name, payload, **env):
    done = subprocess.run([sys.executable, os.path.join(HERE, "hooks", name)], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, **env))
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
        assert "init (session) — g" in log and "confirm T1 (by kim)" in log and "close — g (1 done, 0 open)" in log, log   # a judgment's commit names the run's goal: the log reads without opening the record
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
    keys = ("AI_AGENT", "CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ID", "AGENT_HOST", "CODEX_THREAD_ID", "CODEX_VERSION", "AGENT_CODEX_HOME")
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
            os.environ["AGENT_CODEX_HOME"] = os.path.join(pj.dir, "codex-home")
            write(os.path.join(pj.dir, "codex-home", "sessions", "2026", "rollout-2026-thread-1.jsonl"),
                  json.dumps({"type": "session_meta", "payload": {}}) + "\n" + json.dumps({"type": "turn_context", "payload": {"model": "gpt-test", "effort": None}}) + "\n")
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
            assert run("run", "--target", pj.dir)[0] == 0
            assert pj.state()["tasks"]["T1"]["performed_by"] == {"provider": "session", "host": "codex", "agent": "codex_0.155.0", "session": "thread-1", "model": "gpt-test",
                                                                   "versions": {"used": {"chongdae": chongdae.engine().split(" ", 1)[1]}}}, pj.state()["tasks"]["T1"]["performed_by"]
            del os.environ["AGENT_HOST"], os.environ["CODEX_THREAD_ID"], os.environ["CODEX_VERSION"], os.environ["AGENT_CODEX_HOME"]
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
        assert os.path.exists(os.path.join(d, "local", "T1.pending.json")), "the pending record survives the dead runner"
        # second `run` resumes the SAME provider (waits for it) instead of spawning another
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        assert io.open(marker, encoding="utf-8").read() == "x", "the provider ran once, not twice"
        assert not os.path.exists(os.path.join(d, "local", "T1.pending.json")), "consumed pending is cleaned up"
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
        code, out = run("run", "mine", "--target", pj.dir)   # nothing of its own in the tree: done on the session's word by name
        assert code == 0, out
        tasks = pj.state()["tasks"]
        assert tasks["mine"]["status"] == "done" and tasks["mine"]["performed_by"]["provider"] == "session"
        assert tasks["theirs"]["status"] == "done" and tasks["theirs"]["performed_by"]["provider"] == "command" and tasks["theirs"]["response"]["status"] == "done", tasks["theirs"]
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "theirs.request.json")))
        assert req["contract"] == {"Q-add": "## Q-add\n\n`add` appends one item."}, "a session run's --from names the document whose sections are the contract"
        assert run("add", "nobody", "--role", "modeler", "--brief", "no such provider", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "role 'modeler' has no provider" in out, out


def test_the_session_takes_a_task_its_hands_could_not_finish_instead_of_dropping_done_work():
    """guin-site, 2026-09-30: three tasks were `drop`ped although their work was in the tree — a worker's sandbox could not open
    a port, a tests worker's guard read the tree the session was also writing. A drop records done work as not done. `take`
    makes the task the session's (self-performed instead of its role, with the reason); the stopped attempt stays in
    `attempts`, and `run` decides it like any session task: its checks, then the gate."""
    failed = {"status": "failed", "summary": "could not bind a local port", "verified": [], "decisions": [], "non-claims": ["only-tests-touched: stray src/a.py"]}
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(failed)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        ok = sys.executable + " -c 'raise SystemExit(0)'"
        assert run("add", "s2-build", "--role", "implementer", "--brief", "backup code", "--check", ok, "--requires", "loopback", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "did not finish" in out and "chongdae take s2-build --why" in out, out   # the stop names the honest close
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "s2-build.request.json")))
        assert req["needs"] == ["loopback"], req   # the plan's `requires` travels as the request's `needs`
        assert run("take", "s2-build", "--target", pj.dir)[0] != 0, "a take says why"
        code, out = run("take", "s2-build", "--why", "the worker's sandbox cannot open a local port; the session finishes it", "--by", "kim", "--target", pj.dir)
        assert code == 0 and "attempt 1 stays in the record" in out, out
        ts = pj.state()["tasks"]["s2-build"]
        assert ts["taken"]["from"] == "implementer" and ts["self-performed"]["instead-of"] == "implementer" and ts["self-performed"]["taken-over"], ts
        assert ts["attempts"][0]["status"] == "failed" and "response" not in ts
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        ts = pj.state()["tasks"]["s2-build"]
        assert ts["status"] == "done" and ts["performed_by"]["provider"] == "session", ts
        assert run("take", "s2-build", "--why", "again", "--target", pj.dir)[0] != 0, "a done task is not taken"
        code, out = run("report", "--target", pj.dir)
        assert "self-performed" in out, out   # the reviewer counts it as the session's own hands
        assert chongdae.plan_problems({"artifact-type": "chongdae/plan@1", "goal": "g", "tasks": [{"id": "x", "role": "r", "checks": [["x"]], "requires": ["gpu"]}]}) \
            == ["x: requires gpu — known: network, loopback"]


def test_one_reason_with_a_different_tail_each_time_is_still_one_stamp():
    """guin-site opened ten judgments' reasons with "소유자가 구현을 맡김", each with its own tail, and the exact-string count saw
    ten different reasons. A shared opening clause used across 3+ judgments is reported as the stamp it is; drops count too."""
    with Project() as pj:
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        for i, tail in enumerate((": the sandbox stopped it", " (tests were rewritten)", " — done by the session")):
            assert run("add", "T%d" % i, "--brief", "b", "--target", pj.dir)[0] == 0
            assert run("drop", "T%d" % i, "--why", "소유자가 구현을 맡김" + tail, "--by", "kim", "--target", pj.dir)[0] == 0
        assert run("add", "U", "--brief", "b", "--target", pj.dir)[0] == 0
        assert run("drop", "U", "--why", "mis-specified: the plan changed", "--by", "kim", "--target", pj.dir)[0] == 0
        assert run("close", "--target", pj.dir)[0] == 0
        doc = json.loads(run("report", "--target", pj.dir)[1])
        stamps = [f for f in doc["findings"] if f["kind"] == "delegation-stamp"]
        assert len(stamps) == 1 and "open with the same clause '소유자가 구현을 맡김'" in stamps[0]["text"] and "3 judgments" in stamps[0]["text"], stamps
        assert all(("T%d" % i) in stamps[0]["where"] for i in range(3)) and "/U " not in stamps[0]["where"] + " ", stamps


def test_a_member_that_refuses_before_starting_is_taken_by_the_session_not_a_failed_build():
    """hacheong refuses a task whose `needs` its member's sandbox cannot give, before any host call: status blocked, the first
    non-claim "not attempted: …". That is not a decision the contract lacks and not a build to resend; with no alternate in
    the lock and nothing decided in hunsu.json `capabilities`, the session takes it — no person is asked mid-run."""
    refused = {"status": "blocked", "summary": "needs loopback, which build on codex cannot do", "verified": [], "decisions": [],
               "non-claims": ["not attempted: needs loopback, which build on codex cannot do"]}
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(refused)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "s3", "--role", "implementer", "--check", sys.executable + " -c 'raise SystemExit(1)'", "--requires", "loopback", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        last = out.strip().splitlines()[-1]
        assert code == chongdae.DECISION and last.startswith("decision: session agent: s3:") and "taken by the session" in last, out
        assert "no implementer@loopback in the lock (hunsu.json capabilities: loopback: undecided)" in last, last
        assert "decision the contract does not give" not in out and "human" not in last, out
        ts = pj.state()["tasks"]["s3"]
        assert ts["taken"]["by"] == "chongdae" and ts["self-performed"]["taken-over"], ts
        assert ts["attempts"][0]["status"] == "blocked" and "taken" in ts["attempts"][0]["retried"], "the refused attempt is kept"
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "session agent: s3 — make these checks pass" in out, "the session's task now, decided by its checks"


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
        req, res = os.path.join(d, "local", "T1.request.json"), os.path.join(d, "local", "T1.response.json")
        assert os.path.exists(req) and not os.path.exists(res) and chongdae.load(os.path.join(d, "local", "T1.pending.json")).get("native")
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
        assert not os.path.exists(res) and os.path.exists(os.path.join(d, "local", "T1.response.1.json")) and os.path.exists(os.path.join(d, "local", "T1.request.1.json")), os.listdir(os.path.join(d, "local"))
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
        assert not os.path.exists(os.path.join(d, "local", "T1.pending.json"))


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
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "local", "T1.quibble.request.json"))
        assert json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "T1.quibble.request.json")))["role"] == "quibble"
        code2, out2 = run("run", "--target", pj.dir)
        assert code2 == chongdae.DECISION and "quibble found 2" in out2, "asked again: still waiting, not re-run"
        assert run("accept", "T1", "--target", pj.dir)[0] != 0, "who accepted?"
        code, out = run("accept", "T1", "--by", "kim", "--target", pj.dir)
        assert code == 0 and "accepted 2 finding(s) from quibble on T1" in out, out
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        assert "newbie T1: 1 finding(s) — in the record" in out and "unclear @ : the README has no command — \u201c# todo\u201d" in out, out   # relayed, not only filed
        ts = pj.state()["tasks"]["T1"]
        assert ts["status"] == "done" and ts["stages"]["quibble"]["accepted"]["by"] == "kim"
        assert ts["stages"]["modeler"] == {"skipped": "no provider"} and any("no provider for role 'modeler' (before)" in n for n in ts["non-claims"]), ts
        assert ts["stages"]["newbie"]["when"] == "after" and ts["stages"]["newbie"]["response"]["findings"][0]["kind"] == "unclear"
        assert os.path.exists(os.path.join(chongdae.run_dir(pj.dir), "local", "T1.newbie.request.json"))
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "T1.newbie.request.json")))
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
        assert json.load(open(os.path.join(rd, "local", "tests.request.json")))["amending"][0]["test"] == "test_a.py::test_x"
        assert json.load(open(os.path.join(rd, "local", "tests.request.1.json")))["checks"] == [[sys.executable, "-c", "raise SystemExit(0)"]], "the writer's request carries the build's check"
        assert st["build"]["status"] == "done" and st["build"]["rebaselined"][0]["tests"] == ["test_a.py"], st["build"]
        assert str(st["build"]["attempts"][0]["retried"]["auto"]).startswith("tests disputed"), st["build"]["attempts"]
        assert open(os.path.join(pj.dir, "test_a.py")).read() == "# amended\n"


def test_a_dispute_in_a_report_the_validator_refused_still_goes_to_the_tests_writer():
    """guin-site write-bsky-build, 2026-10-10: three answers each disputed the same three tests, and each named its check
    as `cd <project> && …`; the validator refused the report (`failed`, checks-ran), chongdae resent the build for its
    evidence, and the dispute was dropped every time. The dispute is about the tests, not the evidence: it is routed."""
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        writer = os.path.join(pj.dir, "writer.py")
        write(writer, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\n"
                      "open(os.path.join(req['target'], 'test_a.py'), 'w').write('# amended\\n' if req.get('amending') else '# wrong fixture\\n')\n"
                      "json.dump({'status': 'done', 'summary': 'w', 'non-claims': [], 'tests': ['test_a.py']}, open(sys.argv[2], 'w'))\n")
        builder = os.path.join(pj.dir, "builder.py")
        write(builder, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\n"
                       "wrong = open(os.path.join(req['target'], 'test_a.py')).read().startswith('# wrong')\n"
                       "json.dump({'status': 'failed' if wrong else 'done', 'summary': 'disputed' if wrong else 'built', 'verified': [], 'decisions': [],\n"
                       "           'non-claims': ['checks-ran: `cd /p && python3 -m unittest` was not run by the session'] if wrong else [], 'validation': {'failed': ['checks-ran']} if wrong else {},\n"
                       "           'disputed-tests': [{'test': 'test_a.py::test_x', 'contract_quote': 'Q', 'why': 'fixture breaks Q'}] if wrong else []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": [sys.executable, writer, "{request}", "{response}"],
                                                                  "implementer": [sys.executable, builder, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "tests", "--role", "nitpick", "--tests", "test_a.py", "--target", pj.dir)[0] == 0
        assert run("add", "build", "--role", "implementer", "--tests", "test_a.py", "--check", sys.executable + " -c 'raise SystemExit(1)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        st = pj.state()["tasks"]
        assert "reopened with the dispute" in out and st["tests"]["attempts"][0]["disputed-tests"][0]["why"] == "fixture breaks Q", out
        assert str(st["build"]["attempts"][0]["retried"]["auto"]).startswith("tests disputed"), st["build"]["attempts"]
        assert not any("did not run" in str((a.get("retried") or {}).get("auto")) for a in st["build"]["attempts"]), "not resent for its evidence instead"
        assert open(os.path.join(pj.dir, "test_a.py")).read() == "# amended\n"


def test_an_amendment_rebaselines_every_test_file_the_writer_changed_not_only_the_disputed_ones():
    """guin-site run e77d, 2026-10-10: the dispute named two test files; the tests writer fixed the cause in a shared fixture
    (`write_support.py`, also among the build's tests). Only the named files were re-baselined, so the build's next judgment
    restored the fixture as "changed protected tests" and charged the build. The amendment is what the writer changed."""
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        writer = os.path.join(pj.dir, "writer.py")
        write(writer, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\nt = req['target']\n"
                      "open(os.path.join(t, 'test_a.py'), 'w').write('# uses support\\n')\n"
                      "open(os.path.join(t, 'support.py'), 'w').write('# fixed fixture\\n' if req.get('amending') else '# wrong fixture\\n')\n"
                      "json.dump({'status': 'done', 'summary': 'w', 'non-claims': [], 'tests': ['test_a.py', 'support.py']}, open(sys.argv[2], 'w'))\n")
        builder = os.path.join(pj.dir, "builder.py")
        write(builder, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\n"
                       "wrong = open(os.path.join(req['target'], 'support.py')).read().startswith('# wrong')\n"
                       "json.dump({'status': 'blocked' if wrong else 'done', 'summary': 'disputed' if wrong else 'built', 'verified': [], 'decisions': [], 'non-claims': [],\n"
                       "           'disputed-tests': [{'test': 'test_a.py::test_x', 'contract_quote': 'Q', 'why': 'its fixture breaks Q'}] if wrong else []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": [sys.executable, writer, "{request}", "{response}"],
                                                                  "implementer": [sys.executable, builder, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "tests", "--role", "nitpick", "--tests", "test_a.py", "support.py", "--target", pj.dir)[0] == 0
        assert run("add", "build", "--role", "implementer", "--tests", "test_a.py", "support.py", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "changed protected tests" not in out, out
        st = pj.state()["tasks"]
        assert st["build"]["status"] == "done" and st["build"]["rebaselined"][0]["tests"] == ["support.py", "test_a.py"], st["build"]
        assert open(os.path.join(pj.dir, "support.py")).read() == "# fixed fixture\n", "the fix stands"


def test_a_retry_that_requires_a_capability_hands_a_taken_task_to_the_alternate():
    """guin-site write-bsky-build, 2026-10-10: the session had taken the build; `retry --requires loopback` printed "the lock's
    implementer@loopback does it", and the next `run` kept it with the session (the take stood). Asking for the capability is
    asking for that hand: the take is lifted, in the record. A plain retry of a taken task says the session does it again."""
    blocked = {"status": "blocked", "summary": "the contract is silent on the port", "verified": [], "decisions": [], "non-claims": []}
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        write(os.path.join(pj.dir, "test_a.py"), "# the contract\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(blocked, "plain"),
                                                                  "implementer@loopback": pj.fake_provider(RESPONSE_DONE, "loop")}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "w", "--role", "implementer", "--tests", "test_a.py", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == chongdae.DECISION
        assert run("take", "w", "--why", "the session finishes it", "--by", "kim", "--checked", sys.executable + " -c 'pass'", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "test_a.py"), "# bent by the session\n")   # the session's attempt is rejected by the contract
        code, out = run("run", "--target", pj.dir)
        assert "changed the contract's tests" in out, out
        code, out = run("retry", "w", "--by", "kim", "--target", pj.dir)
        assert code == 0 and "the session took it (`take`), so the session does it again" in out, out
        ts = pj.state()["tasks"]["w"]
        assert "checked" not in ts and ts["attempts"][-1]["checked"]["ran"][0]["exit"] == 0, "what was run for an attempt goes with it"
        write(os.path.join(pj.dir, "test_a.py"), "# bent again\n")
        run("run", "--target", pj.dir)
        code, out = run("retry", "w", "--requires", "loopback", "--by", "kim", "--target", pj.dir)
        assert code == 0 and "the lock's implementer@loopback does it" in out, out
        ts = pj.state()["tasks"]["w"]
        assert "taken" not in ts and ts["attempts"][-1]["retried"]["untaken"]["why"] == "the session finishes it", ts
        assert not [n for n in ts.get("non-claims", []) if "taken over by the session" in n], ts["non-claims"]
        assert run("run", "--target", pj.dir)[0] == 0
        assert pj.state()["tasks"]["w"]["performed_by"]["as"] == "implementer@loopback"


def test_what_the_verifier_read_and_accepted_is_said_once_not_charged_and_a_restatement_replaces_its_original():
    """guin-site, 10-07 -> 10-10: 175 of 281 review charges were providers' own non-claims, disposed in bulk in 68 seconds; a
    reopened tests writer restated its earlier list in other words and both reached the reviewer. The build's verifier now
    gets the tests writer's non-claims beside the builder's; an accept marks both tasks' as seen — `report` says them in one
    observation, not as charges. A provider non-claim quoting the contract sentence a later answer quotes gives way to it."""
    old = ['(provider) "the list is sorted" — checked on three items', '(provider) nothing deployed']
    assert chongdae.merge_provider_non_claims(old, ['(provider) No test sorts a long list ("the list is sorted")']) == \
        ['(provider) nothing deployed', '(provider) No test sorts a long list ("the list is sorted")']
    assert chongdae.merge_provider_non_claims(['no check decides this task', '(provider) x'], ['(provider) x']) == ['no check decides this task', '(provider) x']
    # a quoted file name is not a contract sentence, and one new line replaces at most one old one
    old = ['(provider) "tests/run.py" does not cover the network path']
    assert chongdae.merge_provider_non_claims(old, ['(provider) "tests/run.py" was run without --all']) == old + ['(provider) "tests/run.py" was run without --all']
    old = ['(provider) "the list is sorted" — no test writes a long list', '(provider) "the list is sorted" — the fixture has no ties']
    assert chongdae.merge_provider_non_claims(old, ['(provider) "the list is sorted" — checked on three items']) == \
        [old[1], '(provider) "the list is sorted" — checked on three items']
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        writer = os.path.join(pj.dir, "writer.py")
        write(writer, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\nopen(os.path.join(req['target'], 'test_a.py'), 'w').write('# t\\n')\n"
                      "json.dump({'status': 'done', 'summary': 'w', 'non-claims': ['\"the list is sorted\" — checked on three items only']}, open(sys.argv[2], 'w'))\n")
        eyes = os.path.join(pj.dir, "eyes.py")
        write(eyes, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                    "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept', 'findings': []}, open(sys.argv[2], 'w'))\n")
        built = dict(RESPONSE_DONE, **{"non-claims": ["nothing deployed"]})
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": [sys.executable, writer, "{request}", "{response}"],
                                                                  "implementer": pj.fake_provider(built), "verifier": [sys.executable, eyes, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "tests", "--role", "nitpick", "--tests", "test_a.py", "--target", pj.dir)[0] == 0
        assert run("add", "build", "--role", "implementer", "--tests", "test_a.py", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        req = json.load(open(glob.glob(os.path.join(chongdae.run_dir(pj.dir), "local", "build.verify*request*.seen"))[0]))
        assert req["tests_non_claims"] == {"tests": ['"the list is sorted" — checked on three items only']} and req["built"]["non-claims"] == ["nothing deployed"], req
        st = pj.state()["tasks"]
        assert st["build"]["seen-non-claims"]["texts"] == ["(provider) nothing deployed"] and st["tests"]["seen-non-claims"]["by"] == "verifier of build"
        code, out = run("report", "--target", pj.dir)
        f = json.loads(out)["findings"]
        assert not [x for x in f if x["kind"] == "non-claim" and "(provider)" in x["text"]], f
        seen = [x for x in f if x["kind"] == "seen-non-claims"]
        assert len(seen) == 1 and seen[0]["layer"] == "observation" and seen[0]["text"].startswith("2 provider non-claim(s)") and "/build (1)" in seen[0]["where"], seen


def test_checked_is_one_command_bounded_and_a_retry_that_refuses_records_nothing():
    """`--checked "echo ok && false"` ran `echo` with three words and recorded a pass. One command, no shell: shell syntax is
    refused; a missing command, a timeout and a prompt for input are failures, not tracebacks or hangs. A retry whose check
    fails writes nothing — not even the `--requires` it was given."""
    with Project() as pj:
        for line in ("echo ok && false", "A=1 " + sys.executable + " -c pass", "pytest | tee out", "pytest>out"):
            try:
                chongdae.run_checked(pj.dir, [line])
                assert False, line
            except SystemExit as e:
                assert "not a shell line" in str(e), (line, e)
        for line, code in (("no-such-command-xyz", "exit 127"), (sys.executable + " -c 'input()'", "exit 1")):
            try:
                chongdae.run_checked(pj.dir, [line])
                assert False, line
            except SystemExit as e:
                assert code in str(e), (line, e)
        os.environ["CHONGDAE_CHECK_TIMEOUT"] = "1"
        try:
            chongdae.run_checked(pj.dir, [sys.executable + " -c 'import time; time.sleep(5)'"])
            assert False
        except SystemExit as e:
            assert "exit 124" in str(e) and "timed out" in str(e), e
        finally:
            os.environ.pop("CHONGDAE_CHECK_TIMEOUT")
    blocked = {"status": "blocked", "summary": "no port here", "verified": [], "decisions": [], "non-claims": []}
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(blocked)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "w", "--role", "implementer", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == chongdae.DECISION
        assert run("retry", "w", "--requires", "loopback", "--checked", sys.executable + " -c 'raise SystemExit(1)'", "--target", pj.dir)[0] != 0
        plan = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "plan.json")))
        assert not [t for t in plan["tasks"] if t.get("requires")], plan
        # what a verifier read of an attempt, and what chongdae ran for it, go with that attempt on a retry
        d = chongdae.run_dir(pj.dir)
        state = chongdae.load_state(d)
        state["tasks"]["w"]["seen-non-claims"] = {"by": "verifier of w", "texts": ["(provider) x"]}
        state["tasks"]["w"]["checked"] = {"ran": [{"command": "c", "exit": 0, "tail": []}], "checked-tree": {}}
        chongdae.save_state(d, state)
        assert run("retry", "w", "--target", pj.dir)[0] == 0
        ts = pj.state()["tasks"]["w"]
        assert "seen-non-claims" not in ts and "checked" not in ts and ts["attempts"][-1]["seen-non-claims"]["texts"] == ["(provider) x"], ts


def test_take_and_retry_checked_run_the_command_record_it_and_hand_it_to_the_verifier():
    """guin-site write-bsky-build, 2026-10-10: the session took the build, ran the full test run itself (exit 0) and had nowhere
    to put it; the verifier rejected the builder's old claim three more times. `--checked` is a command chongdae runs itself:
    exit 0 is recorded and goes to the verifier with what changed after; a failure refuses, recording nothing."""
    blocked = {"status": "blocked", "summary": "no port here", "verified": [], "decisions": [], "non-claims": []}
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        eyes = os.path.join(pj.dir, "eyes.py")
        write(eyes, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                    "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept', 'findings': []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(blocked), "verifier": [sys.executable, eyes, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "w", "--role", "implementer", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == chongdae.DECISION
        write(os.path.join(pj.dir, "w.py"), "x = 1\n")
        code, out = run("take", "w", "--why", "the sandbox had no port", "--checked", sys.executable + " -c 'raise SystemExit(3)'", "--target", pj.dir)
        assert code != 0 and "exit 3" in out and "taken" not in pj.state()["tasks"]["w"], out
        code, out = run("take", "w", "--why", "the sandbox had no port", "--checked", sys.executable + " -c 'print(\"all 135 OK\")'", "--target", pj.dir)
        assert code == 0 and "checked by chongdae" in out, out
        ck = pj.state()["tasks"]["w"]["checked"]["ran"][0]
        assert ck["exit"] == 0 and ck["tail"] == ["all 135 OK"], ck
        write(os.path.join(pj.dir, "w.py"), "x = 2\n")   # changed after the check: the verifier is told
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        req = json.load(open(glob.glob(os.path.join(chongdae.run_dir(pj.dir), "local", "w.verify*request*.seen"))[0]))
        assert req["checked"][0]["tail"] == ["all 135 OK"] and req["checked"][0]["changed_since"] == ["w.py"], req.get("checked")
    with Project() as pj:   # retry --checked: the same evidence, and a failing one refuses the retry
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(blocked)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "w", "--role", "implementer", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == chongdae.DECISION
        assert run("retry", "w", "--checked", sys.executable + " -c 'raise SystemExit(1)'", "--target", pj.dir)[0] != 0
        assert not pj.state()["tasks"]["w"].get("attempts"), "refused before anything was recorded"
        code, out = run("retry", "w", "--checked", sys.executable + " -c 'pass'", "--target", pj.dir)
        assert code == 0 and pj.state()["tasks"]["w"]["attempts"][-1]["retried"]["checked"] == [sys.executable + " -c 'pass'"], out


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
            rd = chongdae.run_dir(pj.dir)
            rec = json.load(open(os.path.join(rd, "tasks", "T1.json"), encoding="utf-8"))
            trace = rec["performed_by"]["trace"]
            assert trace["commands-run"] == 1 and "commands" not in trace and trace["changed"] == ["write ./NOTES.md"], trace   # lines stay local
            assert "session" not in rec["performed_by"] and rec["performed_by"]["model"] == "m", rec   # the session is this machine's (local/)
            assert "secret" not in json.dumps(rec) and trace["elsewhere"].startswith("1 command"), trace
            assert not any(n.endswith(".trace.json") for n in os.listdir(rd)), os.listdir(rd)   # no trace files beside the record
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
            code, out = run("add", "T1", "--check", "python3 -c pass " + plugin_check + " " + home + "/x", "--role", "session", "--target", pj.dir)
            assert code != 0 and "--why" in out, out   # the lock has an implementer: the session doing a build itself is a decision, with a reason
            assert run("add", "T1", "--check", "python3 -c pass " + plugin_check + " " + home + "/x", "--role", "session", "--why", "one line, quicker than a call", "--target", pj.dir)[0] == 0
            ts = pj.state()["tasks"]["T1"]
            assert ts["self-performed"]["instead-of"] == "implementer" and ts["self-performed"]["why"] == "one line, quicker than a call", ts["self-performed"]
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
            asked = open(os.path.join(rd, "asked", "T2.json"), encoding="utf-8").read()
            assert json.loads(asked)["task"] == "T2" and pj.dir not in asked and home not in asked, asked
            assert run("close", *UNCOMMITTED, "--target", pj.dir)[0] == 0
            tracked = subprocess.run(["git", "ls-files"], cwd=pj.dir, capture_output=True, text=True).stdout.split()
            assert any(t.endswith("asked/T2.json") for t in tracked) and not any("/local/" in t or t.endswith(".request.json") for t in tracked), tracked
            # the run's root is the record and nothing else: no work file beside it, the work under local/
            assert set(os.listdir(rd)) <= {"plan.json", "state.json", "tasks", "asked", "contract", "delegations", "local"}, os.listdir(rd)
            assert {"T2.request.json", "T2.response.json"} <= set(os.listdir(os.path.join(rd, "local"))), os.listdir(os.path.join(rd, "local"))
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
        assert run("close", *UNCOMMITTED, "--target", pj.dir)[0] == 0
        code, out = run("recheck", "--target", pj.dir)
        assert code == 0 and "still green  %s/a-build" % os.path.basename(chongdae.run_dir(pj.dir)) in out and "recheck: 1 green" in out, out
        assert not os.path.exists(os.path.join(pj.dir, ".chongdae", "rechecks")), "the verdict is printed and returned; nothing is filed"


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
            assert code == chongdae.WAITING and out.startswith("still working: T1: the provider is still working (pid") and "again keeps waiting" in out, out
            d = chongdae.run_dir(pj.dir)
            assert os.path.exists(os.path.join(d, "local", "T1.pending.json")) and "response" not in pj.state()["tasks"]["T1"]
            chongdae.WAIT_BUDGET = 30
            code, out = run("run", "--target", pj.dir)
            assert code == 0, out
            assert pj.state()["tasks"]["T1"]["status"] == "done" and not os.path.exists(os.path.join(d, "local", "T1.pending.json"))
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
            assert code == chongdae.WAITING and "still working" in out and dt < 6, (out, dt)   # quibble took ~2s, the builder then hit the call's remaining budget — not a fresh 3s of its own
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
            assert hook("session_start.py", {"cwd": pj.dir}, AGENT_WORKER="1") == (0, ""), "a worker session: the run is the hiring session's"
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
            code, out = run("close", *UNCOMMITTED, "--target", pj.dir)
            assert code == 0 and "2 task(s) done, 1 open (T3), 1 dropped (T4)" in out, out
            assert pj.state()["status"] == "complete" and "open" not in pj.state()   # open tasks are the tasks' statuses; `report`/`status` recount them
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
            run("close", *UNCOMMITTED, "--target", pj.dir)
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
        # the report shows whose words a ref points at — the delegation's `by` and `why` had no reader before 1.12.1
        refs = [f["text"] for f in doc["findings"] if f["kind"] == "delegated" and "ref %s" % did in f["text"]]
        assert refs and all("ref %s (kim: owner pre-approved this run)" % did in t for t in refs), refs
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
    """A worker's whole session and the request as sent carry this machine's paths and can be megabytes; they stay under the
    run's local/, out of git. The author line in the record gets `trace`: the files changed, how many commands ran and
    failed, the project as `.` and home as `~`; the command lines go to this machine's overlay. A session an earlier version
    committed beside the record leaves the index at the next record commit."""
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
        write(os.path.join(run_dir, "local", "b.response.transcript.jsonl"), "\n".join(json.dumps(x) for x in lines) + "\n")
        response = {"status": "done", "worker": {"host": "codex", "model": "m", "session": "s-1", "transcript": "b.response.transcript.jsonl"}}
        who = chongdae.with_trace(chongdae.performer(["w"], argv=["w"], response=response), response, run_dir, tmp)
        # the record keeps what the worker changed and how its commands ended; the command lines and the session stay local
        pub, priv = chongdae.split_private(who)
        assert pub["trace"] == {"changed": ["update ./build.py"], "commands-run": 2, "commands-failed": 0} and "commands" not in pub and "session" not in pub, pub
        assert priv["commands"][0] == {"command": "python3 -m unittest discover -s tests -p 'test_s[12].py'", "exit": 0} and priv["commands"][1]["command"] == "cat ~/.codex/skill.md", priv
        write(os.path.join(run_dir, "state.json"), "{}")
        # an earlier version committed a session beside the record: it must leave the index, and stay on disk
        write(os.path.join(run_dir, "a.response.transcript.1.jsonl"), json.dumps(lines[1]) + "\n")
        git("add", "-f", ".chongdae/run-x/a.response.transcript.1.jsonl"); git("commit", "-qm", "old")
        assert chongdae.commit_record(tmp, "run-x", "test")
        tracked = git("ls-files").stdout.split()
        assert tracked == [".chongdae/.gitignore", ".chongdae/run-x/state.json"], tracked
        assert os.path.exists(os.path.join(run_dir, "a.response.transcript.1.jsonl")), "local copy kept"
        assert open(os.path.join(tmp, ".chongdae", ".gitignore")).read().split("\n")[2] == "local/", "one line says what stays: the run's local/"
        assert chongdae.neutral_path("rg --files %s/.codex/plugins/cache/some-market | rg x" % home, tmp) == "rg --files <codex-plugins> | rg x"
        assert chongdae.neutral_path("sed -n 1p ~/.claude/plugins/cache/m/hacheong/1.2.0/worker.py", tmp) == "sed -n 1p <plugin:hacheong@1.2.0>/worker.py"
        assert chongdae.neutral_path("D=/private/tmp/claude-1/x-y/scratch/a.json && ls", tmp) == "D=<tmp> && ls"
        assert chongdae.neutral_path("cat %s/.claude/projects/%s-src/s.jsonl" % (home, home.replace(os.sep, "-")), tmp) == "cat ~/.claude/projects/~-src/s.jsonl"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_lock_says_who_does_a_task_and_the_session_says_why_when_it_does_it_itself():
    """Seen on a site: 43 tasks in a day, every one `role: session` — nobody chose that; `add` defaulted to the session and a
    model at work does the work. Now the lock says: a task with checks goes to its `implementer`, a task that writes the
    contract's tests to its `nitpick`; the session does what nothing is declared for, or what it takes with a reason —
    recorded on the task (`self-performed`) and reported as an observation, its reason counted like a delegation's."""
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE),
                                                                  "nitpick": pj.fake_provider({"status": "done", "summary": "wrote", "non-claims": [], "tests": ["test_a.py"]}, name="teujip")}})
        # the fake nitpick writes the file it names: a build whose protected tests are absent stops at its start
        with io.open(os.path.join(pj.dir, "teujip.py"), "a", encoding="utf-8") as fh:
            fh.write("open('test_a.py', 'w').write('# written by the nitpick\\n')\n")
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        code, out = run("add", "plan", "--brief", "a plan section", "--target", pj.dir)
        assert code == 0 and "Work, then" in out, out   # nothing declared for a plan: the session's own
        assert run("add", "model", "--brief", "the model", "--target", pj.dir)[0] == 0
        # two no-check tasks say "done is the agent's word" once, together — not once per task
        said = [n for n in chongdae.non_claims(pj.state()) if "no check decides" in n]
        assert said == ["no check decides this task; done means the agent said so — 2 task(s): plan, model"], said
        code, out = run("add", "tests", "--tests", "test_a.py", "--target", pj.dir)
        assert code == 0 and "nitpick does it (the lock's provider)" in out, out
        code, out = run("add", "build", "--tests", "test_a.py", "--check", sys.executable + " -c pass", "--target", pj.dir)
        assert code == 0 and "implementer does it (the lock's provider)" in out, out
        code, out = run("add", "own", "--check", sys.executable + " -c pass", "--role", "session", "--target", pj.dir)
        assert code != 0 and "--why" in out and "'implementer'" in out, out
        assert run("add", "own", "--check", sys.executable + " -c pass", "--role", "session", "--why", "a one-line fix", "--target", pj.dir)[0] == 0
        assert run("add", "own2", "--check", sys.executable + " -c pass", "--role", "session", "--why", "a one-line fix", "--by", "kim", "--target", pj.dir)[0] == 0
        defs = {tid: ts["def"]["role"] for tid, ts in pj.state()["tasks"].items()}
        assert defs == {"plan": "session", "model": "session", "tests": "nitpick", "build": "implementer", "own": "session", "own2": "session"}, defs
        assert run("run", "plan", "model", "--target", pj.dir)[0] == 0
        st = pj.state()["tasks"]
        assert st["tests"]["performed_by"]["provider"] == "command" and st["build"]["performed_by"]["provider"] == "command" and st["own"]["performed_by"]["provider"] == "session"
        assert st["own2"]["self-performed"]["by"] == "kim" and st["own"]["self-performed"]["instead-of"] == "implementer"
        doc = json.loads(run("report", "--target", pj.dir)[1])
        own = [f for f in doc["findings"] if f["kind"] == "self-performed"]
        assert len(own) == 2 and all(f["layer"] == "observation" and "a one-line fix" in f["text"] for f in own), own
        # a project with nothing declared: the session does everything, and says nothing about it
    with Project() as pj:
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "b", "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0
        assert pj.state()["tasks"]["b"]["def"]["role"] == "session" and "self-performed" not in pj.state()["tasks"]["b"]


def test_a_refused_report_stands_when_the_checks_pass_here_and_two_shapes_of_task_are_refused_at_add():
    """A site's refactoring lost eighteen minutes to three things a tool can refuse or route: a validator refused a true
    report twice for the spelling of a `sh -c` check (each refusal a build and a wait), the session had written that
    shell line as one check, and it had sent a helper-moving task to the nitpicker with a check of its own."""
    with Project() as pj:
        # the worker did the work and ran the checks; the validator did not recognize the command's spelling
        refused = dict(RESPONSE_DONE, status="failed", **{"non-claims": ["checks-ran: `sh -c 'x && y'` is claimed verified but no such command appears in the session's transcript"]})
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(refused)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "the checks pass here" in out and "sent back" not in out, out
        ts = pj.state()["tasks"]["T1"]
        assert ts["status"] == "done" and ts["checks-ran-overruled"]["refused"][0].startswith("checks-ran:") and not ts.get("attempts"), ts
        assert any("the report stands as the worker's word" in n for n in ts["non-claims"]), ts["non-claims"]
        # the same refusal on a task whose checks fail here: back to the hands, as before
        assert run("add", "T2", "--check", sys.executable + " -c 'raise SystemExit(1)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "sent back to the provider automatically" in out, out
        # a shell line is not a check; a nitpick task has no check of its own
        code, out = run("add", "T3", "--check", "sh -c 'python3 build.py && git diff --exit-code'", "--target", pj.dir)
        assert code != 0 and "a check is one command" in out, out
        code, out = run("add", "T4", "--role", "nitpick", "--tests", "tests/test_x.py", "--check", sys.executable + " -c pass", "--target", pj.dir)
        assert code != 0 and "a nitpick task writes the contract's tests and has no check of its own" in out, out


def test_the_runner_places_the_reviewer_when_a_run_ends():
    """dwitbuk's review never ran on a site with 22 runs: no product called it, and a skill is the session's discretion. The
    reviewer is placed by the runner, like the verifier — the lock's `reviewer` role runs when a run ends (close, complete);
    what it wrote is part of the closing record and goes into that commit; what it said last is kept. No reviewer: a non-claim."""
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir, check=True)
        reviewer = os.path.join(pj.dir, "reviewer.py")
        write(reviewer, "import json, os, sys\nos.makedirs('reviews', exist_ok=True)\n"
                        "runs = [d for d in os.listdir('.chongdae') if d.startswith('run-')]\n"
                        "json.dump({'runs': runs}, open('reviews/review-1.json', 'w'))\nprint('review-1: 2 objection(s)')\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"reviewer": [sys.executable, reviewer]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--brief", "b", "--target", pj.dir)[0] == 0
        assert run("run", "T1", "--target", pj.dir)[0] == 0
        code, out = run("close", "--target", pj.dir)
        assert code == 0 and "reviewer: review-1: 2 objection(s) — wrote reviews/review-1.json" in out, out
        st = pj.state()
        assert st["reviewed"]["said"] == "review-1: 2 objection(s)" and st["reviewed"]["wrote"] == ["reviews/review-1.json"] and st["reviewed"]["by"]["argv"][1] == reviewer, st["reviewed"]
        assert json.load(open(os.path.join(pj.dir, "reviews", "review-1.json")))["runs"] == [os.path.basename(chongdae.run_dir(pj.dir))], "the reviewer saw the run complete"
        shown = subprocess.run(["git", "show", "--name-only", "--format=%s", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert shown.startswith(os.path.basename(chongdae.run_dir(pj.dir)) + ": close — g") and "reviews/review-1.json" in shown, shown
        assert not subprocess.run(["git", "status", "--porcelain", "--", "reviews", ".chongdae"], cwd=pj.dir, capture_output=True, text=True).stdout.strip(), "the review and the record are committed, nothing of them left over"
    with Project() as pj:
        # no reviewer declared: the run closes, and the record says nobody reviewed it
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("close", "--target", pj.dir)[0] == 0
        assert any("no `reviewer` role" in n for n in pj.state()["non-claims"]), pj.state()["non-claims"]
    with Project() as pj:
        # a plan run's `complete` places it too, and a reviewer that fails is a non-claim, not a stop
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"reviewer": [sys.executable, "-c", "raise SystemExit('no reporters here')"]}})
        plan = {"artifact-type": "chongdae/plan@1", "goal": "p", "providers": {"b": [sys.executable, "-c", "import json,sys; json.dump({'status': 'done', 'summary': 's', 'verified': [], 'decisions': [], 'non-claims': []}, open(sys.argv[2], 'w'))", "{request}", "{response}"]},
                "tasks": [{"id": "T", "role": "b", "checks": [[sys.executable, "-c", "pass"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "complete" in out, out
        st = pj.state()
        assert st["reviewed"]["exit"] == 1 and any("the reviewer exited 1" in n for n in st["non-claims"]), st
    with Project() as pj:
        # a reviewer that cannot even be resolved here (a plugin this machine lacks) — seen on a trial clone: `close` had set the
        # run complete, then died resolving the argv, leaving a complete run with its task open and no close commit
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"reviewer": ["python3", "{plugin:nope}/x.py"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        code, out = run("close", "--target", pj.dir)
        assert code == 0 and "closed" in out, out
        st = pj.state()
        assert st["status"] == "complete" and st["reviewed"]["exit"] == 1 and "not linked" in st["reviewed"]["said"], st["reviewed"]


def test_show_tells_what_happened_in_a_run_with_its_times_and_nothing_cut():
    """Nobody could see what happened in a run after it ran: `status` shows the open run, `report` is findings for a reviewer, and
    agents read tasks/*.json with cat and guessed keys — a retrospective of one day took ~50 tool calls. `show` tells a run in
    order (who did each task, every attempt with its verdict and findings whole, the judgments, checks, touched files, times),
    `--since` gives one line per run and the totals, `--path` the tasks that touched a file. The record now keeps the times it
    lacked: when a task became done, when an attempt's answer and its verdict came back, when the run ended."""
    long_why = "the counter restarts after clear, so the next id repeats an old one — " + "a reader needs every word of this. " * 12
    reject = {**REVIEW_REJECT, "findings": [{**REVIEW_REJECT["findings"][0], "why": long_why}]}
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE), "verifier": pj.fake_provider(reject, "verifier")}})
        write(os.path.join(pj.dir, ".gitignore"), "*.py\n")   # the fake providers are not the work
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            assert run("show", "--target", pj.dir) == (0, "no run\n")
            assert run("init", "--session", "--goal", "count memos", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--brief", "the plan section", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "plan.md"), "## Q1\n")
            assert run("run", "--target", pj.dir)[0] == 0
            assert run("add", "B", "--brief", "count", "--check", sys.executable + " -c pass", "--gate", "human", "--target", pj.dir)[0] == 0
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "verifier rejected" in out, out
            ts = pj.state()["tasks"]["B"]
            # every attempt keeps when its answer and its verdict came back
            assert all(a["answered"]["at"].endswith("+00:00") and a["verdict-given"]["at"].endswith("+00:00") for a in ts["attempts"]), ts["attempts"]
            assert ts["answered"]["at"] and ts["verdict-given"]["at"] and ts["review"]["verdict"] == "reject"
            pj.fake_provider(REVIEW_ACCEPT, "verifier")
            assert run("retry", "B", "--delegated", "the owner handed this run off", "--target", pj.dir)[0] == 0
            assert run("run", "--target", pj.dir)[0] == chongdae.DECISION
            assert run("confirm", "B", "--by", "kim", "--target", pj.dir)[0] == 0
            assert run("run", "--target", pj.dir)[0] == 0
            assert run("add", "D", "--brief", "superseded piece", "--target", pj.dir)[0] == 0
            assert run("drop", "D", "--why", "superseded by B", "--target", pj.dir)[0] == 0
            assert run("add", "O", "--brief", "left for later", "--target", pj.dir)[0] == 0
            assert run("close", *UNCOMMITTED, "--target", pj.dir)[0] == 0
        finally:
            os.environ.pop("CHONGDAE_USER", None)
        st = pj.state()
        assert st["ended"]["at"].endswith("+00:00") and st["tasks"]["T1"]["done"]["at"] and st["tasks"]["B"]["done"]["at"] == st["tasks"]["B"]["confirmed"]["at"]
        code, out = run("show", "--target", pj.dir)
        assert code == 0, out
        name = os.path.basename(chongdae.run_dir(pj.dir))
        assert out.startswith("run %s — session, complete\ngoal: count memos\n" % name), out
        assert "· ended " in out and "· took " in out and "(from git" not in out, out   # the record's own times
        assert "tasks 4: 2 done, 1 dropped, 1 open · 0 self-performed (0 taken) · 5 attempt(s) · 3 verifier reject(s) · 1 delegated" in out, out
        assert long_why in out, "a finding is never cut"
        assert "attempt 4: done, answered " in out and "verifier: accept at " in out and "retried at " in out and "delegated: the owner handed this run off" in out, out
        assert "by chongdae (auto: the verifier rejected: 1 finding(s))" in out, out
        assert "who: implementer → command " in out and "verified by: command " in out, out
        assert "checks (passed here when the task was produced):" in out and "confirmed at " in out and "by kim" in out, out
        assert "dropped at " in out and "superseded by B" in out and "touched: plan.md" in out, out
        assert "\nleft open: O (todo)\n" in out and "reviewer" in out, out
        b = out[out.index("\nB  done"):out.index("\nD  dropped")]
        assert "added " in b and " done " in b and "took " in b, b
        # --since: one line per run, and the totals
        code, out = run("show", "--since", base, "--target", pj.dir)
        lines = out.strip().split("\n")
        assert code == 0 and len(lines) == 2 and lines[0].startswith(name + "  complete  ") and lines[0].endswith("— count memos"), out
        assert lines[1].startswith("total: 1 run(s) · tasks 4: 2 done, 1 dropped, 1 open") and "3 verifier reject(s) · 1 delegated" in lines[1], out
        assert run("show", "--since", "HEAD", "--target", pj.dir)[1] == "no run since HEAD\n"
        # --path: the tasks that touched a file, newest first
        code, out = run("show", "--path", "./plan.md", "--target", pj.dir)
        assert code == 0 and out.startswith(name) and "\n  T1  done  session (" in out and "the plan section" in out, out
        assert "no task in any run recorded touching nope.py" in run("show", "--path", "nope.py", "--target", pj.dir)[1]
        # a run recorded before these times existed: its end comes from the close commit, and says so
        rd = chongdae.run_dir(pj.dir)
        sf = os.path.join(rd, "state.json")
        old = chongdae.load(sf); old.pop("ended"); write(sf, old)
        for tid in ("T1", "B"):
            tf = os.path.join(rd, "tasks", tid + ".json")
            t = chongdae.load(tf); t.pop("done"); write(tf, t)
        code, out = run("show", "--run", name, "--target", pj.dir)
        assert "ended " in out and "(from git)" in out and "· took " in out, out
        assert "done — its time not recorded (an older chongdae); by the run's end, " in out, out
        assert run("show", "--run", "run-nope", "--target", pj.dir)[0] != 0


def test_a_run_reviewed_before_since_does_not_claim_a_change_made_after_it():
    """`report --since REV` asks which changes since REV no run claims. Every completed run's `touched` used to claim, so a path
    some old run once touched hid a later change made outside any run. Only the runs whose work falls in the range claim it:
    the runs whose record was not complete at REV (the ones `--since` already reviews); an earlier run's work was in the tree
    there. Without --since the range is the whole history, and every completed run claims."""
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "a.py"), "x = 0\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            assert run("init", "--session", "--goal", "old work", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--brief", "a", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "a.py"), "x = 1\n")
            assert run("run", "--target", pj.dir)[0] == 0
            subprocess.run(["git", "commit", "-qam", "the old run's work"], cwd=pj.dir, check=True)
            assert run("close", *UNCOMMITTED, "--target", pj.dir)[0] == 0
            reviewed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()   # the last review covered up to here
            write(os.path.join(pj.dir, "a.py"), "x = 2\n")   # outside any run, after the review
            subprocess.run(["git", "commit", "-qam", "a change no run made"], cwd=pj.dir, check=True)
            write(os.path.join(pj.dir, "b.py"), "y = 0\n")
            assert run("init", "--session", "--goal", "new work", "--target", pj.dir)[0] == 0
            assert run("add", "T2", "--brief", "b", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "b.py"), "y = 1\n")
            assert run("run", "--target", pj.dir)[0] == 0
            assert run("close", *UNCOMMITTED, "--target", pj.dir)[0] == 0
        finally:
            os.environ.pop("CHONGDAE_USER", None)
        doc = json.loads(run("report", "--since", reviewed, "--target", pj.dir)[1])
        outside = [f["where"] for f in doc["findings"] if f["kind"] == "outside-run"]
        assert outside == ["a.py"], outside   # the old run's T1 touched a.py before the review; b.py is the new run's
        doc = json.loads(run("report", "--target", pj.dir)[1])   # the whole history: the old run claims a.py, as it always did
        assert [f["where"] for f in doc["findings"] if f["kind"] == "outside-run"] == [], doc


def test_the_other_products_records_are_known_from_the_lock_not_by_name():
    """chongdae's report and its snapshots left out `.mangsang/`, `.dwitbuk/` and `reviews/` by name — the one place a product
    knew its siblings. Now each plugin declares its record paths and the lock carries them (`record-paths`); a project
    without that key still gets the old names. At close, what the reviewer wrote is a record and still goes into the commit."""
    with Project() as pj:
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {}, "record-paths": {"alpha": [".alpha/", "alpha.json"], "beta": []}})
            assert chongdae.record_paths(pj.dir) == (".chongdae/", ".claude/", "hunsu", ".alpha/", "alpha.json")
            write(os.path.join(pj.dir, ".alpha", "x.json"), "{}")
            write(os.path.join(pj.dir, "alpha.json"), "{}")
            write(os.path.join(pj.dir, "reviews", "r.json"), "{}")   # not declared here: a sibling's name is no longer assumed
            write(os.path.join(pj.dir, "work.py"), "x = 1\n")
            doc = json.loads(run("report", "--target", pj.dir)[1])
            outside = sorted(f["where"] for f in doc["findings"] if f["kind"] == "outside-run")
            assert outside == ["reviews/r.json", "work.py"], outside
            assert set(chongdae.dirty(pj.dir)) == {"reviews/r.json", "work.py"} and ".alpha/x.json" in chongdae.dirty(pj.dir, records_too=True)
            os.remove(os.path.join(pj.dir, "hunsu.lock.json"))
            assert chongdae.record_paths(pj.dir) == (".chongdae/", ".claude/", "hunsu", ".mangsang/", ".dwitbuk/", "reviews/"), "no lock: the old names"
        finally:
            os.environ.pop("CHONGDAE_USER", None)


def test_work_the_session_committed_before_run_is_still_the_tasks():
    """`touched` measured only what differed from HEAD, so a session that committed its work before `run` recorded
    `touched: []` (guin-site's drop-nojekyll: three committed files nobody claimed, later reported as outside-run). The start
    keeps the commit it stood on; a file a commit since then changed is measured against what it was there. A task still
    open does not inherit what the done one committed, and a change committed and then undone is no change."""
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        for f in ("a.py", "b.py", "c.py"):
            write(os.path.join(pj.dir, f), "x = 0\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--brief", "a", "--target", pj.dir)[0] == 0
            assert run("add", "T2", "--brief", "b", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "a.py"), "x = 1\n")
            subprocess.run(["git", "commit", "-qam", "T1's work, committed before run"], cwd=pj.dir, check=True)
            code, out = run("run", "--target", pj.dir)
            assert code == 2 and "T2 has changed nothing of its own" in out, out   # T1 done; T2 has not started
            st = pj.state()
            assert st["tasks"]["T1"]["touched"] == ["a.py"], st["tasks"]["T1"]
            # T2 was open over the same window: a.py is T1's, not T2's; its own committed change is its
            write(os.path.join(pj.dir, "b.py"), "x = 2\n")
            subprocess.run(["git", "commit", "-qam", "T2's work"], cwd=pj.dir, check=True)
            write(os.path.join(pj.dir, "c.py"), "x = 3\n")
            subprocess.run(["git", "commit", "-qam", "tried"], cwd=pj.dir, check=True)
            write(os.path.join(pj.dir, "c.py"), "x = 0\n")
            subprocess.run(["git", "commit", "-qam", "and undone"], cwd=pj.dir, check=True)
            assert run("run", "--target", pj.dir)[0] == 0
            st = pj.state()
            assert st["tasks"]["T2"]["touched"] == ["b.py"], st["tasks"]["T2"]
        finally:
            os.environ.pop("CHONGDAE_USER", None)


def test_a_move_records_both_paths_and_a_korean_name_is_itself():
    """`git status --porcelain` wrote a rename as one string, `a -> b`, and quoted a non-ASCII name: guin-site's content move
    recorded `content/about.md -> tests/fixtures/content/about.md` as touched, which named no file, and the reviewer charged
    the three moved directories as work outside any run. Both sides of a move are the task's, and a name is itself."""
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "content", "a.md"), "a\n")
        write(os.path.join(pj.dir, "글.md"), "가\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            assert run("init", "--session", "--goal", "move", "--target", pj.dir)[0] == 0
            assert run("add", "T1", "--brief", "move content", "--target", pj.dir)[0] == 0
            os.makedirs(os.path.join(pj.dir, "tests", "fixtures"))
            subprocess.run(["git", "mv", "content", "tests/fixtures/content"], cwd=pj.dir, check=True)
            write(os.path.join(pj.dir, "글.md"), "나\n")
            assert run("run", "--target", pj.dir)[0] == 0
            touched = pj.state()["tasks"]["T1"]["touched"]
            assert touched == sorted(["content/a.md", "tests/fixtures/content/a.md", "글.md"]), touched
            subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
            subprocess.run(["git", "commit", "-qm", "the move"], cwd=pj.dir, check=True)
            assert run("close", "--target", pj.dir)[0] == 0
        finally:
            os.environ.pop("CHONGDAE_USER", None)
        doc = json.loads(run("report", "--since", base, "--target", pj.dir)[1])
        outside = [f for f in doc["findings"] if f["kind"] == "outside-run"]
        assert outside == [], outside


def test_the_session_disputes_its_own_builds_tests_and_the_fix_survives_the_next_judgment():
    """guin-site, 2026-10-02: a session build found its contract tests wrong. Every judgment of the build restored them, so the
    fix could not land; a fix task added with --tests protected the very files it fixed and restored its own fix. `dispute`
    is the session's route a provider's build has in `disputed-tests`: recorded as a judgment, the task that wrote the tests
    is reopened to amend them (or one is made), and once it is done the build takes the amended files as its contract."""
    with Project() as pj:
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE)}})
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            code, out = run("add", "tests", "--tests", "test_a.py", "--brief", "contract tests", "--target", pj.dir)
            assert code == 0 and "--tests: the tests tests writes (no check decides it)" in out, out
            write(os.path.join(pj.dir, "test_a.py"), "# wrong\n")
            assert run("run", "--target", pj.dir)[0] == 0
            check = sys.executable + " -c \"import sys; sys.exit(0 if open('test_a.py').read() == '# right\\n' and open('src.py').read() else 1)\""
            code, out = run("add", "build", "--role", "session", "--why", "the worker's sandbox cannot bind a port", "--tests", "test_a.py", "--check", check, "--target", pj.dir)
            assert code == 0 and "--tests: files build may not change — its judgment restores any change it makes to them" in out and "chongdae dispute build" in out, out
            write(os.path.join(pj.dir, "src.py"), "x = 1\n")
            write(os.path.join(pj.dir, "test_a.py"), "# right\n")   # the session fixes the test while building
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "changed the contract's tests" in out, out
            assert open(os.path.join(pj.dir, "test_a.py")).read() == "# wrong\n", "the judgment restored the contract's tests"
            # the self-defeating fix: a task with a check that protects the very tests it would correct
            code, out = run("add", "tests-fix", "--role", "session", "--why", "fix", "--tests", "test_a.py", "--check", check, "--target", pj.dir)
            assert code != 0 and "build's judgment restored test_a.py" in out and "chongdae dispute build --tests test_a.py" in out, out
            assert run("dispute", "build", "--tests", "nope.py", "--why", "x", "--target", pj.dir)[0] != 0, "only the build's protected tests"
            assert run("dispute", "tests", "--tests", "test_a.py", "--why", "x", "--target", pj.dir)[0] != 0, "a tests task protects nothing"
            code, out = run("dispute", "build", "--tests", "test_a.py::test_x", "--why", "test_x expects the wrong order", "--target", pj.dir)
            assert code == 0 and "tests reopened to amend test_a.py" in out and "the session amends them" in out, out
            st = pj.state()["tasks"]
            assert st["tests"]["status"] == "todo" and st["tests"]["amending"][0]["why"] == "test_x expects the wrong order", st["tests"]
            assert chongdae.is_agent(st["tests"]["attempts"][0]["reopened"]["by"]) and st["tests"]["attempts"][0]["touched"] == ["test_a.py"], st["tests"]["attempts"]
            assert st["build"]["attempts"][0]["retried"]["disputed"].startswith("tests disputed") and st["build"]["attempts"][0]["rejected"]["by"] == "contract", st["build"]
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "amend test_a.py as the dispute says" in out and "test_x expects the wrong order" in out, out
            write(os.path.join(pj.dir, "test_a.py"), "# right\n")
            code, out = run("run", "--target", pj.dir)
            assert code == 0 and "done tests" in out and "done build" in out, out
            st = pj.state()["tasks"]
            assert st["build"]["rebaselined"][0]["tests"] == ["test_a.py"] and "test_a.py" not in st["build"]["touched"], st["build"]
            assert st["tests"]["touched"] == ["test_a.py"], st["tests"]
            kept = chongdae.work_path(chongdae.run_dir(pj.dir), os.path.join("contract-tests", "build", "test_a.py"))
            assert open(kept).read() == "# right\n", "the build's kept copy is the amended test: a later restore keeps the fix"
            code, out = run("show", "--target", pj.dir)
            assert "(disputed: tests disputed by build; why: test_x expects the wrong order)" in out and "re-baselined at" in out, out
        finally:
            os.environ.pop("CHONGDAE_USER", None)


def test_a_dispute_with_no_writer_on_record_makes_a_tests_task_and_the_build_waits_for_it():
    """Tests committed before the run have no task on record that wrote them: the dispute makes one — the lock's nitpick when
    it declares one, else the session's — named and printed; the build waits for it even though it comes later in order."""
    with Project() as pj:
        write(os.path.join(pj.dir, "test_b.py"), "# old\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        check = sys.executable + " -c \"import sys; sys.exit(0 if open('test_b.py').read() == '# new\\n' else 1)\""
        assert run("add", "b", "--tests", "test_b.py", "--check", check, "--target", pj.dir)[0] == 0
        code, out = run("dispute", "b", "--tests", "test_b.py", "--why", "the fixture predates Q-x", "--by", "kim", "--target", pj.dir)
        assert code == 0 and "b-tests made to amend test_b.py" in out, out
        st = pj.state()["tasks"]
        assert st["b-tests"]["def"]["role"] == "session" and st["b-tests"]["def"]["tests"] == ["test_b.py"] and "the fixture predates Q-x" in st["b-tests"]["def"]["brief"], st["b-tests"]
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "b waits for b-tests" in out and "amend test_b.py" in out, out
        write(os.path.join(pj.dir, "test_b.py"), "# new\n")
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "done b-tests" in out and "done b" in out, out
        assert pj.state()["tasks"]["b"]["touched"] == [], pj.state()["tasks"]["b"]


def test_hooks_and_engine_anchor_to_the_project_not_the_shells_directory():
    """guin-site, 2026-10-02: after `cd tests` the hook payload's cwd was `<project>/tests`; the write hook found no run there and
    would refuse writes during a running run. The hooks and the engine anchor to the nearest directory holding `.chongdae/`
    (else git's top level); a path inside a run's worktree is still that worktree's."""
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir, check=True)
        sub = os.path.join(pj.dir, "tests")
        os.makedirs(sub)
        write_hook = lambda cwd, *parts: hook("pre_write.py", {"cwd": cwd, "tool_name": "Write", "tool_input": {"file_path": os.path.join(*parts)}})[0]
        assert write_hook(sub, sub, "test_x.py") == 2, "no run: refused from a subdirectory too"
        assert chongdae.project_root(sub) == pj.dir, "no record yet: git's top level"
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert write_hook(sub, sub, "test_x.py") == 0 and write_hook(sub, pj.dir, "a.py") == 0, "a running run, seen from tests/"
        out = hook("session_start.py", {"cwd": sub, "session_id": "s1", "transcript_path": "/x/s1.jsonl"})[1]
        assert "in progress" in out, out
        assert os.path.exists(os.path.join(pj.dir, chongdae.SESSIONS, "s1.json")) and not os.path.exists(os.path.join(sub, chongdae.RUNS))
        here = os.getcwd()
        try:
            os.chdir(sub)
            code, out = run("status")
            assert code == 0 and "is running" in out, out   # the engine, too: no --target from tests/
        finally:
            os.chdir(here)
        assert run("close", "--target", pj.dir)[0] == 0
        # a worktree run: its record is in the worktree; a shell inside it anchors there, not at the main tree around it
        assert run("init", "--session", "--goal", "w", "--worktree", "--target", pj.dir)[0] == 0
        wt = os.path.join(pj.dir, ".chongdae", "wt", os.listdir(os.path.join(pj.dir, ".chongdae", "wt"))[0])
        os.makedirs(os.path.join(wt, "tests"))
        assert chongdae.project_root(os.path.join(wt, "tests")) == wt
        assert write_hook(os.path.join(wt, "tests"), wt, "a.py") == 0, "the worktree's run is running"
        assert write_hook(pj.dir, wt, "a.py") == 0, "from the main tree, a path in the worktree re-anchors there"
        assert write_hook(os.path.join(pj.dir, "tests"), pj.dir, "a.py") == 2, "the main tree has no run of its own"


def test_a_task_that_requires_a_capability_goes_to_the_roles_alternate_and_the_record_says_which():
    """A role may hold capability alternates (`implementer@loopback`: the same member on a host whose sandbox can bind a port).
    A task that requires capabilities goes to the alternate covering them, the smallest set; otherwise to the plain role."""
    plain = {"status": "failed", "summary": "should not be hired", "verified": [], "decisions": [], "non-claims": []}
    with Project() as pj:
        lock = {"implementer": pj.fake_provider(plain, "plain"), "implementer@loopback": pj.fake_provider(RESPONSE_DONE, "loop"),
                "implementer@loopback+network": pj.fake_provider(plain, "both")}
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": lock})
        assert chongdae.hire(lock, {"role": "implementer"})[0] == "implementer"
        assert chongdae.hire(lock, {"role": "implementer", "requires": ["network"]})[0] == "implementer@loopback+network"
        assert chongdae.hire(lock, {"role": "implementer", "requires": ["loopback"]})[0] == "implementer@loopback", "the smallest set that covers"
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        code, out = run("add", "w", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--requires", "loopback", "--target", pj.dir)
        assert code == 0 and "implementer@loopback does it (the lock's alternate for loopback)" in out, out
        code, out = run("run", "--target", pj.dir)
        assert code == 0, out
        ts = pj.state()["tasks"]["w"]
        assert ts["status"] == "done" and ts["performed_by"]["as"] == "implementer@loopback" and "loop.py" in " ".join(ts["performed_by"]["argv"]), ts["performed_by"]
        assert ts["def"]["role"] == "implementer"
        assert "who: implementer@loopback → command" in run("show", "--target", pj.dir)[1]


def test_a_sandbox_that_lacked_a_capability_mid_task_with_no_alternate_is_taken_by_the_session_with_the_reason():
    """hacheong reports a member that failed mid-task for a missing sandbox capability: status blocked or failed, `lacked`, a
    non-claim `sandbox lacked: …`. guin-site, 2026-10-02: twice the stop listed the ways on and waited, and the session took the
    task itself. The run must go on without a person: the capability was decided once at setup (hunsu.json `capabilities`);
    decided `session`, or not decided, the session takes the task, recorded with the reason, and `run` stops only for the
    session to do the work. `report` adds one observation per run."""
    lacked = {"status": "failed", "summary": "the tests need wrangler dev", "verified": [], "decisions": [], "lacked": ["loopback"],
              "non-claims": ["sandbox lacked: loopback — wrangler dev could not bind 127.0.0.1:8787"]}
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.json"), {"capabilities": {"loopback": "session"}})
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(lacked, "plain") + ["--member", "dakdol", "--host", "codex"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "w", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        assert run("add", "x", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        last = out.strip().splitlines()[-1]
        assert code == chongdae.DECISION and last.startswith("decision: session agent: w: the tests need wrangler dev (implementer) — taken by the session: "
                                                              "dakdol on codex lacked loopback; no implementer@loopback in the lock (hunsu.json capabilities: loopback: session)"), out
        assert "human" not in last and "decision the contract does not give" not in out, out
        ts = pj.state()["tasks"]["w"]
        assert ts["taken"]["for-lack"] == {"role": "implementer", "lacked": ["loopback"], "capabilities": {"loopback": "session"}, "member": "dakdol", "host": "codex"}, ts["taken"]
        assert ts["attempts"][0]["performed_by"], "who made the stopped attempt stays with it"
        code, out = run("run", "--target", pj.dir)   # w's checks pass: done; x goes out and lacks loopback too
        assert code == chongdae.DECISION and "done w" in out and "decision: session agent: x:" in out, out
        assert run("run", "--target", pj.dir)[0] == 0
        assert run("close", "--target", pj.dir)[0] == 0
        doc = json.loads(run("report", "--target", pj.dir)[1])
        lack = [f for f in doc["findings"] if f["kind"] == "taken-for-lack"]
        assert len(lack) == 1 and lack[0]["layer"] == "observation", lack
        assert lack[0]["text"] == "taken for lack: 2 task(s) — implementer lacked loopback (no implementer@loopback; capabilities: loopback: session)", lack
        assert not [f for f in doc["findings"] if f["kind"] == "delegation-stamp"], "chongdae's own reason is not a stamp"
        assert chongdae.sandbox_lacked({"non-claims": ["sandbox lacked: network (npm install)"]}) == ["network"]
        assert chongdae.sandbox_lacked({"non-claims": ["nothing"]}) is None


def test_a_capability_stop_with_the_alternate_in_the_lock_sends_the_task_there_with_no_question():
    """The lock already holds the hire the question would ask for: a member that lacked loopback mid-task (its task said nothing
    of it) goes to `<role>@loopback` — the task requires loopback now, the attempt is kept, no person is asked."""
    lacked = {"status": "failed", "summary": "the tests need wrangler dev", "verified": [], "decisions": [], "lacked": ["loopback"],
              "non-claims": ["sandbox lacked: loopback — wrangler dev could not bind 127.0.0.1:8787"]}
    with Project() as pj:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(lacked, "plain"),
                                                                  "implementer@loopback": pj.fake_provider(RESPONSE_DONE, "loop")}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "w", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "decision:" not in out and "goes to implementer@loopback" in out, out
        ts = pj.state()["tasks"]["w"]
        assert ts["status"] == "done" and ts["def"]["requires"] == ["loopback"] and ts["performed_by"]["as"] == "implementer@loopback", ts
        assert ts["attempts"][0]["retried"]["by"] == "chongdae" and ts["attempts"][0]["retried"]["requires"] == ["loopback"], ts["attempts"]
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "w.request.json")))
        assert req["needs"] == ["loopback"], req
        # a person's retry can say it on the task too, for a stop of another kind
        blocked = {"status": "blocked", "summary": "the contract is silent on the port", "verified": [], "decisions": [], "non-claims": []}
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(blocked, "plain"),
                                                                  "implementer@loopback": pj.fake_provider(RESPONSE_DONE, "loop")}})
        assert run("add", "v", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "decision the contract does not give" in out, out
        code, out = run("retry", "v", "--requires", "loopback", "--by", "kim", "--target", pj.dir)
        assert code == 0 and "it requires loopback now; the lock's implementer@loopback does it" in out, out
        assert run("run", "--target", pj.dir)[0] == 0
        assert pj.state()["tasks"]["v"]["performed_by"]["as"] == "implementer@loopback"



def test_two_open_session_tasks_the_first_to_finish_does_not_silently_own_the_others_file():
    """guin-site run-20261002-065900-f588: escape-tests (added first, a check that did not look at the code) and escape-build were
    open together. The session wrote src/lib/outputs.ts for escape-build before adding it, so escape-build's start held it;
    escape-tests finished first and counted it as its own; escape-build's diff was empty, the verifier rejected it on every
    retry (retry did not measure again), and the drop-and-add that followed recorded nothing. Now `run` says whose the file
    might be, `retry` measures again and names it, and `adopt` is the judgment that moves it."""
    with Project() as pj:
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            eyes = os.path.join(pj.dir, "eyes.py")
            write(eyes, "import json, sys\nreq = json.load(open(sys.argv[1], encoding='utf-8'))\nok = bool(req.get('touched'))\n"
                        "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept' if ok else 'reject', 'findings': [] if ok else "
                        "[{'kind': 'record-vs-tree', 'where': 'src/out.ts', 'why': 'touched is empty beside the work', 'record_quote': 'touched: []', "
                        "'tree_quote': 'escaped'}]}, open(sys.argv[2], 'w', encoding='utf-8'))\n")
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"verifier": [sys.executable, eyes, "{request}", "{response}"]}})
            write(os.path.join(pj.dir, "src", "out.ts"), "plain\n")
            write(os.path.join(pj.dir, "tests", "test_bots.py"), "# old\n")
            subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
            assert run("init", "--session", "--goal", "escape", "--target", pj.dir)[0] == 0
            assert run("add", "escape-tests", "--check", sys.executable + " -c pass", "--brief", "PLAN Q-bots: link text escapes [ and ]; tests/test_bots.py checks it", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "PLAN.md"), "## Q-bots\nescape [ and ]\n")
            write(os.path.join(pj.dir, "tests", "test_bots.py"), "# new\n")
            write(os.path.join(pj.dir, "src", "out.ts"), "escaped\n")   # escape-build's work, written before escape-build was added
            check = sys.executable + " -c \"import sys; sys.exit(0 if open('src/out.ts').read() == 'escaped\\n' else 1)\""
            assert run("add", "escape-build", "--check", check, "--tests", "tests/test_bots.py", "--brief", "src/out.ts llmsTxt: escape [ and ] in link text", "--target", pj.dir)[0] == 0
            code, out = run("run", "--target", pj.dir)
            assert code == chongdae.DECISION and "done escape-tests" in out and "verifier rejected" in out, out
            assert ("note: src/out.ts was already changed when escape-build was added" in out and "`chongdae adopt escape-build src/out.ts --why WHY`" in out), out
            st = pj.state()["tasks"]
            assert "src/out.ts" in st["escape-tests"]["touched"] and st["escape-tests"]["shared"] == {"src/out.ts": ["escape-build"]}, st["escape-tests"]
            req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "escape-build.verify.request.json"), encoding="utf-8"))
            assert req["touched"] == [] and req["attribution"] == {"held-at-start": ["src/out.ts"]}, req
            # a dispute on a file the build does not protect says what to do
            code, out = run("dispute", "escape-build", "--tests", "PLAN.md", "--why", "x", "--target", pj.dir)
            assert code != 0 and "PLAN.md: no open build protects it" in out and "change it in this task (escape-build)" in out, out
            # retry measures again and names what the measure leaves out
            code, out = run("retry", "escape-build", "--by", "kim", "--target", pj.dir)
            assert code == 0 and "measured now: nothing" in out and "src/out.ts: already changed when escape-build was added" in out and "chongdae adopt escape-build src/out.ts" in out, out
            assert pj.state()["tasks"]["escape-build"]["attempts"][-1]["retried"]["measured"] == [], pj.state()["tasks"]["escape-build"]["attempts"]
            assert run("adopt", "escape-build", "nope.ts", "--why", "x", "--target", pj.dir)[0] != 0, "nothing changed it: nothing to attribute"
            code, out = run("adopt", "escape-build", "src/out.ts", "--why", "written for it before it was added", "--target", pj.dir)
            assert code == 0 and "adopted src/out.ts into escape-build (from escape-tests: src/out.ts)" in out and "`chongdae run` decides it" in out, out
            st = pj.state()["tasks"]
            assert "src/out.ts" not in st["escape-tests"]["touched"] and st["escape-tests"]["gave"][0]["to"] == "escape-build" and "shared" not in st["escape-tests"], st["escape-tests"]
            assert chongdae.is_agent(st["escape-build"]["adopted"][0]["by"]) and st["escape-build"]["adopted"][0]["from"] == {"escape-tests": ["src/out.ts"]}, st["escape-build"]
            code, out = run("run", "--target", pj.dir)
            assert code == 0 and "done escape-build" in out, out
            assert pj.state()["tasks"]["escape-build"]["touched"] == ["src/out.ts"], pj.state()["tasks"]["escape-build"]
            code, out = run("show", "--target", pj.dir)
            assert "adopted src/out.ts (from escape-tests: src/out.ts) — by the session (" in out and "gave src/out.ts to escape-build at" in out, out
            # the brief reads (jokbo): a note on the file, the map
            code, out = run("show", "--path", "src/out.ts", "--brief", "--target", pj.dir)
            lines = out.strip().splitlines()
            assert code == 0 and len(lines) == 1 and lines[0].startswith("last changed in run-") and "task escape-build: src/out.ts llmsTxt" in lines[0], out
            assert run("show", "--path", "nothing.txt", "--brief", "--target", pj.dir) == (0, ""), "nothing on record: nothing printed"
            code, out = run("show", "--brief", "--target", pj.dir)
            assert code == 0 and out == "1 run (1 this week), none closed yet\n", out
            assert run("close", *UNCOMMITTED, "--target", pj.dir)[0] == 0
            code, out = run("show", "--brief", "--target", pj.dir)
            assert code == 0 and out.startswith("1 run (1 this week), last closed: escape (") and len(out.strip().splitlines()) == 1, out
            assert run("show", "--run", os.path.basename(chongdae.run_dir(pj.dir)), "--brief", "--target", pj.dir)[0] != 0
        finally:
            os.environ.pop("CHONGDAE_USER", None)


def test_a_file_both_open_tasks_measure_is_said_and_left_to_both_until_adopted():
    """The other order: both tasks open, the file written after both were added, the second one's brief naming it. The first to
    finish counts it and says so; it is not pinned away from the second (a guess), which keeps measuring it; a file the second
    does not name is pinned as before. `adopt` settles it; a dropped or open task that changed a file is the note's second line."""
    with Project() as pj:
        os.environ["CHONGDAE_USER"] = "kim"
        try:
            write(os.path.join(pj.dir, "README.md"), "# r\n")
            subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "a", "--brief", "the plan section", "--target", pj.dir)[0] == 0
            assert run("add", "b", "--brief", "write src/x.py", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "PLAN.md"), "# plan\n")
            write(os.path.join(pj.dir, "src", "x.py"), "x = 1\n")
            code, out = run("show", "--path", "src/x.py", "--brief", "--target", pj.dir)
            assert out.startswith("open now: task b in run-") or out.startswith("open now: task a in run-"), out
            code, out = run("run", "--target", pj.dir)
            assert code == 0 and "done a" in out and "done b" in out and "note: src/x.py changed after b was added, and b's brief names it" in out, out
            st = pj.state()["tasks"]
            assert st["a"]["touched"] == ["PLAN.md", "src/x.py"] and st["a"]["shared"] == {"src/x.py": ["b"]}, st["a"]
            assert "src/x.py: also b's by its own word — whose it is was not settled (`adopt`)" in run("show", "--target", pj.dir)[1]
            assert st["b"]["touched"] == ["src/x.py"] and st["b"]["pinned"] == {"PLAN.md": "a"}, st["b"]
            code, out = run("adopt", "b", "src/x.py", "--why", "b's work", "--delegated", "owner: settle it", "--target", pj.dir)
            assert code == 0 and "from a: src/x.py" in out, out
            st = pj.state()["tasks"]
            assert st["a"]["touched"] == ["PLAN.md"] and "shared" not in st["a"] and st["b"]["adopted"][0]["delegated"] == "owner: settle it", st
            assert run("add", "c", "--brief", "try README", "--target", pj.dir)[0] == 0
            write(os.path.join(pj.dir, "README.md"), "# r2\n")
            assert run("drop", "c", "--why", "superseded", "--target", pj.dir)[0] == 0
            code, out = run("show", "--path", "README.md", "--brief", "--target", pj.dir)
            assert code == 0 and out.startswith("dropped: task c in run-") and "superseded" in out and len(out.strip().splitlines()) == 1, out
        finally:
            os.environ.pop("CHONGDAE_USER", None)


@contextlib.contextmanager
def a_session(model="claude-opus-5-5"):
    """This process as a Claude Code session whose transcript names its model — the identity chongdae signs with."""
    home = tempfile.mkdtemp(prefix="chongdae-host-")
    sid = "s-test-1"
    write(os.path.join(home, "projects", "p", sid + ".jsonl"), json.dumps({"type": "assistant", "message": {"model": model}}) + "\n")
    keep = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_SESSION_ID", "AGENT_HOST", "CODEX_THREAD_ID", "CHONGDAE_USER")}
    os.environ.update({"CLAUDE_CONFIG_DIR": home, "CLAUDE_CODE_SESSION_ID": sid, "AGENT_HOST": "claude-code", "CHONGDAE_USER": "kim"})
    os.environ.pop("CODEX_THREAD_ID", None)
    try:
        yield {"agent": "claude-code " + model}
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(home, ignore_errors=True)


def test_an_omitted_by_is_the_session_and_readers_say_so():
    """guin-site, 1.17.0: an omitted --by wrote git user.name, so 73 of 80 self-performed records — and every drop, take, retry,
    claim and adopt the session decided alone — read as the owner's decision. Left out, the session signs as itself (host and
    model); a person's name is written only by --by NAME; the gates still need a person (--by) or a delegation."""
    with Project() as pj, a_session() as agent:
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_BLOCKED)}})
        assert chongdae.agent_signer(pj.dir) == agent == {"agent": "claude-code claude-opus-5-5"}
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "own", "--check", sys.executable + " -c pass", "--role", "session", "--why", "a one-line fix", "--target", pj.dir)[0] == 0
        assert run("add", "own2", "--check", sys.executable + " -c pass", "--role", "session", "--why", "the owner said so", "--by", "kim", "--target", pj.dir)[0] == 0
        assert run("add", "c", "--brief", "a note", "--target", pj.dir)[0] == 0
        code, out = run("claim", "c", "--target", pj.dir)
        assert code == 0 and "c claimed by the session (claude-code claude-opus-5-5)" in out, out
        assert run("claim", "c", "--by", "bob", "--target", pj.dir)[0] != 0, "the session's claim on kim's machine is not bob's to take"
        assert run("add", "d", "--brief", "superseded", "--target", pj.dir)[0] == 0
        assert run("drop", "d", "--why", "superseded by c", "--target", pj.dir)[0] == 0
        assert run("add", "g", "--brief", "gated", "--gate", "human", "--target", pj.dir)[0] == 0
        assert run("add", "blk", "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0
        code, out = run("run", "c", "--target", pj.dir)
        assert code == chongdae.DECISION and "human: review" in out, out
        assert run("confirm", "g", "--target", pj.dir)[0] != 0, "a gate still needs a person or a delegation"
        assert run("confirm", "g", "--by", "kim", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "provider stopped" in out, out
        code, out = run("retry", "blk", "--target", pj.dir)
        assert code == 0, out
        st = pj.state()["tasks"]
        assert st["own"]["self-performed"]["by"] == agent and st["own2"]["self-performed"]["by"] == "kim", (st["own"], st["own2"])
        assert st["d"]["dropped"]["by"] == agent and st["c"]["claimed_by"] == {**agent, "machine": "kim"} and st["c"]["status"] == "done", st["c"]
        assert st["blk"]["attempts"][0]["retried"]["by"] == agent and st["g"]["confirmed"]["by"] == "kim", st["blk"]
        shown = run("show", "--target", pj.dir)[1]
        for needle in ("self-performed: the session instead of the lock's implementer — by the session (claude-code claude-opus-5-5) at",
                       "self-performed: the session instead of the lock's implementer — by kim at", "claimed by the session (claude-code claude-opus-5-5)",
                       "dropped at", "by the session (claude-code claude-opus-5-5): superseded by c", "retried at", "confirmed at"):
            assert needle in shown, (needle, shown)
        assert "by the session (claude-code claude-opus-5-5)" in [l for l in shown.splitlines() if "retried at" in l][0], shown
        doc = json.loads(run("report", "--target", pj.dir)[1])
        own = sorted(f["text"] for f in doc["findings"] if f["kind"] == "self-performed")
        assert own == ["the session did this itself instead of the lock's implementer (decided by kim): the owner said so",
                       "the session did this itself instead of the lock's implementer (decided by the session (claude-code claude-opus-5-5)): a one-line fix"], own
        judged = {f["text"].split(" decided by")[0] for f in doc["findings"] if f["kind"] == "session-judged"}
        assert judged == {"drop", "claim", "retry after attempt 1"}, doc["findings"]
        assert all(f["by"]["agent"] == agent["agent"] and f["layer"] == "observation" and "not a person" in f["text"] for f in doc["findings"] if f["kind"] == "session-judged")


def test_the_sessions_sub_agents_are_declared_hands_and_scopes_split_one_tree():
    """guin-site run-20261004-144130-9035: the owner asked the session to dispatch its work to sub-agents; 11 sub-agents did 14
    tasks, all recorded as the session's own, and concurrent ones needed `adopt` to split the files each had been told were its
    own. A sub-agent is a provider now (`--role subagent`, or a lock role whose provider is `subagent`), not self-performed;
    `--scope` says which files each one's hands own, and a changed file is the open task's whose scope holds it most narrowly."""
    with Project() as pj, a_session():
        write(os.path.join(pj.dir, "README.md"), "# r\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": "subagent"}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        code, out = run("add", "build", "--check", sys.executable + " -c pass", "--brief", "the build", "--target", pj.dir)
        assert code == 0 and "the session's sub-agent does it (the lock's implementer)" in out, out
        code, out = run("add", "ui", "--role", "subagent", "--scope", "src/ui/", "--brief", "the pages", "--target", pj.dir)
        assert code == 0 and "the session's sub-agent does it (as asked)" in out and "--scope: src/ui — while scoped tasks are open" in out, out
        assert run("add", "api", "--role", "subagent", "--scope", "src/api", "./src/shared/api.ts", "--target", pj.dir)[0] == 0
        assert run("add", "misc", "--role", "subagent", "--scope", "src", "--target", pj.dir)[0] == 0
        assert run("add", "bad", "--role", "subagent", "--scope", "../elsewhere", "--target", pj.dir)[0] != 0, "a scope is project-relative"
        st = pj.state()["tasks"]
        assert st["api"]["def"]["scope"] == ["src/api", "src/shared/api.ts"] and all(isinstance(st[t].get("start"), dict) for t in ("build", "ui", "api", "misc")), st["api"]
        # the sub-agents work concurrently in one tree
        write(os.path.join(pj.dir, "src", "ui", "a.css"), "a {}\n")
        write(os.path.join(pj.dir, "src", "api", "x.ts"), "x\n")
        write(os.path.join(pj.dir, "src", "shared", "api.ts"), "y\n")
        write(os.path.join(pj.dir, "src", "other.ts"), "z\n")
        write(os.path.join(pj.dir, "README.md"), "# r2\n")
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and all("done %s" % t in out for t in ("build", "ui", "api", "misc")), out
        assert "note: scope: README.md is in no open task's scope (scoped and open: api, misc, ui) — build counts it by its window; `chongdae adopt TASK README.md --why WHY`" in out, out
        st = pj.state()["tasks"]
        touched = {t: st[t]["touched"] for t in ("build", "ui", "api", "misc")}
        assert touched == {"build": ["README.md"], "ui": ["src/ui/a.css"], "api": ["src/api/x.ts", "src/shared/api.ts"], "misc": ["src/other.ts"]}, touched
        for t in ("build", "ui", "api", "misc"):
            pb = st[t]["performed_by"]
            assert pb["provider"] == "subagent" and pb["host"] == "claude-code" and pb["model"] == "claude-opus-5-5" and "self-performed" not in st[t], st[t]
        t = chongdae.run_tally(chongdae.run_dir(pj.dir), {}, pj.state())
        assert t["subagent"] == 4 and t["self"] == 0, t
        shown = run("show", "--target", pj.dir)[1]
        assert "who: implementer → the session's sub-agent (claude-code, claude-opus-5-5" in shown and "who: the session's sub-agent (claude-code, claude-opus-5-5" in shown, shown
        assert "scope src/shared/api.ts" not in shown and "scope src/api, src/shared/api.ts" in shown and "4 by the session's sub-agents" in shown, shown
        doc = json.loads(run("report", "--target", pj.dir)[1])
        kinds = [f["kind"] for f in doc["findings"]]
        assert kinds.count("subagent") == 4 and "self-performed" not in kinds, doc["findings"]
        # two open tasks whose scopes hold a file alike: the first to finish counts it and says so; the other keeps measuring it
        assert run("add", "p", "--role", "subagent", "--scope", "docs", "--target", pj.dir)[0] == 0
        code, out = run("add", "q", "--role", "subagent", "--scope", "docs", "--target", pj.dir)
        assert "note: p has the same scope entry" in out, out
        write(os.path.join(pj.dir, "docs", "x.md"), "x\n")
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "note: scope: docs/x.md is in p's scope and q's alike — p counts it by its window; `chongdae adopt q docs/x.md --why WHY`" in out, out
        st = pj.state()["tasks"]
        assert st["p"]["touched"] == ["docs/x.md"] and st["p"]["shared"] == {"docs/x.md": ["q"]} and st["q"]["touched"] == ["docs/x.md"], (st["p"], st["q"])
        # an unscoped task keeps the window rule when no scoped task is open
        assert run("add", "w", "--role", "subagent", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "src", "ui", "a.css"), "a { b }\n")
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "scope:" not in out and pj.state()["tasks"]["w"]["touched"] == ["src/ui/a.css"], out


def test_a_brief_note_says_a_drop_only_while_it_is_news():
    """guin-site, 2026-10-06: `show --path FILE --brief` printed weeks-old drops ("dropped: task tests-support (09-24)…") 51 times
    in one session. A dropped or open task is said only while its run is open or it ended in the last 7 days, and only when no
    done task changed the file after it; otherwise the note is the last-changed line alone."""
    import datetime
    with Project() as pj, a_session():
        write(os.path.join(pj.dir, "README.md"), "# r\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "c", "--brief", "try README", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "README.md"), "# r2\n")
        assert run("drop", "c", "--why", "superseded", "--target", pj.dir)[0] == 0
        assert run("close", "--target", pj.dir)[0] == 0
        d = chongdae.run_dir(pj.dir)

        def dropped_ago(days):
            state = chongdae.load_state(d)
            state["tasks"]["c"]["dropped"]["at"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            chongdae.save_state(d, state)

        def note():
            return run("show", "--path", "README.md", "--brief", "--target", pj.dir)[1]

        dropped_ago(2)
        assert note().startswith("dropped: task c in run-") and "superseded" in note(), note()   # closed, but ended this week
        dropped_ago(30)
        assert note() == "", note()   # weeks old: nothing else on record, so nothing at all
        dropped_ago(1)
        assert run("init", "--session", "--goal", "g2", "--target", pj.dir)[0] == 0
        assert run("add", "e", "--brief", "write README", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "README.md"), "# r3\n")
        assert run("run", "--target", pj.dir)[0] == 0
        out = note()
        assert out.startswith("last changed in run-") and "task e: write README" in out and "dropped" not in out and len(out.strip().splitlines()) == 1, out


def git_commit(pj, msg="base"):
    subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg], cwd=pj.dir, check=True)


def test_tests_the_contract_deleted_are_sent_as_deleted_tests_never_demanded_and_never_recreated():
    """guin-site, 2026-10-12: the tests writer deleted four retired test files that were also in the build's --tests; `run`
    refused the build because its protected tests did not exist, and the session dropped it and added it again. A protected
    test that the task which wrote the contract's tests deleted (in its `touched`, gone from the tree) is deleted by the
    contract: said once, left out of `tests` and sent as `deleted-tests`, and a build that recreates one is refused."""
    with Project() as pj, a_session():
        write(os.path.join(pj.dir, "tests", "test_old.py"), "# retired\n")
        write(os.path.join(pj.dir, "tests", "test_keep.py"), "# kept\n")
        git_commit(pj)
        seen = os.path.join(pj.dir, "builder.py")
        write(seen, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                    "json.dump(%r, open(sys.argv[2], 'w'))\n" % RESPONSE_DONE)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": [sys.executable, seen, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "t", "--tests", "tests/test_old.py", "tests/test_keep.py", "tests/test_new.py", "--target", pj.dir)[0] == 0
        os.remove(os.path.join(pj.dir, "tests", "test_old.py"))
        write(os.path.join(pj.dir, "tests", "test_new.py"), "# new\n")
        assert run("run", "--target", pj.dir)[0] == 0
        assert "tests/test_old.py" in pj.state()["tasks"]["t"]["touched"], pj.state()["tasks"]["t"]
        code, out = run("add", "b", "--check", sys.executable + " -c pass", "--tests", "tests/test_old.py", "tests/test_keep.py", "tests/test_new.py", "--target", pj.dir)
        assert code == 0 and "tests/test_old.py deleted by the contract" in out and "t by tests/test_old.py" in out, out
        assert pj.state()["tasks"]["b"]["deleted-tests"] == {"tests/test_old.py": "t"}
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "do not exist" not in out and "deleted by the contract" not in out, out   # said once, at `add`
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "b.request.json.seen"), encoding="utf-8"))
        assert req["tests"] == ["tests/test_keep.py", "tests/test_new.py"] and req["deleted-tests"] == ["tests/test_old.py"], req
        assert not os.path.exists(os.path.join(pj.dir, "tests", "test_old.py")), "nothing recreates it"
        assert "deleted by the contract: tests/test_old.py (t deleted it)" in run("show", "--target", pj.dir)[1]
        # a session build accepts the deleted file at `add` (it would refuse any other absent test), and is refused when it recreates it
        code, out = run("add", "c", "--role", "session", "--why", "one line", "--check", sys.executable + " -c pass",
                        "--tests", "tests/test_old.py", "tests/test_keep.py", "--target", pj.dir)
        assert code == 0 and "deleted by the contract" in out, out
        assert run("add", "e", "--role", "session", "--why", "x", "--check", sys.executable + " -c pass", "--tests", "tests/nowhere.py", "--target", pj.dir)[0] != 0
        write(os.path.join(pj.dir, "tests", "test_old.py"), "# back again\n")
        write(os.path.join(pj.dir, "c.py"), "x = 1\n")
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "recreated tests the contract deleted (tests/test_old.py — t deleted them)" in out, out
        ts = pj.state()["tasks"]["c"]
        assert ts["rejected"]["by"] == "contract" and ts["rejected"]["removed"] == ["tests/test_old.py"], ts["rejected"]
        assert not os.path.exists(os.path.join(pj.dir, "tests", "test_old.py")), "the contract's deletion stands"
    with Project() as pj:   # a provider build added before the writer deleted the file: `run` says it, once, and sends it
        write(os.path.join(pj.dir, "tests", "test_old.py"), "# retired\n")
        git_commit(pj)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "t", "--role", "session", "--tests", "tests/test_old.py", "--target", pj.dir)[0] == 0
        assert run("add", "b", "--check", sys.executable + " -c pass", "--tests", "tests/test_old.py", "--target", pj.dir)[0] == 0
        os.remove(os.path.join(pj.dir, "tests", "test_old.py"))
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and out.count("deleted by the contract") == 1 and "b: note: tests/test_old.py deleted by the contract" in out, out
        assert pj.state()["tasks"]["b"]["status"] == "done"


def test_did_runs_one_operation_records_it_whatever_the_exit_and_report_lists_it():
    """guin-site, 2026-10-12: the cleanup's deploys, secret deletions and remote database changes ran as plain Bash in a todo
    task and survive only as prose in a plan file. `did TASK -- COMMAND...` runs one command (argv, no shell) and records
    {command, exit, tail, at, why, approved-in, signer} on the task whatever the exit; `show` prints it, `report` lists it —
    an observation, or an objection when it exited non-zero."""
    with Project() as pj, a_session() as agent:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("did", "ops", "--target", pj.dir, "--", sys.executable, "-c", "pass")[0] != 0, "no such task"
        assert run("add", "ops", "--brief", "deploy and delete", "--target", pj.dir)[0] == 0
        code, out = run("did", "ops", "--why", "deploy the site", "--approved-in", "source:at-63", "--target", pj.dir, "--",
                        sys.executable, "-c", "import sys; print('deployed ' + sys.argv[1])", "--why")
        assert code == 0 and "-> exit 0" in out and "deployed --why" in out and "source:at-63" in out, out   # options after `--` are the command's
        code, out = run("did", "ops", "--by", "kim", "--target", pj.dir, "--", sys.executable, "-c", "import sys; print('no such bucket'); sys.exit(3)")
        assert code == 1 and "-> exit 3" in out and "no such bucket" in out, out
        code, out = run("did", "ops", "--target", pj.dir, "--", "echo", "a", "&&", "rm", "x")
        assert code != 0 and "not a shell line" in out, out
        assert run("did", "ops", "--approved-in", "the chat", "--target", pj.dir, "--", sys.executable, "-c", "pass")[0] != 0
        assert run("did", "ops", "--target", pj.dir)[0] != 0, "no command"
        did = pj.state()["tasks"]["ops"]["did"]
        assert len(did) == 2, did
        first = dict(did[0])
        assert first.pop("at").endswith("+00:00") and first.pop("chongdae") == chongdae.engine()
        assert first == {"command": chongdae.shlex.join([sys.executable, "-c", "import sys; print('deployed ' + sys.argv[1])", "--why"]), "exit": 0,
                         "tail": ["deployed --why"], "why": "deploy the site", "approved-in": "source:at-63", "signer": agent}, first
        assert did[1]["exit"] == 3 and did[1]["signer"] == "kim" and "approved-in" not in did[1]
        log = subprocess.run(["git", "log", "--format=%s"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert "did ops:" in log, log
        out = run("show", "--target", pj.dir)[1]
        assert "did at" in out and "-> exit 0 — deploy the site; approved in source:at-63" in out and "| no such bucket" in out, out
        found = [f for f in json.loads(run("report", "--target", pj.dir)[1])["findings"] if f["kind"] == "did"]
        assert [f.get("layer") for f in found] == ["observation", None], found
        assert "no such bucket" in found[1]["text"] and "no approval cited" in found[1]["text"] and "source:at-63" in found[0]["text"], found
        assert run("drop", "ops", "--why", "x", "--target", pj.dir)[0] == 0
        assert run("did", "ops", "--target", pj.dir, "--", sys.executable, "-c", "pass")[0] != 0, "not on a dropped task"


def test_closes_without_a_contract_document_is_said_at_add_and_no_quibbler_or_verifier_gets_an_empty_contract():
    """guin-site run-20261012-052024-de21: a session run started without `--from`; `add --closes Q-cleanup` was accepted and the
    quibble was sent `contract: {}` — it answered that the contract was empty. `add` says so; `run` refuses to send a quibbler
    or verifier a request whose contract is missing a closed section, and says the fix."""
    with Project() as pj:
        quib = os.path.join(pj.dir, "quib.py")
        write(quib, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                    "json.dump({'status': 'done', 'summary': 'read it', 'findings': [], 'non-claims': []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"quibble": [sys.executable, quib, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        code, out = run("add", "q", "--role", "quibble", "--closes", "Q-cleanup", "--target", pj.dir)
        assert code == 0 and "no contract document" in out and "--from" in out, out
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "empty contract" in out and "init --session --from PLAN" in out, out
        assert not glob.glob(os.path.join(chongdae.run_dir(pj.dir), "local", "q*.request.json")), "nothing was sent"
        assert run("drop", "q", "--why", "no contract", "--target", pj.dir)[0] == 0 and run("close", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "plan", "PLAN.md"), "# p\n\n## Q-cleanup retire\n\nAcceptance: /admin is 404.\n")
        assert run("init", "--session", "--from", "plan/PLAN.md", "--goal", "g2", "--target", pj.dir)[0] == 0
        code, out = run("add", "q2", "--role", "quibble", "--closes", "Q-cleanup", "--target", pj.dir)
        assert code == 0 and "note: --closes" not in out, out
        assert run("run", "--target", pj.dir)[0] == 0
        req = json.load(open(glob.glob(os.path.join(chongdae.run_dir(pj.dir), "local", "q2*.request.json.seen"))[0], encoding="utf-8"))
        assert "/admin is 404" in req["contract"]["Q-cleanup"], req["contract"]
        # a role hired before the work reads the contract too: a section the document lacks stops it, with that fix
        code, out = run("add", "b", "--before", "quibble", "--closes", "Q-other", "--target", pj.dir)
        assert code == 0 and "has no `## Q-other` section" in out, out
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and "plan/PLAN.md has no `## Q-other` section" in out and "Add the section to plan/PLAN.md" in out, out


def test_the_session_start_line_counts_open_tasks_by_the_rule_run_uses():
    """guin-site, 2026-10-12: the SessionStart line said "2 task(s) open: cleanup-build, cleanup-ops" with cleanup-build
    dropped. One rule (`open_tasks`) for `run`, `status`, `close` and the hook."""
    with Project() as pj:
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "a", "--target", pj.dir)[0] == 0 and run("add", "b", "--target", pj.dir)[0] == 0
        assert run("drop", "a", "--why", "superseded", "--target", pj.dir)[0] == 0
        out = hook("session_start.py", {"cwd": pj.dir})[1]
        assert "1 task(s) open: b." in out, out
        assert "1 open: b" in run("status", "--target", pj.dir)[1]


def test_checked_red_records_a_tests_tasks_expected_red_and_take_says_both_flags():
    """`take` printed no hint of `--checked`, and `--checked` records only a pass: a tests task's red run had nowhere to go.
    `--checked-red COMMAND` runs it and records a non-zero exit as red as expected, a zero exit as passed before the build."""
    blocked = {"status": "blocked", "summary": "no port here", "verified": [], "decisions": [], "non-claims": []}
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        rec = chongdae.run_checked(pj.dir, [], red=[sys.executable + " -c pass"])["ran"][0]
        assert rec["exit"] == 0 and rec["expect"] == "fail" and rec["outcome"] == "passed before the build", rec
        try:
            chongdae.run_checked(pj.dir, [], red=["no-such-command-xyz"])
            assert False
        except SystemExit as e:
            assert "did not run" in str(e) and "exit 127" in str(e), e
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": pj.fake_provider(blocked)}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "t", "--tests", "test_a.py", "--target", pj.dir)[0] == 0
        assert run("add", "u", "--tests", "test_b.py", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == chongdae.DECISION
        code, out = run("take", "t", "--why", "the sandbox had no port", "--target", pj.dir)
        assert code == 0 and "--checked \"COMMAND\"" in out and "--checked-red" in out, out
        write(os.path.join(pj.dir, "test_b.py"), "raise SystemExit(1)\n")
        code, out = run("take", "u", "--why", "the sandbox had no port", "--checked-red", sys.executable + " test_b.py", "--target", pj.dir)
        assert code == 0 and "exit 1 — red as expected" in out and "evidence chongdae saw:" not in out, out
        ck = pj.state()["tasks"]["u"]["checked"]["ran"][0]
        assert ck["exit"] == 1 and ck["outcome"] == "red as expected" and ck["expect"] == "fail", ck
        assert "checked by chongdae at" in run("show", "--target", pj.dir)[1]
        assert "--checked-red" in run("take", "--help")[1]


def test_run_waits_well_under_a_hosts_ten_minute_tool_limit_by_default():
    """guin-site, 2026-10-12: `run` blocked ~8 minutes on a provider against a 10-minute tool limit, and the session wrapped it
    in polling loops. The default budget is four minutes; CHONGDAE_WAIT still overrides it."""
    env = {k: v for k, v in os.environ.items() if k != "CHONGDAE_WAIT"}
    said = lambda e: subprocess.run([sys.executable, "-c", "import chongdae; print(chongdae.WAIT_BUDGET)"], cwd=HERE, env=e,
                                    capture_output=True, text=True).stdout.strip()
    assert said(env) == "240", said(env)
    assert said(dict(env, CHONGDAE_WAIT="17")) == "17"



# ---------------------------------------------------------------- many machines on one plan: leases, the remote, parents (1.20.0)

@contextlib.contextmanager
def isolated_git(home):
    """git with no global or system config, and an identity from the environment: these tests never read or write the
    machine's own git config."""
    keep = dict(os.environ)
    write(os.path.join(home, "gitconfig"), "")
    os.environ.update(GIT_CONFIG_GLOBAL=os.path.join(home, "gitconfig"), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                      GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for k in ("CHONGDAE_MACHINE", "CHONGDAE_SESSION", "CHONGDAE_USER"):
        os.environ.pop(k, None)
    real_clock = chongdae.clock
    try:
        yield
    finally:
        chongdae.clock = real_clock
        os.environ.clear()
        os.environ.update(keep)


def g(cwd, *a, check=True):
    done = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if check and done.returncode:
        raise AssertionError("git %s: %s" % (" ".join(a), done.stderr))
    return done.stdout.strip()


class Machines:
    """Two clones of one local bare repository: machine A and machine B on one plan. `settings` goes into the committed
    hunsu.json (settings.chongdae)."""

    def __init__(self, settings, tasks=None):
        self.top = tempfile.mkdtemp(prefix="chongdae-machines-")
        self.cm = isolated_git(self.top)
        self.cm.__enter__()
        self.remote = os.path.join(self.top, "remote.git")
        g(self.top, "init", "-q", "--bare", "-b", "main", self.remote)
        self.a, self.b = os.path.join(self.top, "a"), os.path.join(self.top, "b")
        g(self.top, "clone", "-q", self.remote, self.a)
        g(self.a, "checkout", "-q", "-b", "main")
        write(os.path.join(self.a, "hunsu.json"), {"settings": {"chongdae": settings}})
        g(self.a, "add", "hunsu.json")
        g(self.a, "commit", "-qm", "base")
        g(self.a, "push", "-q", "origin", "main")
        g(self.top, "clone", "-q", self.remote, self.b)
        self.offset = [0.0]
        chongdae.clock = lambda: time.time() + self.offset[0]
        self.plan = os.path.join(self.top, "plan.json")
        write(self.plan, {"artifact-type": "chongdae/plan@1", "goal": "three pieces", "providers": {"implementer": "session"},
                          "tasks": tasks or [{"id": t, "role": "implementer", "gate": "human", "needs": [], "checks": [[sys.executable, "-c", "pass"]]}
                                             for t in ("T1", "T2", "T3")]})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.cm.__exit__(*a)
        shutil.rmtree(self.top, ignore_errors=True)

    def on(self, who, *argv, session="s1"):
        """A chongdae command on machine A or B (a session of it)."""
        os.environ["CHONGDAE_MACHINE"], os.environ["CHONGDAE_SESSION"] = who, session
        return run(*argv, "--target", self.a if who == "A" else self.b)

    def state(self, who):
        return chongdae.load_state(chongdae.run_dir(self.a if who == "A" else self.b))

    def refs(self):
        return g(self.top, "--git-dir", self.remote, "for-each-ref", "--format=%(refname)", "refs/chongdae/")

    def start(self):
        """Machine A starts the plan run and the remote has it; machine B pulls it."""
        assert self.on("A", "init", "--plan", self.plan)[0] == 0
        g(self.a, "push", "-q", "origin", "main")
        g(self.b, "pull", "-q", "origin", "main")
        return os.path.basename(chongdae.run_dir(self.a))


def test_c1_two_machines_claim_one_task_one_holds_it_the_other_is_told_who_and_takes_the_next_ready():
    with Machines({"lease": "git"}) as m:
        run_id = m.start()
        # at the same moment: two processes, one per clone — the remote takes exactly one create
        procs = []
        for who, tree in (("A", m.a), ("B", m.b)):
            env = dict(os.environ, CHONGDAE_MACHINE=who, CHONGDAE_SESSION="s1")
            procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "chongdae.py"), "claim", "T1", "--target", tree], env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        outs = [(p.wait(), p.stdout.read()) for p in procs]
        winners = [i for i, (code, _) in enumerate(outs) if code == 0]
        assert len(winners) == 1, outs
        loser = "B" if winners == [0] else "A"
        code, out = outs[1 - winners[0]]
        assert code == 1 and "held by %s/s1 (gen 1" % ("A" if loser == "B" else "B") in out and "ready and unheld: T2, T3" in out, out
        assert m.refs() == "refs/chongdae/claims/%s/T1" % run_id, m.refs()
        # the loser's run passes over the held task and takes the next ready one
        code, out = m.on(loser, "run")
        assert code == chongdae.DECISION and "T1 is held by" in out and "claimed T2 (gen 1)" in out and "human: review task T2" in out, out
        assert m.state(loser)["tasks"]["T2"]["gen"] == 1 and "T1" in m.state(loser)["tasks"] and m.state(loser)["tasks"]["T1"]["status"] == "todo"
        # one hold per session: the loser cannot also take T3 while it holds T2
        code, out = m.on(loser, "claim", "T3")
        assert code != 0 and "holds %s/T2 already" % run_id in out, out
        code, out = m.on(loser, "claim", "--list")
        assert code == 0 and "%s/T1" % run_id in out and "%s/T2" % run_id in out and "gen 1" in out, out


def test_c2_a_lapsed_hold_is_taken_over_and_the_record_says_so():
    with Machines({"lease": "git", "lease-ttl": 60}) as m:
        m.start()
        assert m.on("A", "claim", "T1")[0] == 0
        m.offset[0] = 61   # A's session died: no progress for longer than the ttl
        code, out = m.on("B", "claim", "--list")
        assert "[lapsed]" in out, out
        code, out = m.on("B", "claim", "T1")
        assert code == 0 and "claimed by B/s1 (gen 2)" in out and "taken over from a lapsed hold of A/s1 (gen 1" in out, out
        code, out = m.on("B", "run")
        assert code == chongdae.DECISION and "human: review task T1" in out, out
        assert m.on("B", "confirm", "T1", "--by", "kim")[0] == 0
        ts = m.state("B")["tasks"]["T1"]
        assert ts["status"] == "done" and ts["gen"] == 2 and ts["lease"]["from"]["lapsed"] is True and ts["lease"]["from"]["holder"]["machine"] == "A", ts
        rec = chongdae.load(os.path.join(chongdae.run_dir(m.b), "tasks", "T1.json"))
        assert "lease-held" not in rec and rec["lease"]["gen"] == 2, rec   # the record carries the generation; what this machine holds stays local


def test_c3_a_break_is_a_judgment_with_its_reason_and_the_old_holder_is_refused_at_its_next_renewal():
    with Machines({"lease": "git"}) as m:
        run_id = m.start()
        assert m.on("A", "claim", "T1")[0] == 0
        assert m.on("A", "run")[0] == chongdae.DECISION   # A works on T1: produced, waiting at its gate
        assert m.on("B", "claim", "--break", "T1")[0] != 0, "a break needs a reason"
        code, out = m.on("B", "claim", "--break", "T1", "--why", "A's laptop is in a bag for the week")
        assert code == 0 and "broke A/s1's hold on T1 (gen 1 -> 2)" in out and "next renewal" in out, out
        brk = m.state("B")["tasks"]["T1"]["lease-breaks"][0]
        assert brk["why"] == "A's laptop is in a bag for the week" and brk["from"]["machine"] == "A" and brk["gen"] == 1 and brk["to-gen"] == 2, brk
        assert "break the hold on T1" in g(m.b, "log", "-1", "--format=%s"), "a break is a judgment: committed"
        write(os.path.join(m.a, "more.py"), "x = 1\n")   # A goes on working
        code, out = m.on("A", "run")
        assert code == chongdae.DECISION and "this session's hold (gen 1) was taken — B/s1 holds it now (gen 2) and broke it: A's laptop is in a bag for the week" in out, out
        assert "%s/T1" % run_id in m.refs()


def test_c4_without_a_lease_setting_claims_are_the_records_as_before():
    with Machines({}) as m:
        m.start()
        assert m.on("A", "claim", "T1", "--by", "bob")[0] == 0
        assert m.state("A")["tasks"]["T1"]["claimed_by"] == "bob"
        code, out = m.on("A", "claim", "--list")
        assert code == 0 and "T1  claimed by bob" in out and "no lease setting" in out, out
        code, out = m.on("A", "claim", "--break", "T1", "--why", "x")
        assert code != 0 and "needs a lease" in out, out
        code, out = m.on("A", "run")
        assert "T1 is claimed by bob" in out, out
        assert m.refs() == "" and not os.path.exists(os.path.join(m.a, ".git", "chongdae-claims")), "no lease store is touched"
        assert g(m.top, "--git-dir", m.remote, "rev-parse", "main") == g(m.a, "rev-parse", "origin/main"), "nothing pushed without a remote setting"


def test_c5_claims_and_releases_leave_no_commit_on_main_and_no_ref_behind():
    with Machines({"lease": "git", "remote": "sync"}) as m:
        run_id = m.start()
        assert m.on("A", "claim", "T1")[0] == 0 and m.on("B", "claim", "T2")[0] == 0
        assert m.on("A", "run")[0] == chongdae.DECISION and m.on("B", "run")[0] == chongdae.DECISION
        assert sorted(m.refs().split("\n")) == ["refs/chongdae/claims/%s/T1" % run_id, "refs/chongdae/claims/%s/T2" % run_id], m.refs()
        assert m.on("A", "confirm", "T1", "--by", "kim")[0] == 0
        assert m.on("B", "claim", "T2", "--release")[0] == 0
        assert m.on("A", "claim", "--list")[1].startswith("no hold"), "released: nobody holds anything"
        markers = [json.loads(g(m.top, "--git-dir", m.remote, "log", "-1", "--format=%B", r)) for r in m.refs().split("\n")]
        assert sorted((x["key"].split("/")[-1], x["gen"], bool(x.get("released"))) for x in markers) == [("T1", 1, True), ("T2", 1, True)], markers
        m.offset[0] = chongdae.LEASE_CEILING + 1
        code, out = m.on("A", "claim", "--list", "--prune")
        assert code == 0 and "pruned 2 released marker(s)" in out, out
        assert m.refs() == "", "pruned: the refs are gone"
        log = g(m.top, "--git-dir", m.remote, "log", "--format=%s", "main")
        assert log and "confirm T1" in log and "claim" not in log.lower(), log   # the judgments travelled; no claim did
        assert g(m.top, "--git-dir", m.remote, "for-each-ref", "--format=%(refname)", "refs/heads") == "refs/heads/main"


def test_c7_a_hold_lapses_without_progress_and_progress_past_the_ceiling_is_long_held():
    with Machines({"lease": "git", "lease-ttl": 60, "lease-ceiling": 300}) as m:
        m.start()
        assert m.on("A", "claim", "T1")[0] == 0
        assert m.on("A", "run")[0] == chongdae.DECISION
        m.offset[0] = 50
        assert m.on("A", "run")[0] == chongdae.DECISION   # waiting at the gate, nothing moved: not progress
        m.offset[0] = 70
        code, out = m.on("A", "claim", "--list")
        assert "[lapsed]" in out, out   # renewed by progress, never by time alone
        assert m.on("B", "claim", "T1")[0] == 0, "a lapsed hold is anyone's"
        assert m.on("A", "claim", "T2", session="s2")[0] == 0
        for step in range(1, 8):   # progress every 50 s: the tree moves, `run` sees it
            m.offset[0] = 70 + 50 * step
            write(os.path.join(m.a, "work.py"), "x = %d\n" % step)
            m.on("A", "run", session="s2")
        code, out = m.on("A", "claim", "--list")
        line = next(l for l in out.split("\n") if "/T2" in l)
        assert "long-held" in line and "lapsed" not in line, out


def test_c8_a_result_made_under_an_old_generation_is_refused_and_the_old_holder_stops():
    with Machines({"lease": "git", "lease-ttl": 60}) as m:
        m.start()
        assert m.on("A", "claim", "T1")[0] == 0
        assert m.on("A", "run")[0] == chongdae.DECISION   # the laptop produced T1 under gen 1, then slept
        assert m.state("A")["tasks"]["T1"]["gen"] == 1
        m.offset[0] = 4000
        assert m.on("B", "claim", "T1")[0] == 0
        code, out = m.on("A", "confirm", "T1", "--by", "kim")
        assert code != 0 and "made under gen 1" in out and "B/s1 holds the task at gen 2" in out, out
        write(os.path.join(m.a, "awake.py"), "x = 1\n")
        code, out = m.on("A", "run")
        assert code == chongdae.DECISION and "(gen 1) was taken — B/s1 holds it now (gen 2) and took it after it lapsed" in out and "stays in this tree" in out, out
        assert m.state("A")["tasks"]["T1"]["status"] == "produced", "nothing recorded done under the old generation"


def test_c9_overlapping_scopes_are_not_held_at_once():
    tasks = [{"id": "T1", "role": "implementer", "gate": "human", "scope": ["src"], "checks": [[sys.executable, "-c", "pass"]]},
             {"id": "T2", "role": "implementer", "gate": "human", "scope": ["src/a"], "checks": [[sys.executable, "-c", "pass"]]},
             {"id": "T3", "role": "implementer", "gate": "human", "scope": ["docs"], "checks": [[sys.executable, "-c", "pass"]]}]
    with Machines({"lease": "local"}, tasks=tasks) as m:   # two sessions on one machine: the local backend
        assert m.on("A", "init", "--plan", m.plan)[0] == 0
        assert m.on("A", "claim", "T1", session="s1")[0] == 0
        code, out = m.on("A", "claim", "T2", session="s2")
        assert code == 1 and "its scope overlaps src, held by A/s1" in out, out
        assert m.on("A", "claim", "T3", session="s2")[0] == 0
        code, out = m.on("A", "claim", "--list")
        assert "scope src (" in out and "scope docs (" in out and "scope src/a" not in out, out   # the refused take gave every key back
        store = os.path.join(m.a, ".git", "chongdae-claims")
        files = [json.load(open(os.path.join(store, f))) for f in os.listdir(store) if f.endswith(".json")]
        assert sum(1 for f in files if not f.get("released")) == 4 and sorted(f["key"] for f in files if f.get("released")) == sorted(["scope/src%2Fa", "%s/T2" % os.path.basename(chongdae.run_dir(m.a))]), files   # the refused take's keys: given back, gens kept
        assert m.on("A", "claim", "T1", "--release", session="s1")[0] == 0
        assert m.on("A", "claim", "T3", "--release", session="s2")[0] == 0
        assert m.on("A", "claim", "T2", session="s2")[0] == 0, "free once the overlapping scope is given back"


def test_under_a_lease_one_run_takes_finishes_and_gives_back_one_task_at_a_time():
    with Machines({"lease": "local"}) as m:
        assert m.on("A", "init", "--session", "--goal", "g")[0] == 0
        assert m.on("A", "add", "T1", "--brief", "x")[0] == 0 and m.on("A", "add", "T2", "--brief", "y")[0] == 0
        write(os.path.join(m.a, "a.py"), "x = 1\n")
        code, out = m.on("A", "run")
        assert code == chongdae.DECISION and "claimed T1 (gen 1)" in out and "done T1" in out and "claimed T2 (gen 1)" in out, out   # T1 given back, so T2 could be taken
        write(os.path.join(m.a, "b.py"), "x = 2\n")
        code, out = m.on("A", "run")
        assert code == 0 and "done T2" in out and "claimed" not in out, out
        st = m.state("A")
        assert st["tasks"]["T1"]["gen"] == 1 and st["tasks"]["T2"]["lease"]["holder"]["machine"] == "A", st["tasks"]["T2"]
        assert m.on("A", "claim", "--list")[1].startswith("no hold"), "done gives every hold back"


def test_sync_pushes_each_judgment_and_goes_on_when_the_push_fails():
    with Machines({"remote": "sync"}) as m:
        assert m.on("A", "init", "--session", "--goal", "g")[0] == 0
        assert g(m.top, "--git-dir", m.remote, "rev-parse", "main") == g(m.a, "rev-parse", "HEAD"), "the judgment was pushed"
        hook_path = os.path.join(m.remote, "hooks", "pre-receive")
        write(hook_path, "#!/bin/sh\necho closed for the night >&2\nexit 1\n")
        os.chmod(hook_path, 0o755)
        assert m.on("A", "add", "T1", "--brief", "x")[0] == 0
        code, out = m.on("A", "drop", "T1", "--why", "superseded")
        assert code == 0 and "record not pushed to origin/main" in out and "the next judgment pushes again" in out, out
        os.remove(hook_path)
        assert m.on("A", "add", "T2", "--brief", "y")[0] == 0
        assert m.on("A", "drop", "T2", "--why", "superseded too")[0] == 0
        assert g(m.top, "--git-dir", m.remote, "rev-parse", "main") == g(m.a, "rev-parse", "HEAD"), "retried: everything behind went"


def test_shared_fetches_before_a_step_and_stops_when_the_push_is_refused():
    with Machines({"remote": "shared"}) as m:
        assert m.on("A", "init", "--session", "--goal", "g")[0] == 0
        assert m.on("A", "add", "T1", "--brief", "x")[0] == 0
        assert m.on("A", "drop", "T1", "--why", "superseded")[0] == 0
        assert g(m.b, "rev-parse", "HEAD") != g(m.a, "rev-parse", "HEAD")
        code, out = m.on("B", "run")   # a step under shared: fetch and take what the remote has first
        assert g(m.b, "rev-parse", "HEAD") == g(m.a, "rev-parse", "HEAD") and "session run" in out, out
        # B judges while A moved on: B's push is refused, fetch + reconcile + push again goes through
        assert m.on("B", "add", "T3", "--brief", "w")[0] == 0
        assert m.on("A", "add", "T2", "--brief", "y")[0] == 0 and m.on("A", "drop", "T2", "--why", "z")[0] == 0
        code, out = m.on("B", "drop", "T3", "--why", "not needed")
        assert code == 0 and "fetched, reconciled and pushed" in out, out
        assert g(m.top, "--git-dir", m.remote, "rev-parse", "main") == g(m.b, "rev-parse", "HEAD")
        hook_path = os.path.join(m.remote, "hooks", "pre-receive")
        write(hook_path, "#!/bin/sh\nexit 1\n")
        os.chmod(hook_path, 0o755)
        code, out = m.on("B", "add", "T4", "--brief", "v")   # naming a task is a judgment that travels too
        assert code == chongdae.DECISION and "decision: the record is committed here, but origin/main did not take it" in out and "fetch, reconcile" in out, out


def test_under_shared_a_task_travels_when_it_is_named():
    """On GitHub with two clones, `add` left the task uncommitted and the other machine said "no task T1". Under `sync` or
    `shared`, `add` commits and pushes the task; under `shared` it fetches first."""
    with Machines({"remote": "shared", "lease": "git"}) as m:
        assert m.on("A", "init", "--session", "--goal", "g")[0] == 0
        assert m.on("A", "add", "T1", "--brief", "x")[0] == 0
        assert g(m.top, "--git-dir", m.remote, "rev-parse", "main") == g(m.a, "rev-parse", "HEAD"), "the new task was pushed"
        code, out = m.on("B", "claim", "T1")
        assert code == 0 and "T1 claimed by B" in out, out
        assert m.on("B", "add", "T2", "--brief", "y")[0] == 0, "B fetched A's record before naming its own task"
        code, out = m.on("A", "claim", "T2")
        assert code == 0 and "T2 claimed by A" in out, out
    with Machines({}) as m:
        assert m.on("A", "init", "--session", "--goal", "g")[0] == 0
        head = g(m.a, "rev-parse", "HEAD")
        assert m.on("A", "add", "T1", "--brief", "x")[0] == 0
        assert g(m.a, "rev-parse", "HEAD") == head, "no remote setting: add commits nothing, as before"


def test_a_child_run_names_its_parent_and_the_parent_shows_its_children():
    with Machines({"lease": "local"}) as m:
        parent = m.start()
        assert m.on("A", "init", "--parent", "nope/T1")[0] != 0
        code, out = m.on("A", "init", "--session", "--goal", "do T1", "--worktree", "--parent", "%s/T1" % parent)
        assert code == 0 and "child of %s / task T1 (held at gen 1)" % parent in out, out
        wt = out.split("--target ")[-1].strip()
        child = os.path.basename(chongdae.run_dir(wt))
        assert chongdae.load_state(chongdae.run_dir(wt))["parent"] == {"run": parent, "task": "T1", "gen": 1}
        os.environ["CHONGDAE_MACHINE"] = "A"
        code, out = run("show", "--target", wt)
        assert "parent: %s / task T1 (held at gen 1)" % parent in out, out
        assert run("add", "c1", "--brief", "piece", "--target", wt)[0] == 0
        code, out = m.on("A", "show", "--run", parent)
        assert "child %s — task T1: running (1 todo) [worktree %s]" % (child, child) in out, out
        assert "child" not in chongdae.load(os.path.join(m.a, ".chongdae", parent, "state.json")), "the parent's state holds nothing of its children"
        # someone else breaks the parent task's hold: the child does not land
        assert m.on("A", "claim", "--break", "T1", "--why", "reassigned", session="s9")[0] == 0
        code, out = run("close", "--target", wt)
        assert code != 0 and "not closed:" in out and "held by A/s9 at gen 2" in out, out


def test_a_service_backend_speaks_the_argv_contract():
    backend = SERVICE_BACKEND
    with Machines({}) as m:
        write(os.path.join(m.top, "svc.py"), backend)
        write(os.path.join(m.a, "hunsu.local.json"), {"settings": {"chongdae": {"lease": [sys.executable, os.path.join(m.top, "svc.py")]}}})
        assert m.on("A", "init", "--plan", m.plan)[0] == 0
        code, out = m.on("A", "claim", "T1")
        assert code == 0 and "claimed by A/s1 (gen 1)" in out, out
        code, out = m.on("A", "claim", "T1", session="s2")
        assert code == 1 and "held by A/s1 (gen 1" in out, out
        code, out = m.on("A", "claim", "--list")
        assert "T1  A/s1  gen 1" in out, out
        assert m.on("A", "run")[0] == chongdae.DECISION
        assert m.on("A", "confirm", "T1", "--by", "kim")[0] == 0
        kept = chongdae.load(os.path.join(m.top, "leases.json"))
        assert [(v["gen"], bool(v.get("released"))) for v in kept.values()] == [(1, True)], kept   # done gives the hold back; the gen stays
        assert m.on("A", "claim", "--list")[1].startswith("no hold")
        write(os.path.join(m.top, "svc.py"), "import sys; sys.exit(3)\n")
        code, out = m.on("A", "claim", "T2")
        assert code == chongdae.DECISION and "cannot be reached" in out and "nothing was started untaken" in out, out


SERVICE_BACKEND = r'''
import json, sys, os
db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leases.json")
data = json.load(open(db)) if os.path.exists(db) else {}
op, a = sys.argv[1], sys.argv[2:]
key = a[0] if a else ""
opt = dict(zip(a[1::2], a[2::2]))
cur = data.get(key)
out = {}
if op == "take":
    h = json.loads(opt["--holder"])
    free = cur is None or cur.get("released")
    same = not free and cur["holder"]["machine"] == h["machine"] and cur["holder"]["session"] == h["session"]
    if free or same or ("--over" in opt and str(cur["gen"]) == opt["--over"]):
        gen = max(int(opt["--gen"]), (cur or {}).get("gen", 0) + 1) if not same else cur["gen"]
        new = {"key": key, "holder": h, "gen": gen, "taken": "2026-10-13T00:00:00+00:00", "renewed": "2026-10-13T00:00:00+00:00",
               "last-progress": "2026-10-13T00:00:00+00:00", "ttl": int(opt["--ttl"])}
        new.update({k: opt["--" + k] for k in ("task", "scope") if "--" + k in opt})
        if "--over" in opt:
            new["from"] = {"holder": cur["holder"], "gen": cur["gen"], "broken": opt.get("--why", "")}
        data[key] = new
        out = {"ok": True, "lease": new}
    else:
        out = {"ok": False, "lease": cur}
elif op == "renew":
    out = {"ok": bool(cur and str(cur["gen"]) == opt["--gen"]), "lease": cur}
elif op == "release":
    ok = bool(cur and not cur.get("released") and str(cur["gen"]) == opt["--gen"])
    if ok:
        data[key] = {"key": key, "released": "2026-10-13T00:00:00+00:00", "gen": cur["gen"], "by": opt.get("--by", "")}
    out = {"ok": ok, "lease": None}
elif op == "list":
    out = {"leases": [v for k, v in sorted(data.items()) if k.startswith(key)]}
elif op == "prune":
    gone = [k for k, v in data.items() if k.startswith(key) and v.get("released")]
    for k in gone:
        del data[k]
    out = {"pruned": gone}
json.dump(data, open(db, "w"))
print(json.dumps(out))
'''
def test_a_release_keeps_the_generation_so_a_machine_that_never_saw_the_record_still_counts_on():
    with Machines({"lease": "git"}) as m:
        m.start()
        assert m.on("A", "claim", "T1")[0] == 0
        code, out = m.on("A", "claim", "T1", "--release")
        assert code == 0 and "released (gen 1)" in out, out
        assert "gen" not in m.state("B")["tasks"]["T1"], "B has not fetched anything of A's hold"
        code, out = m.on("B", "claim", "T1")
        assert code == 0 and "claimed by B/s1 (gen 2)" in out, out


def lease_record_after(m, who="A"):
    """One scenario on one backend: take T1, work it to its gate, confirm it. The task's record, as committed."""
    assert m.on(who, "init", "--plan", m.plan)[0] == 0
    assert m.on(who, "claim", "T1")[0] == 0
    assert m.on(who, "run")[0] == chongdae.DECISION
    assert m.on(who, "confirm", "T1", "--by", "kim")[0] == 0
    return chongdae.load(os.path.join(chongdae.run_dir(m.a), "tasks", "T1.json"))


def test_c6_changing_the_backend_changes_no_record():
    shape = lambda rec: (sorted(k for k in rec if k not in ("start", "touched")), sorted(rec["lease"]), sorted(rec["lease"]["holder"]),
                         rec["gen"], rec["lease"]["gen"], rec["lease"]["holder"]["machine"])
    with Machines({"lease": "local"}) as m:
        local = lease_record_after(m)
    with Machines({}) as m:
        write(os.path.join(m.top, "svc.py"), SERVICE_BACKEND)
        write(os.path.join(m.a, "hunsu.local.json"), {"settings": {"chongdae": {"lease": [sys.executable, os.path.join(m.top, "svc.py")]}}})
        service = lease_record_after(m)
    assert shape(local) == shape(service), (shape(local), shape(service))
    assert sorted(local["lease"]["holder"]) == ["agent", "machine"], local["lease"]   # a holder is a holder on every backend; the host's session id stays in local/



def test_a_verifier_finding_whose_quote_is_not_where_it_says_is_overruled_and_the_work_is_not_resent():
    """guin-site run-20261015-054352-a0ec: chongdae ran cache-build's suite green, then sent the verifier a request that said
    nothing of it; the verifier rejected the build, quoting "`built.non-claims` says: `I did not run the whole suite.`" — a
    sentence only the tests writer's tests_non_claims held — and the build was resent. chongdae's own check runs go to the
    verifier as `checked`; a finding whose quote is not in the field it names, or that calls unverified a check chongdae saw
    pass, is overruled — said and recorded — and the slice goes on as accepted. A finding that stands is printed whole when
    the work goes back."""
    request = {"built": {"summary": "the full check passes", "verified": [{"check": "python3 tests/run.py --all", "exit": 0}],
                         "non-claims": ["I didn't run the TypeScript type-check"]},
               "tests_non_claims": {"cache-tests": ["a", "b", "I did not run the whole suite."]}, "contract": {"Q-cache": "## Q-cache\n\nkeys carry the `version` id."},
               "checked": [{"command": "python3 tests/run.py --all", "exit": 0, "tail": ["ok"], "changed_since": []}], "target": "."}
    said = {"kind": "claim-unverified", "where": "built.verified[0] and built.non-claims",
            "record_quote": "`built.verified` claims `python3 tests/run.py --all` exited 0, while `built.non-claims` says: `I did not run the whole suite.`",
            "tree_quote": "x", "why": "the report contradicts itself"}
    why = chongdae.unfounded(dict(said, kind="record-vs-tree"), request)
    assert why and "I did not run the whole suite." in why and "tests_non_claims.cache-tests[2]" in why and "tests writer" in why, why
    why = chongdae.unfounded(said, request)
    assert why and "chongdae itself ran it" in why and "python3 tests/run.py --all" in why, why
    ran_later = dict(request, checked=[dict(request["checked"][0], changed_since=["src/a.ts"])])
    assert "tests_non_claims" in chongdae.unfounded(said, ran_later), "changed since it ran: the run is no ground — the quote still is"
    grounded = {"kind": "plan-vs-code", "where": "contract.Q-cache", "record_quote": "keys carry the `version` id.", "tree_quote": "k", "why": "w"}
    assert chongdae.unfounded(grounded, request) is None
    assert chongdae.unfounded({"kind": "claim-unverified", "where": "built.verified[0]", "record_quote": "`python3 tests/run.py --all` decides `keys carry the`",
                               "tree_quote": "t", "why": "w"}, request) is None, "a claim-unverified quoting the contract sentence the check may not decide stands"
    assert chongdae.unfounded({"kind": "plan-vs-code", "where": "src/read.ts:12", "record_quote": "anything", "tree_quote": "t", "why": "w"}, request) is None
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        writer = os.path.join(pj.dir, "writer.py")
        write(writer, "import json, os, sys\nreq = json.load(open(sys.argv[1]))\nopen(os.path.join(req['target'], 'test_a.py'), 'w').write('# t\\n')\n"
                      "json.dump({'status': 'done', 'summary': 'w', 'non-claims': ['I did not run the whole suite.']}, open(sys.argv[2], 'w'))\n")
        check = sys.executable + " -c 'print(\"all groups passed\")'"
        built = {"status": "done", "summary": "built; the full check passes", "verified": [{"check": check, "exit": 0}], "decisions": [], "non-claims": ["no type-check"]}
        finding = {"kind": "claim-unverified", "where": "built.verified[0] and built.non-claims", "tree_quote": "tests/run.py", "why": "contradicts itself",
                   "record_quote": "`built.non-claims` says: `I did not run the whole suite.`"}
        eyes = os.path.join(pj.dir, "eyes.py")
        write(eyes, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                    "json.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'reject', 'findings': [%r]}, open(sys.argv[2], 'w'))\n" % finding)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"nitpick": [sys.executable, writer, "{request}", "{response}"],
                                                                  "implementer": pj.fake_provider(built), "verifier": [sys.executable, eyes, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "tests", "--role", "nitpick", "--tests", "test_a.py", "--target", pj.dir)[0] == 0
        assert run("add", "build", "--role", "implementer", "--tests", "test_a.py", "--check", check, "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "unfounded, overruled" in out and "going on as accepted" in out and "sent back" not in out, out
        req = json.load(open(glob.glob(os.path.join(chongdae.run_dir(pj.dir), "local", "build.verify*request*.seen"))[0]))
        own = [c for c in req["checked"] if c["source"].startswith("the task's checks")]
        assert own and own[0]["command"] == chongdae.shlex.join(chongdae.shlex.split(check)) and own[0]["exit"] == 0 and own[0]["tail"] == ["all groups passed"] \
            and own[0]["changed_since"] == [] and own[0]["at"], req["checked"]
        ts = pj.state()["tasks"]["build"]
        assert ts["status"] == "done" and not ts.get("attempts") and "rejected" not in ts, ts
        assert ts["overruled"]["findings"][0]["finding"] == finding and "tests_non_claims.tests[0]" in ts["overruled"]["findings"][0]["why"], ts["overruled"]
        assert any("chongdae overruled the verifier's claim-unverified finding" in n for n in ts["non-claims"]), ts["non-claims"]
        assert chongdae.verdict_of(ts) == "accept"
        shown = run("show", "--target", pj.dir)[1]
        assert "every one overruled — went on as accepted" in shown and "overruled by chongdae: its record quote" in shown, shown
    with Project() as pj:   # a finding that stands goes back to the hands, and what goes back is said whole
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        write(os.path.join(pj.dir, "PLAN.md"), "# p\n\n## Q1 count\n\nids of the remaining memos do not change.\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": pj.fake_provider(RESPONSE_DONE), "verifier": pj.fake_provider(REVIEW_REJECT, "verifier")}})
        assert run("init", "--session", "--goal", "g", "--from", "PLAN.md", "--target", pj.dir)[0] == 0
        assert run("add", "b", "--role", "implementer", "--closes", "Q1", "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        said = out[:out.index("sent back to the provider automatically")]
        assert "the verifier rejected the slice:" in said and "plan-vs-code @ plan Q10 vs memo.py:clear: clear resets the counter" in said \
            and "record: “ids of the remaining memos do not change”" in said, out


def test_the_calls_budget_covers_chongdaes_own_checks_and_the_next_call_resumes_from_the_stage_it_stopped_at():
    """guin-site, 10-15: one `run` call took 8m35s — accept, chongdae's own suite (~4.5 min), the verifier (~1 min), a resend and
    240 s more — against the host's 10-minute tool limit; the budget counted only provider waits. The checks now run as a
    tracked process of their own inside the call's budget: past it the call hands back (`still working:`, exit WAITING),
    the next call waits for the same run, and checks that passed on this tree are not run again when a later call resumes
    at the verifier."""
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        outside = tempfile.mkdtemp(prefix="chongdae-count-")
        count = os.path.join(outside, "ran")
        write(os.path.join(pj.dir, "check.py"), "import sys, time\nopen(sys.argv[1], 'a').write('x')\ntime.sleep(float(sys.argv[2]))\nprint('suite ok')\n")
        subprocess.run(["git", "add", "check.py"], cwd=pj.dir)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "check"], cwd=pj.dir)
        slow_eyes = os.path.join(outside, "eyes.py")
        write(slow_eyes, "import json, sys, time\ntime.sleep(3)\njson.dump({'artifact-type': 'dwitbuk/review@1', 'verdict': 'accept', 'findings': []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"verifier": [sys.executable, slow_eyes, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "T1", "--role", "session", "--why", "small", "--check", "%s check.py %s 3" % (sys.executable, count), "--target", pj.dir)[0] == 0
        old = chongdae.WAIT_BUDGET; chongdae.WAIT_BUDGET = 1
        try:
            t0 = time.time(); code, out = run("run", "--target", pj.dir); dt = time.time() - t0
            assert code == chongdae.WAITING and out.startswith("still working: T1 (its checks): chongdae's own run of its checks is still going") and dt < 2.5, (out, dt)
            d = chongdae.run_dir(pj.dir)
            assert os.path.exists(os.path.join(d, "local", "T1.checks.pending.json"))
            # the next call waits for the same run — never a second one — then the verifier, which outlasts the budget
            t0 = time.time(); code, out = run("run", "--target", pj.dir); dt = time.time() - t0
            assert code == chongdae.WAITING and "T1 (verify): the provider is still working" in out and dt < 4.5, (out, dt)
            assert io.open(count).read() == "x", "the checks ran once"
            ts = pj.state()["tasks"]["T1"]
            assert ts["checks-passed"]["ran"][0]["tail"] == ["suite ok"] and "checks-tree" not in chongdae.load(os.path.join(d, "tasks", "T1.json")), ts
            chongdae.WAIT_BUDGET = 30
            code, out = run("run", "--target", pj.dir)   # resumes at the verifier: the checks passed on this very tree
            assert code == 0 and pj.state()["tasks"]["T1"]["status"] == "done" and io.open(count).read() == "x", (out, io.open(count).read())
        finally:
            chongdae.WAIT_BUDGET = old
            shutil.rmtree(outside, ignore_errors=True)
    with Project() as pj:   # the process's exit code itself: still working is not a stop and not a finish
        slow = os.path.join(pj.dir, "slow.py")
        write(slow, "import json, sys, time\ntime.sleep(3)\njson.dump(%r, open(sys.argv[2], 'w'))\n" % RESPONSE_DONE)
        plan = {"artifact-type": "chongdae/plan@1", "goal": "g", "providers": {"builder": [sys.executable, slow, "{request}", "{response}"]},
                "tasks": [{"id": "T1", "role": "builder", "checks": [[sys.executable, "-c", "pass"]]}]}
        write(os.path.join(pj.dir, "plan.json"), plan)
        assert run("init", "--plan", "plan.json", "--target", pj.dir)[0] == 0
        done = subprocess.run([sys.executable, os.path.join(HERE, "chongdae.py"), "run", "--target", pj.dir], capture_output=True, text=True,
                              env=dict(os.environ, CHONGDAE_WAIT="1"))
        assert done.returncode == chongdae.WAITING == 4 and done.stdout.startswith("still working: "), (done.returncode, done.stdout)
        assert chongdae.WAITING not in (0, chongdae.DECISION, chongdae.DISPATCH)
        time.sleep(3)


def test_a_quibble_task_is_sent_a_review_shaped_request_not_its_own_empty_checks():
    """guin-site run-20261015-054352-a0ec: cache-quibble, a task of its own with role quibble, was sent `stage: build` and its
    own `checks: []`; 4 of its 8 findings were "unchecked: checks가 []라서…" — about the request. A contract reader's task
    is sent its role as the stage, no checks of its own, and the planned builds' checks labelled as planned (or that none is
    named yet)."""
    with Project() as pj:
        write(os.path.join(pj.dir, "plan", "PLAN.md"), "# p\n\n## Q-a\n\nthe count is printed.\n")
        sibi = os.path.join(pj.dir, "sibi.py")
        write(sibi, "import json, shutil, sys\nshutil.copy(sys.argv[1], sys.argv[1] + '.seen')\n"
                    "json.dump({'status': 'done', 'summary': 's', 'findings': [], 'non-claims': []}, open(sys.argv[2], 'w'))\n")
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"quibble": [sys.executable, sibi, "{request}", "{response}"]}})
        assert run("init", "--session", "--goal", "g", "--from", "plan/PLAN.md", "--target", pj.dir)[0] == 0
        assert run("add", "q1", "--role", "quibble", "--closes", "Q-a", "--brief", "read the contract", "--target", pj.dir)[0] == 0
        assert run("run", "--target", pj.dir)[0] == 0
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "q1.request.json.seen")))
        assert req["stage"] == "quibble" and req["role"] == "quibble" and "checks" not in req and "tests" not in req, req
        assert req["checks-are"].startswith("not named yet") and req["contract"]["Q-a"].startswith("## Q-a"), req
        assert run("add", "b", "--role", "session", "--why", "the test", "--closes", "Q-a", "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0
        assert run("add", "q2", "--role", "quibble", "--closes", "Q-a", "--target", pj.dir)[0] == 0
        run("run", "--target", pj.dir)
        req = json.load(open(os.path.join(chongdae.run_dir(pj.dir), "local", "q2.request.json.seen")))
        assert req["stage"] == "quibble" and req["checks"] == [[sys.executable, "-c", "pass"]] and req["checks-are"].startswith("planned: the checks of b"), req


def test_a_record_file_is_written_only_when_what_it_says_changed():
    """guin-site d281c8a: a `did` on one task rewrote all seven task files, and six done or dropped tasks nobody had judged
    again read `written_by` 1.19.0 -> 1.20.0 — false provenance and noise in the notary commit."""
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "old", "--brief", "b", "--target", pj.dir)[0] == 0
        assert run("drop", "old", "--why", "superseded", "--target", pj.dir)[0] == 0
        assert run("add", "ops", "--brief", "b", "--target", pj.dir)[0] == 0
        d = chongdae.run_dir(pj.dir)
        f = os.path.join(d, "tasks", "old.json")
        rec = chongdae.load(f); rec["written_by"] = "chongdae 1.19.0"; write(f, rec)
        subprocess.run(["git", "add", "-A", "--", ".chongdae"], cwd=pj.dir)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "as an older version wrote it"], cwd=pj.dir)
        assert run("did", "ops", "--target", pj.dir, "--", sys.executable, "-c", "pass")[0] == 0
        assert chongdae.load(f)["written_by"] == "chongdae 1.19.0", "an unchanged record keeps the version that wrote it"
        names = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.split()
        assert [n for n in names if "/tasks/" in n] == [os.path.relpath(os.path.join(d, "tasks", "ops.json"), pj.dir)], names
        assert chongdae.load(os.path.join(d, "tasks", "ops.json"))["written_by"] == chongdae.engine()


def test_did_keeps_a_script_outside_the_project_a_sensible_subject_a_meaningful_tail_and_a_batch_as_one_judgment():
    """guin-site run-20261012-052255-3556: `did cleanup-ops -- python3 /private/tmp/…/scratchpad/empty_r2.py` was recorded with only
    the machine path (the script is gone), its commit subject cut at 120 characters mid-name ("…/scratchpad/empty"), the
    deletions' tails kept "⛅️ wrangler 4.143.1 (update available 4.149.0)" and rules of ─, and R2's emptying and deletion — one
    decision — were separate commits. The record now keeps the script (sha256, its text when small) behind a marker, the
    subject keeps the head and the name, the tail drops banners and rules, and `--each FILE` records several as one."""
    assert chongdae.short_command("python3 " + "/x" * 80 + "/empty_r2.py", 60).endswith("… empty_r2.py") and len(chongdae.short_command("a " * 200, 60)) <= 60
    assert chongdae.kept_tail("⛅️ wrangler 4.143.1 (update available 4.149.0)\n" + "─" * 40 + "\n\nDeleted bucket guin\n" + "═" * 10) == ["Deleted bucket guin"]
    with Project() as pj, a_session():
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        scratch = tempfile.mkdtemp(prefix="chongdae-scratch-")
        script = os.path.join(scratch, "a" * 30, "b" * 30, "empty_r2.py")
        body = "print('⛅️ wrangler 4.143.1 (update available 4.149.0)')\nprint('─' * 30)\nprint('before: 41 objects')\nprint('deleted 41; after: 0 objects')\nprint('─' * 30)\n"
        write(script, body)
        try:
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "ops", "--brief", "retire R2", "--target", pj.dir)[0] == 0
            code, out = run("did", "ops", "--why", "empty the bucket", "--target", pj.dir, "--", sys.executable, script)
            assert code == 0 and "the program it ran (empty_r2.py) is outside the project: sha256" in out and "its content kept in the record" in out, out
            rec = pj.state()["tasks"]["ops"]["did"][0]
            assert rec["command"] == chongdae.shlex.join([sys.executable, "<outside:empty_r2.py>"]) and scratch not in json.dumps(rec), rec
            import hashlib
            o = rec["outside"][0]
            assert o["arg"] == 1 and o["sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest() and o["content"] == body and o["size"] == len(body.encode("utf-8")), o
            assert rec["tail"] == ["before: 41 objects", "deleted 41; after: 0 objects"], rec["tail"]
            subject = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=pj.dir, capture_output=True, text=True).stdout
            assert "'<outside:empty_r2.py>' -> exit 0" in subject, subject
            f = [x for x in json.loads(run("report", "--target", pj.dir)[1])["findings"] if x["kind"] == "did"][0]
            assert "the program it ran (empty_r2.py) is outside the project: sha256" in f["text"], f
            assert "(empty_r2.py) is outside the project" in run("show", "--target", pj.dir)[1]
            # several operations, one judgment: one commit, each its own exit and tail; a failure stops the rest
            each = os.path.join(scratch, "ops.txt")
            write(each, "# R2, then D1\n%s -c \"print('emptied')\"\n\n%s -c \"import sys; print('no such db'); sys.exit(2)\"\n%s -c \"print('never')\"\n"
                  % (sys.executable, sys.executable, sys.executable))
            before = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()
            code, out = run("did", "ops", "--each", each, "--why", "retire the old stores", "--target", pj.dir)
            assert code == 1 and "| emptied" in out and "| no such db" in out and "not run (an earlier command exited non-zero)" in out and "never" not in out.split("not run")[0], out
            after = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()
            assert int(after) == int(before) + 1, (before, after)
            did = pj.state()["tasks"]["ops"]["did"]
            assert [(r["exit"], r["batch"]) for r in did[1:]] == [(0, {"of": 3, "n": 1}), (2, {"of": 3, "n": 2})], did
            subject = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=pj.dir, capture_output=True, text=True).stdout
            assert subject.startswith(os.path.basename(chongdae.run_dir(pj.dir)) + ": did ops: 2 operation(s) (stopped at 2 of 3)"), subject
            assert run("did", "ops", "--each", each, "--target", pj.dir, "--", "echo")[0] != 0, "a command or a file, not both"
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def test_did_keeps_the_program_not_its_data_and_nothing_that_looks_like_secrets():
    """guin-site 10-16: `did lexicon-publish -- node <scratch>/publish_lexicons.mjs ./lexicons/… <the PDS's .dev.vars> --write`
    kept every outside file's text, so the data argument — a secrets file — went into `did[0].outside[1].content` and was
    committed; the report said "it ran a file outside the project, .dev.vars". Only the program run keeps its text; an argument
    keeps its sha256 and size; a secret-looking name or text keeps nothing, the program included; a secret-looking value in the
    command line or the tail is masked; the report tells the program from an argument. And f3beee0's subject ended
    `'<outsi… --write -> exit 0`: the subject is cut at argument boundaries."""
    import hashlib
    assert chongdae.program_arg(".", ["node", "x.mjs", "a.json"]) == 1 and chongdae.program_arg(".", ["npx", "tsx", "x.ts"]) == 2
    assert chongdae.program_arg(".", ["python3", "-u", "x.py", "d"]) == 2 and chongdae.program_arg(".", ["python3", "-c", "print(1)", "x.py"]) is None
    assert chongdae.program_arg(".", ["wrangler", "deploy", "x.js"]) is None
    for name in (".env", ".env.local", ".dev.vars", "server.pem", "my.key", "id_rsa", "id_ed25519.pub", "api_token.txt", "db-password", "Credentials.json"):
        assert chongdae.looks_secret_name(name), name
    for name in ("publish.mjs", "data.json", "lexicon.json", "README.md"):
        assert not chongdae.looks_secret_name(name), name
    fake_gh = "ghp_" + "A1b2C3d4" * 4
    assert chongdae.looks_secret_text("PDS_ADMIN_PASSWORD=hunter2hunter2\n") and chongdae.looks_secret_text("x = '%s'" % fake_gh)
    assert chongdae.looks_secret_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n")
    assert not chongdae.looks_secret_text("const KEY = process.env.API_KEY\nconsole.log('ok')\n")
    masked, n = chongdae.mask_secrets("ok\nAPI_TOKEN=abcdef123456 done\nkey sk-%s\n" % ("x" * 30))
    assert n == 2 and "API_TOKEN=<masked> done" in masked and "abcdef123456" not in masked and "sk-x" not in masked, masked
    assert chongdae.mask_argv(["curl", "--token", "abcdefgh1234", "SECRET_KEY=zzzzzzzz9", "-v"]) == (["curl", "--token", "<masked>", "SECRET_KEY=<masked>", "-v"], 2)
    # the subject: never inside a marker or a quoted argument
    cmd = chongdae.shlex.join(["node", "<outside:publish_lexicons.mjs>"] + ["./lexicons/app/guin/%s.json" % ("n" * 12 + str(i)) for i in range(6)] + ["<outside:.dev.vars>", "--write"])
    sub = chongdae.short_command(cmd)
    assert len(sub) <= 100 and sub.startswith("node '<outside:publish_lexicons.mjs>' ") and sub.endswith(" … --write"), sub
    assert all(w == "…" or w in chongdae.shlex.split(cmd) or w.startswith("'<outside:") and w in cmd for w in sub.split(" ")), sub
    assert "'<outsi…" not in sub and sub.count("'") % 2 == 0, sub
    assert chongdae.short_join(["a" * 40] * 5, 100) == "; ".join(["a" * 40] * 2) + " (and 3 more)"
    with Project() as pj, a_session():
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        scratch = tempfile.mkdtemp(prefix="chongdae-scratch-")
        try:
            prog = os.path.join(scratch, "publish.py")
            write(prog, "import sys\nprint('published', len(sys.argv) - 1, 'file(s)')\nprint('SESSION_TOKEN' + '=' + 'tok_' + 'abcdef0123456789')\n")
            data = os.path.join(scratch, "lexicon.json")
            write(data, '{"id": "app.guin.post"}\n')
            vars_ = os.path.join(scratch, "pds", ".dev.vars")
            write(vars_, "PDS_JWT_SECRET=0123456789abcdef0123456789abcdef\nPDS_PORT=2583\n")
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
            assert run("add", "publish", "--brief", "publish the lexicons", "--target", pj.dir)[0] == 0
            code, out = run("did", "publish", "--why", "publish", "--target", pj.dir, "--", sys.executable, prog, data, vars_, "--write")
            assert code == 0, out
            rec = pj.state()["tasks"]["publish"]["did"][0]
            p, d, v = rec["outside"]
            assert (p["role"], p["content"]) == ("program", io.open(prog, encoding="utf-8").read()), p
            assert d["role"] == "argument" and "content" not in d and d["not-kept"] == "an argument, not the program", d
            assert d["sha256"] == hashlib.sha256(open(data, "rb").read()).hexdigest() and d["size"] == os.path.getsize(data), d
            assert v["role"] == "argument" and "content" not in v and v["not-kept"] == "looks like secrets" and v["name"] == ".dev.vars", v
            # the tail: the value masked, the name kept, said
            assert "SESSION_TOKEN=<masked>" in rec["tail"] and rec["masked"] == {"tail": 1}, rec
            committed = subprocess.run(["git", "log", "-p", "-1"], cwd=pj.dir, capture_output=True, text=True).stdout
            assert "0123456789abcdef0123456789abcdef" not in committed and "tok_abcdef0123456789" not in committed, "a secret reached the commit"
            assert "the program it ran (publish.py) is outside the project" in out and "a file it was given as an argument (.dev.vars) is outside the project" in out, out
            assert "content not kept: looks like secrets" in out and "masked in the record (looked like secrets): 1 value(s) in the output's end" in out, out
            f = [x for x in json.loads(run("report", "--target", pj.dir)[1])["findings"] if x["kind"] == "did"][0]
            assert "the program it ran (publish.py)" in f["text"] and "a file it was given as an argument (.dev.vars)" in f["text"] and "it ran a file" not in f["text"], f
            # a program whose own text looks like secrets keeps no content either
            leaky = os.path.join(scratch, "deploy.py")
            write(leaky, "API_KEY = 'AKIA" + "ABCDEFGHIJKLMNOP" + "'\nprint('ok')\n")
            assert run("did", "publish", "--target", pj.dir, "--", sys.executable, leaky)[0] == 0
            o = pj.state()["tasks"]["publish"]["did"][1]["outside"][0]
            assert o["role"] == "program" and "content" not in o and o["not-kept"] == "looks like secrets", o
            # a secret on the command line is masked in the record and the subject
            assert run("did", "publish", "--target", pj.dir, "--", sys.executable, "-c", "print('ok')", "API_SECRET=s3cr3tvalue99")[0] == 0
            r3 = pj.state()["tasks"]["publish"]["did"][2]
            assert "API_SECRET=<masked>" in r3["command"] and "s3cr3tvalue99" not in json.dumps(r3) and r3["masked"] == {"command": 1}, r3
            log = subprocess.run(["git", "log", "-p", "-3"], cwd=pj.dir, capture_output=True, text=True).stdout
            assert "s3cr3tvalue99" not in log and "ABCDEFGHIJKLMNOP" not in log, "a secret reached the history"
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def test_done_is_committed_when_it_is_made():
    """guin-site run-20261015-054352-a0ec: five tasks became done in `run` calls that committed nothing; their results landed
    in a commit titled "accept decisions on cache-build (delegated)", 12 files. Done is a judgment, notarized when made."""
    with Project() as pj:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "contract", "--brief", "write the contract", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "PLAN.md"), "# p\n")
        assert run("run", "--target", pj.dir)[0] == 0
        log = subprocess.run(["git", "log", "-1", "--format=%s", "--name-only"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert log.startswith(os.path.basename(chongdae.run_dir(pj.dir)) + ": done contract — write the contract") and "tasks/contract.json" in log, log
        assert not subprocess.run(["git", "status", "--porcelain", "--", ".chongdae"], cwd=pj.dir, capture_output=True, text=True).stdout.strip()


def test_close_stops_on_uncommitted_work_and_on_what_the_reviewer_finds_the_tree_can_answer():
    """guin-site run-20261012-052255-3556 closed with plan/ATPROTO.md — in cleanup-ops' scope and `touched` — edited and not
    committed; and the reviewer, run as the close was final, reported two cq-failed the tree could answer: they arrived after
    the run was closed and were fixed outside any run. `close` now says the uncommitted work and stops; it runs the reviewer
    before it is final, and an open objection the tree can answer stops it for the session (not a person's question), the
    review written for it taken back; `--anyway --why` closes with them standing, recorded. Counted as the reviewer counts."""
    assert chongdae.review_count([{"kind": "cq-failed", "where": "a"}, {"kind": "non-claim"}, {"kind": "undisposed", "carries": ["non-claim", "r", "t"]}, {"kind": "cq-failed", "where": "b"}]) \
        == "cq-failed 2, non-claim 2; 1 of them carried, already in the count"   # dwitbuk's count_text, word for word
    # two copies of one charge are one thing owed — a carry and the charge it carries, or one charge raised twice (its bearing struck)
    assert chongdae.review_count([{"kind": "non-claim", "where": "r", "text": "t"}, {"kind": "undisposed", "carries": ["non-claim", "r", "t"]},
                                  {"kind": "non-claim", "where": "s", "text": "u [tasks a, b]"}, {"kind": "non-claim", "where": "s", "text": "u [tasks a]"}]) == "non-claim 2"
    assert chongdae.review_count([]) == "none"
    with Project() as pj:
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=pj.dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "plan", "ATPROTO.md"), "# a\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        reviewer = os.path.join(pj.dir, "reviewer.py")
        write(reviewer, "import json, os, sys\nos.makedirs('reviews', exist_ok=True)\nfs = json.load(open('findings.json')) if os.path.exists('findings.json') else []\n"
                        "json.dump({'artifact-type': 'dwitbuk/review@1', 'findings': fs}, open('reviews/review-1.json', 'w'))\nprint('review-1: %d finding(s)' % len(fs))\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "reviewer"], cwd=pj.dir, check=True)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"reviewer": [sys.executable, reviewer]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "ops", "--brief", "the ops, then Done in ATPROTO.md", "--scope", "plan/ATPROTO.md", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "plan", "ATPROTO.md"), "# a\n\nDone: the ops.\n")
        assert run("run", "--target", pj.dir)[0] == 0
        code, out = run("close", "--target", pj.dir)
        assert code == chongdae.DECISION and "decision: session agent: this run's work is not committed — plan/ATPROTO.md (ops)" in out \
            and "git add -- plan/ATPROTO.md" in out and "close --anyway --why" in out, out
        assert pj.state()["status"] == "running"
        subprocess.run(["git", "add", "plan/ATPROTO.md"], cwd=pj.dir, check=True)
        subprocess.run(["git", "commit", "-qm", "the ops' Done"], cwd=pj.dir, check=True)
        # the reviewer finds what the tree can answer: the close stops for the session, the run stays open, the review is taken back
        found = [{"kind": "cq-failed", "where": "records-kept", "text": "record-table lost a projection", "layer": "objection"},
                 {"kind": "non-claim", "where": "run-x", "text": "no check decides this task", "layer": "objection"},
                 {"kind": "undisposed", "where": "run-y", "text": "no check decides this task", "carries": ["non-claim", "run-y", "no check"], "layer": "objection"},
                 {"kind": "cq-failed", "where": "post-fields", "text": "answered before", "layer": "objection", "disposition": {"as": "accepted"}}]
        write(os.path.join(pj.dir, "findings.json"), found)
        code, out = run("close", "--target", pj.dir)
        assert code == chongdae.DECISION and "decision: session agent: the reviewer found 1 objection(s) this tree can answer (cq-failed 1)" in out \
            and "cq-failed @ records-kept: record-table lost a projection" in out and "human:" not in out and "non-claim @" not in out, out
        st = pj.state()
        assert st["status"] == "running" and "ended" not in st and "reviewed" not in st, st
        assert not os.path.exists(os.path.join(pj.dir, "reviews", "review-1.json")), "a review for a close that did not happen is not the next one's base"
        # closed anyway: recorded, said
        code, out = run("close", "--anyway", "--target", pj.dir)
        assert code != 0 and "needs --why" in out, out
        code, out = run("close", "--anyway", "--why", "the owner reads the cq at the next session", "--target", pj.dir)
        assert code == 0 and "closed" in out, out
        st = pj.state()
        assert st["status"] == "complete" and st["closed-anyway"]["standing"] == [{"kind": "cq-failed", "where": "records-kept", "text": "record-table lost a projection"}], st.get("closed-anyway")
        assert any("1 reviewer objection(s) the tree could answer (cq-failed 1)" in n for n in st["non-claims"]), st["non-claims"]
        shown = subprocess.run(["git", "show", "--name-only", "--format=%s", "HEAD"], cwd=pj.dir, capture_output=True, text=True).stdout
        assert ": close — g" in shown and "reviews/review-1.json" in shown, shown
    with Project() as pj:   # nothing the tree can answer: close goes through as before
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=pj.dir)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"reviewer": [sys.executable, "-c", "import json, os; os.makedirs('reviews', exist_ok=True); "
                                                                                 "json.dump({'findings': [{'kind': 'non-claim', 'where': 'r', 'text': 't', 'layer': 'objection'}]}, open('reviews/r.json', 'w'))"]}})
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("close", "--target", pj.dir)[0] == 0 and pj.state()["status"] == "complete"

def _git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def test_a_run_for_one_task_does_not_finish_another_with_nothing_of_its_own():
    """guin-site run-20261015-054352-a0ec: the `run` for cache-comment also made cache-ops done (06:36:15, touched [], no
    did) — its deploy, push and Done line happened 06:37–06:39. A session task with no check, no change of its own and no
    `did` stays open; the pass goes on; the call says how to finish it. Named, or with a `did`, it is done."""
    with Project() as pj:
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "ops", "--brief", "npm run deploy와 push — 결과를 ATPROTO.md에 Done으로", "--scope", "plan/ATPROTO.md", "--target", pj.dir)[0] == 0
        assert run("add", "comment", "--brief", "read.ts comments", "--scope", "read.ts", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "read.ts"), "// a snapshot per deployed version\n")
        code, out = run("run", "--target", pj.dir)
        st = pj.state()
        assert code == chongdae.DECISION and "done comment" in out and st["tasks"]["comment"]["status"] == "done", out
        assert st["tasks"]["ops"]["status"] == "todo" and "done ops" not in out, out
        assert "ops has changed nothing of its own and has no `did` record" in out and "chongdae run ops" in out and "chongdae did ops" in out, out
        # the commit form for the session's own commit of a task's work is printed with the done
        assert "git commit -m '%s/comment (session): read.ts comments' -- read.ts" % os.path.basename(chongdae.run_dir(pj.dir)) in out, out
        # a `run` naming another task does not finish it either
        code, out = run("run", "comment", "--target", pj.dir)
        assert code == chongdae.DECISION and pj.state()["tasks"]["ops"]["status"] == "todo", out
        code, out = run("run", "nosuch", "--target", pj.dir)
        assert code != 0 and "no task nosuch" in out, out
        # its work done now, as a `did` and its Done line: the next `run` makes it done
        assert run("did", "ops", "--why", "the deploy", "--target", pj.dir, "--", sys.executable, "-c", "print('deployed')")[0] == 0
        write(os.path.join(pj.dir, "plan", "ATPROTO.md"), "Done: deployed\n")
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "done ops" in out and pj.state()["tasks"]["ops"]["touched"] == ["plan/ATPROTO.md"], out
    with Project() as pj:   # naming it is the session's word: done, and said as a non-claim
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "decide", "--brief", "decide the cache key", "--target", pj.dir)[0] == 0
        code, out = run("run", "--target", pj.dir)
        assert code == chongdae.DECISION and pj.state()["tasks"]["decide"]["status"] == "todo", out
        code, out = run("run", "decide", "--target", pj.dir)
        ts = pj.state()["tasks"]["decide"]
        assert code == 0 and "done decide" in out and ts["status"] == "done", out
        assert any("done on the session's word by name (`run decide`)" in n for n in ts["non-claims"]), ts["non-claims"]
    with Project() as pj:   # a `did` recorded on it: done by a plain `run`
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "ops", "--brief", "deploy", "--target", pj.dir)[0] == 0
        code, out = run("did", "ops", "--why", "the deploy", "--target", pj.dir, "--", sys.executable, "-c", "print('deployed')")
        assert code == 0, out
        code, out = run("run", "--target", pj.dir)
        assert code == 0 and "done ops" in out, out


def test_close_and_report_name_an_operation_with_no_did_and_a_bash_operation_gets_a_did_nudge():
    """guin-site run-20261015-054352-a0ec: cache-ops' deploy and push ran as `npm run deploy … | grep …; git push 2>&1 |
    tail -1` (both exits lost), the push written as prose in ATPROTO.md; nothing in the record says what ran."""
    with Project() as pj:
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "ops", "--brief", "npm run preview → 소유자 확인 → 배포와 push", "--target", pj.dir)[0] == 0
        assert run("add", "comment", "--brief", "주석을 배포 버전마다로 맞춘다", "--target", pj.dir)[0] == 0   # a modifier, not an operation
        assert run("run", "ops", "comment", "--target", pj.dir)[0] == 0
        code, out = run("close", "--target", pj.dir)
        assert code == chongdae.DECISION and "ops reads as an operation outside the repository and has no `did` record" in out \
            and "chongdae did ops" in out and "comment:" not in out, out
        assert pj.state()["status"] == "running"
        code, out = run("report", "--target", pj.dir)
        found = [f for f in json.loads(out)["findings"] if f["kind"] == "operation-unrecorded"]
        assert [f["where"].split("/")[-1] for f in found] == ["ops"] and found[0]["layer"] == "observation", found
        code, out = run("close", "--anyway", "--why", "the preview only; the owner deploys later", "--target", pj.dir)
        st = pj.state()
        assert code == 0 and st["closed-anyway"]["operations-unrecorded"] == ["ops"], (out, st.get("closed-anyway"))
        assert any("task(s) reading as an operation with no `did` (ops)" in n for n in st["non-claims"]), st["non-claims"]
    assert chongdae.reads_as_operation({"brief": "the deployed version in the key"}) is None
    assert chongdae.reads_as_operation({"brief": "delete the old D1"}) == "delete"
    assert chongdae.reads_as_operation({"brief": "deploy", "checks": [["true"]]}) is None, "a build its checks decide is not an operation"
    assert chongdae.reads_as_operation({"brief": "배포한 템플릿은 다음 요청부터"}) is None and chongdae.reads_as_operation({"brief": "R2 삭제"}) == "삭제"
    with Project() as pj:   # the Bash hook: a line of context while a run is running, never a refusal
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        payload = lambda c: {"cwd": pj.dir, "tool_name": "Bash", "tool_input": {"command": c}}
        assert hook("pre_bash.py", payload("git push origin main")) == (0, ""), "no run: silent"
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        assert run("add", "ops", "--brief", "b", "--target", pj.dir)[0] == 0
        code, out = hook("pre_bash.py", payload("npm run deploy 2>&1 | grep -E 'Version'; git push 2>&1 | tail -1"))
        said = json.loads(out)["hookSpecificOutput"]
        assert code == 0 and said["hookEventName"] == "PreToolUse" and "permissionDecision" not in said, out
        assert "record it:" in said["additionalContext"] and "did TASK" in said["additionalContext"] and "ops" in said["additionalContext"], out
        assert hook("pre_bash.py", payload("git status && ls")) == (0, "")
        assert hook("pre_bash.py", payload('python3 "/x/chongdae.py" did ops --why w -- git push')) == (0, ""), "did itself is the record"
        assert hook("pre_bash.py", payload("git push"), AGENT_WORKER="1") == (0, ""), "a worker session: silent"
        write(os.path.join(pj.dir, "hunsu.json"), {"settings": {"chongdae": {"ops-patterns": [r"\bmake\s+release\b"]}}})
        assert hook("pre_bash.py", payload("git push")) == (0, "") and "make release" in hook("pre_bash.py", payload("make release"))[1]
        hooks = json.load(open(os.path.join(HERE, "hooks", "hooks.json"), encoding="utf-8"))["hooks"]["PreToolUse"]
        assert any(h["matcher"] == "Bash" and "pre_bash.py" in h["hooks"][0]["command"] for h in hooks), hooks


def test_the_session_start_and_close_say_unpushed_commits_and_no_upstream():
    """guin-site 10-15: 213 commits sat unpushed for 10 days and main had no upstream; with settings.chongdae.remote absent
    nothing read ahead or behind. Read from the local remote-tracking refs only — no fetch."""
    with Project() as pj:
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        branch = _git(pj.dir, "symbolic-ref", "--short", "HEAD").stdout.strip()
        assert chongdae.upstream_line(pj.dir) is None, "no remote at all: nothing to say"
        bare = tempfile.mkdtemp(prefix="chongdae-remote-")
        try:
            subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
            _git(pj.dir, "remote", "add", "origin", bare)
            assert chongdae.upstream_line(pj.dir) == "%s: no upstream" % branch
            code, out = hook("session_start.py", {"cwd": pj.dir})
            assert "%s: no upstream." % branch in json.loads(out)["hookSpecificOutput"]["additionalContext"], out
            assert _git(pj.dir, "push", "-q", "-u", "origin", branch).returncode == 0
            assert chongdae.upstream_line(pj.dir) is None, "level: silent"
            assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0   # a record commit, not pushed (remote absent)
            code, out = run("close", "--target", pj.dir)
            assert code == 0 and "%s: 2 commits not on origin/%s (as of the last fetch)" % (branch, branch) in out, out
            code, out = hook("session_start.py", {"cwd": pj.dir})
            assert "commits not on origin/%s" % branch in json.loads(out)["hookSpecificOutput"]["additionalContext"], out
        finally:
            shutil.rmtree(bare, ignore_errors=True)


def test_close_prints_the_commit_of_each_tasks_work_in_the_sessions_own_form():
    """guin-site 10-15: with no form given, the agent's own work commits copied the engine's `run-<id>:` (737db95, bf90cdf) or
    made up `run:` (33b5bda): engine and agent commits read alike in `git log`. The session's form is
    `run-<id>/<task> (session): …`; the printed commands commit exactly that task's files."""
    with Project() as pj:
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        write(os.path.join(pj.dir, "other.txt"), "someone else's\n")
        _git(pj.dir, "add", "other.txt")   # staged by someone else before the task: the printed commit leaves it out
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        rid = os.path.basename(chongdae.run_dir(pj.dir))
        assert run("add", "docs", "--brief", "the README says it", "--target", pj.dir)[0] == 0
        write(os.path.join(pj.dir, "README.md"), "# it\n")
        assert run("run", "docs", "--target", pj.dir)[0] == 0
        code, out = run("close", "--target", pj.dir)
        lines = [l.strip() for l in out.splitlines()]
        assert code == chongdae.DECISION and "git add -- README.md" in lines, out
        commit = [l for l in lines if l.startswith("git commit")]
        assert commit == ["git commit -m '%s/docs (session): the README says it' -- README.md" % rid], commit
        assert "`%s/<task> (session): …`" % rid in out, out
        assert _git(pj.dir, "add", "--", "README.md").returncode == 0
        import shlex
        assert _git(pj.dir, *shlex.split(commit[0])[1:]).returncode == 0
        assert _git(pj.dir, "log", "-1", "--format=%s").stdout.strip() == "%s/docs (session): the README says it" % rid
        assert "other.txt" in _git(pj.dir, "diff", "--cached", "--name-only").stdout, "only the task's files were committed"
        _git(pj.dir, "commit", "-qm", "other")
        code, out = run("close", "--target", pj.dir)
        assert code == 0, out


def test_a_resent_builds_verifier_is_told_the_builders_files_and_what_the_eyes_did_not_read_is_said():
    """guin-site run-20261015-054352-a0ec: after the resend the builder found its first attempt's work in the tree and changed
    nothing more; the second verify request said `touched: []`, the builder's index.ts and read.ts under `touched_since`
    ("changed after the builder answered"). And dwitbuk 1.14.0's eyes say in the verdict's `non-claims` when they accepted
    without reading the tree — stored by chongdae, read by nobody: printed, kept on the task, an observation in `report`."""
    with Project() as pj:
        _git(pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        outside = tempfile.mkdtemp(prefix="chongdae-calls-")
        try:
            builder = os.path.join(pj.dir, "builder.py")
            write(builder, "import json, os, sys\nif not os.path.exists('a.py'):\n    open('a.py', 'w').write('x = 1\\n')\n"
                           "json.dump(%r, open(sys.argv[2], 'w'))\n" % (RESPONSE_DONE,))
            accept = dict(REVIEW_ACCEPT, **{"non-claims": ["accepted without reading the tree: the eyes opened no file and ran no command — the verdict rests on the packet alone"]})
            verifier = os.path.join(pj.dir, "eyes.py")
            write(verifier, "import json, os, sys\nn = os.path.join(%r, 'n')\nfirst = not os.path.exists(n)\nopen(n, 'a').write('x')\n"
                            "json.dump(%r if first else %r, open(sys.argv[2], 'w'))\n" % (outside, REVIEW_REJECT, accept))
            _git(pj.dir, "add", "-A")
            _git(pj.dir, "commit", "-qm", "the providers")
            write(os.path.join(pj.dir, "PLAN.md"), "# p\n\n## Q1 count\n\nids of the remaining memos do not change.\n")
            write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": [sys.executable, builder, "{request}", "{response}"],
                                                                      "verifier": [sys.executable, verifier, "{request}", "{response}"]}})
            assert run("init", "--session", "--goal", "g", "--from", "PLAN.md", "--target", pj.dir)[0] == 0
            assert run("add", "b", "--role", "implementer", "--closes", "Q1", "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0
            code, out = run("run", "--target", pj.dir)
            assert "sent back to the provider automatically" in out, out
            reqs = sorted(glob.glob(os.path.join(chongdae.run_dir(pj.dir), "local", "b.verify*request*")), key=os.path.getmtime)
            assert len(reqs) == 2, reqs
            second = json.load(open(reqs[-1], encoding="utf-8"))
            assert second["touched"] == ["a.py"] and "a.py" not in second.get("touched_since", []), (second["touched"], second.get("touched_since"))
            assert "b: the verifier's non-claim: accepted without reading the tree" in out, out
            ts = pj.state()["tasks"]["b"]
            assert ts["status"] == "done" and any(n.startswith("(verifier) accepted without reading the tree") for n in ts["non-claims"]), ts.get("non-claims")
            doc = json.loads(run("report", "--target", pj.dir)[1])
            said = [f for f in doc["findings"] if f["kind"] == "verifier-non-claim"]
            assert len(said) == 1 and said[0]["layer"] == "observation" and "accepted without reading the tree" in said[0]["text"], said
            assert not [f for f in doc["findings"] if f["kind"] == "non-claim" and "(verifier)" in f["text"]], doc["findings"]
        finally:
            shutil.rmtree(outside, ignore_errors=True)


def test_the_hands_read_names_a_hired_provider_out_now_or_answered_since_and_never_the_session():
    """guin-site 10-15 05:53:57: jokbo told the session's own hired builder's edits (cache-build, run-20261015-054352-a0ec) as
    another hand's. `show --after ISO --hands PATH...` (jokbo's `hands` read) prints one JSON object, path -> whose: a hired
    provider out now (its pending pid alive, the file not what it was at its start) or an attempt answered at or after --after
    (the path in its `touched_by_provider`/`touched`). A session task's file is not named; a bad --after is `{}`, exit 0."""
    import datetime
    with Project() as pj, a_session():
        for f in ("a.py", "b.py", "s.py", "old.py", "z.py"):
            write(os.path.join(pj.dir, f), "# %s\n" % f)
        write(os.path.join(pj.dir, "hunsu.lock.json"), {"roles": {"implementer": [sys.executable, "-c", "pass", "{request}", "{response}"]}})
        git_commit(pj)
        assert run("init", "--session", "--goal", "g", "--target", pj.dir)[0] == 0
        for tid in ("build", "fix", "prior"):
            assert run("add", tid, "--role", "implementer", "--brief", tid, "--check", sys.executable + " -c pass", "--target", pj.dir)[0] == 0, tid
        assert run("add", "own", "--brief", "the session's", "--target", pj.dir)[0] == 0
        d = chongdae.run_dir(pj.dir)
        rid = os.path.basename(d)
        utc = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        now = datetime.datetime.now(datetime.timezone.utc)
        after = utc(now - datetime.timedelta(minutes=5))
        state = chongdae.load_state(d)
        hired = {"provider": "command", "argv": ["x"]}
        state["tasks"]["fix"].update({"answered": {"at": now.isoformat()}, "performed_by": hired, "touched_by_provider": ["b.py"]})
        state["tasks"]["prior"].update({"answered": {"at": (now - datetime.timedelta(hours=1)).isoformat()}, "performed_by": hired, "touched_by_provider": ["old.py"]})
        state["tasks"]["own"].update({"answered": {"at": now.isoformat()}, "performed_by": {"provider": "session", "host": "claude-code"}, "touched": ["s.py"]})
        chongdae.save_state(d, state)
        for f in ("b.py", "s.py", "old.py", "z.py"):
            write(os.path.join(pj.dir, f), "# changed\n")
        # in flight: build's provider is out now (this process's pid: alive), started on the tree as it is; a.py changed since
        write(os.path.join(d, "local", "build.pending.json"), {"pid": os.getpid(), "argv": ["x"], "start": chongdae.dirty(pj.dir)})
        write(os.path.join(pj.dir, "a.py"), "# the builder's\n")

        def hands(at, *paths):
            code, out = run("show", "--target", pj.dir, "--after", at, "--hands", *paths)
            assert code == 0, out
            return json.loads(out)

        said = hands(after, "a.py", "b.py", "s.py", "old.py", "z.py")
        assert said == {"a.py": "the implementer of build (%s)" % rid, "b.py": "the implementer of fix (%s)" % rid}, said
        assert hands(utc(now + datetime.timedelta(hours=1)), "b.py") == {}   # answered before --after: not this window's
        assert hands("not-a-time", "a.py", "b.py") == {}
        assert hands(after) == {}
        # the provider gone: not out now, so a.py is nobody's this record knows
        write(os.path.join(d, "local", "build.pending.json"), {"pid": 2 ** 22 + 12345, "start": {}})
        assert "a.py" not in hands(after, "a.py")
        # the declared read, as jokbo calls it: one argument per path
        for m in ("plugin.json", os.path.join(".claude-plugin", "plugin.json"), os.path.join(".codex-plugin", "plugin.json")):
            argv = json.load(open(os.path.join(HERE, m), encoding="utf-8"))["reads"]["hands"]
            assert argv[2:] == ["show", "--target", "{target}", "--after", "{after}", "--hands", "{paths}"], (m, argv)


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
