"""SessionStart hook — one line: which run is in progress, or that none is (and how to start one).

Reads the hook payload (stdin JSON with `cwd`). Never blocks, never writes.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import chongdae  # noqa: E402

PY = "python3" if shutil.which("python3") else "python"   # the name that actually exists here — macOS ships only python3


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
            json.dump({"transcript": path, "agent": os.environ.get("AI_AGENT"), "started": payload.get("source")}, fh)
    except OSError:
        pass   # never block a session start over bookkeeping


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    remember_session(cwd, payload)
    d = chongdae.run_dir(cwd) if os.path.isdir(os.path.join(cwd, chongdae.RUNS)) else None
    state = chongdae.load_state(d) if d else {}
    engine = os.path.join(os.path.dirname(HERE), "chongdae.py").replace(os.sep, "/")
    if state.get("status") == "running":
        plan = chongdae.load(os.path.join(d, "plan.json"))
        open_ = [tid for tid, ts in state["tasks"].items() if ts.get("status") not in ("done", "skipped")]
        msg = ("chongdae: run %s in progress (%s: %r) — %d task(s) open: %s. Writes go through this run; `%s \"%s\" run` advances it."
               % (os.path.basename(d), plan.get("kind", "?"), plan.get("goal", ""), len(open_), ", ".join(open_) or "-", PY, engine))
    else:
        msg = ("chongdae: no run in progress — the run is the agent's container, so Edit/Write are refused until one starts: "
               "`%s \"%s\" init --session --goal \"...\"` (tasks added as you go) or `... init --plan FILE`. The engine is that file; there is no `chongdae` binary." % (PY, engine))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
