"""PreToolUse hook on Bash — an operation outside the repository (a deploy, a push, a deletion) is recorded with `did`.

Payload (stdin JSON): {"cwd": ..., "tool_name": "Bash", "tool_input": {"command": ...}}. Never refuses: when a run is in
progress and the command reads as an operation (chongdae.bash_operation: `git push`, `npm run deploy`, `wrangler deploy`,
…; hunsu.json settings.chongdae.ops-patterns replaces the list), it adds one line of context naming the `did` that records
it, and the command runs as asked. No run, no match, or a worker session (AGENT_WORKER=1: the run is the hiring
session's): silent. guin-site run-20261015-054352-a0ec ran `npm run deploy … | grep …; git push 2>&1 | tail -1` as plain
Bash — both exit codes lost — and wrote the push into ATPROTO.md as prose. An operation after a `chongdae … close` on the
same line runs outside any run: the line says to move it before close.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import chongdae  # noqa: E402

PY = "python3" if shutil.which("python3") else "python"   # the name that actually exists here — macOS ships only python3


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if os.environ.get("AGENT_WORKER"):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    cwd = chongdae.project_root(payload.get("cwd") or os.getcwd())
    if not os.path.isdir(os.path.join(cwd, chongdae.RUNS)):
        return 0
    d = chongdae.run_dir(cwd)
    state = chongdae.load_state(d) if d else {}
    if state.get("status") != "running":
        return 0
    what = chongdae.bash_operation(cwd, command)
    if not what:
        return 0
    plan = chongdae.load(os.path.join(d, "plan.json"))
    open_ = chongdae.open_tasks(plan, state)
    engine = os.path.join(os.path.dirname(HERE), "chongdae.py").replace(os.sep, "/")
    if chongdae.after_close(cwd, command):
        # the line closes the run first: the operation runs outside any run, where no `did` can record it (guin-site 10-15:
        # `…run; git commit; close; git push`, told "record it: did …", pushed after the run had closed)
        msg = ("chongdae: this `%s` runs after `close`, outside any run — move it before close as `%s \"%s\" did TASK --why \"…\" -- %s` "
               "(its own call; open tasks of run %s: %s), then close." % (what, PY, engine, what, os.path.basename(d), ", ".join(open_) or "-"))
    else:
        msg = ("chongdae: `%s` is an operation outside the repository and run %s is in progress — record it: `%s \"%s\" did TASK --why \"…\" -- <command>` "
               "(one command, no shell line: chongdae runs it and keeps its exit and output's end; open tasks: %s). Run as plain Bash, its exit and output "
               "reach no record." % (what, os.path.basename(d), PY, engine, ", ".join(open_) or "-"))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
