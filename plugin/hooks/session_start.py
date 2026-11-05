"""SessionStart hook — one line: which run is in progress, or that none is (and how to start one).

Reads the hook payload (stdin JSON with `cwd` — the shell's directory, anchored to the project: chongdae.project_root). Never blocks. Writes one machine-local file when the project keeps a
record: `.chongdae/sessions/<session id>.json`, the host's transcript path for this session (ignored, never committed).
Inside a worker session (AGENT_WORKER=1 — a builder, a judge, the eyes, a newcomer are host sessions too, and the host runs
the project's hooks in them): silent. The run is the hiring session's; a worker that is told about it reads what its role
may not see (guin-site 2026-10-01: the newcomer's premise, judged an authority conflict). Under hunsu's probe
(HUNSU_SURVEY=1, run in an empty project to judge what this hook tells a session): its standing text — every line it can say,
as templates with no live run id, goal, count or branch — and nothing written. In an empty project the hook showed only its
"no run in progress" line, and in the project itself its line moved between rounds with the run's id (guin-site 10-15).
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import chongdae  # noqa: E402

PY = "python3" if shutil.which("python3") else "python"   # the name that actually exists here — macOS ships only python3


def running_text(run, kind, goal, count, ids, py, engine):
    return ("chongdae: run %s in progress (%s: %s) — %s task(s) open: %s. Writes go through this run; `%s \"%s\" run` advances it."
            % (run, kind, goal, count, ids, py, engine))


def idle_text(py, engine):
    return ("chongdae: no run in progress — the run is the agent's container, so Edit/Write are refused until one starts: "
            "`%s \"%s\" init --session --goal \"...\"` (tasks added as you go) or `... init --plan FILE`. The engine is that file; there is no `chongdae` binary." % (py, engine))


def standing():
    """What this hook can say in any state, the same on every machine and at every moment."""
    engine = "<this plugin>/chongdae.py"
    return ("chongdae, at session start, says one line on this project's run — when a run is in progress: \"%s\" When none is: \"%s\" "
            "When the branch and its upstream differ (read from the local remote-tracking refs, never a fetch), it adds one of: "
            "\"<branch>: no upstream.\", \"<branch>: its upstream has not been fetched yet (no remote-tracking ref).\", "
            "\"<branch>: <N> commits not on <remote>/<branch>; <M> of <remote>/<branch>'s not here (as of the last fetch).\" "
            "Silent in a worker session (AGENT_WORKER=1): the run is the hiring session's."
            % (running_text("<run-id>", "<session | plan | bootstrap>", "'<goal>'", "<N>", "<the open task ids>", "python3", engine), idle_text("python3", engine)))


def remember_session(cwd, payload):
    """session id -> the host's transcript path, so a task this session performs can name its model (the transcript says it;
    the env does not). Machine-local, under .chongdae/sessions/ (ignored); only when the project already keeps a record."""
    sid, path = payload.get("session_id"), payload.get("transcript_path")
    if not (sid and path) or not os.path.isdir(os.path.join(cwd, chongdae.RUNS)):
        return
    d = os.path.join(cwd, chongdae.SESSIONS)
    try:
        os.makedirs(d, exist_ok=True)
        if not os.path.exists(os.path.join(d, ".gitignore")):
            with open(os.path.join(d, ".gitignore"), "w", encoding="utf-8") as fh:
                fh.write("*\n")   # the directory ignores itself: transcript paths are this machine's
        with open(os.path.join(d, sid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"transcript": path}, fh)   # the one field read (chongdae.py `session_transcript`); `agent`/`started` were written and read by nothing
    except OSError:
        pass   # never block a session start over bookkeeping


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if os.environ.get("AGENT_WORKER"):
        return 0
    if os.environ.get("HUNSU_SURVEY"):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": standing()}}))
        return 0
    cwd = chongdae.project_root(payload.get("cwd") or os.getcwd())
    remember_session(cwd, payload)
    d = chongdae.run_dir(cwd) if os.path.isdir(os.path.join(cwd, chongdae.RUNS)) else None
    state = chongdae.load_state(d) if d else {}
    engine = os.path.join(os.path.dirname(HERE), "chongdae.py").replace(os.sep, "/")
    if state.get("status") == "running":
        plan = chongdae.load(os.path.join(d, "plan.json"))
        open_ = chongdae.open_tasks(plan, state)   # the rule `run` and `status` use: a dropped task is not open (guin-site, 2026-10-12)
        msg = running_text(os.path.basename(d), plan.get("kind", "?"), repr(plan.get("goal", "")), len(open_), ", ".join(open_) or "-", PY, engine)
    else:
        msg = idle_text(PY, engine)
    line = chongdae.upstream_line(cwd)   # local remote-tracking refs only, no fetch: 213 commits sat unpushed for 10 days and nothing said so (guin-site, 10-15)
    if line:
        msg += " " + line + "."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
