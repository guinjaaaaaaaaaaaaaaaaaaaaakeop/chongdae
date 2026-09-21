"""PreToolUse hook on Edit/Write — the run is the agent's container, enforced at write time, not in prose.

Payload (stdin JSON): {"cwd": ..., "tool_name": "Edit"|"Write"|..., "tool_input": {"file_path": ...}}.
  file outside cwd                       -> allow (not this project's)
  file under .chongdae/, .claude/, hunsu* -> allow (the record and the environment are written by their own engines)
  a run in progress                      -> allow
  otherwise                              -> deny (exit 2): start a run first
Bash is not covered (reads would be); dwitbuk's `outside-run` finding catches what slips through.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import chongdae  # noqa: E402

EXEMPT = (chongdae.RUNS, ".claude", "hunsu")
PY = "python3" if shutil.which("python3") else "python"   # the name that actually exists here — macOS ships only python3


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    cwd = os.path.abspath(payload.get("cwd") or os.getcwd())
    path = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_input") or {}).get("notebook_path") or ""
    if not path:
        return 0
    rel = os.path.relpath(os.path.abspath(path), cwd).replace(os.sep, "/")
    if rel.startswith(chongdae.RUNS + "/wt/"):
        # a path inside a run's worktree: that worktree is the project the write belongs to — re-anchor there, so the
        # exempt `.chongdae/` prefix of the main tree does not wave through every write into a worktree
        parts = rel.split("/", 3)
        if len(parts) == 4:
            cwd = os.path.join(cwd, *parts[:3])
            rel = parts[3]
    if rel.startswith("..") or rel.startswith(EXEMPT):
        return 0
    d = chongdae.run_dir(cwd) if os.path.isdir(os.path.join(cwd, chongdae.RUNS)) else None
    if d and chongdae.load_state(d).get("status") == "running":
        return 0
    engine = os.path.join(os.path.dirname(HERE), "chongdae.py").replace(os.sep, "/")
    print("chongdae: no run in progress — writes happen inside a run. `%s \"%s\" init --session --goal \"...\"` (then `... add <id>` for this piece), or `... init --plan FILE`." % (PY, engine), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
