"""chongdae — runs a plan: a DAG of roles that produce artifacts, with checks in code and human gates in between.

  init  --goal "..." | --plan FILE     start a run: the bootstrap plan (questions -> plan document -> modeler) or a plan the session agent wrote
  init  --merge [--base REV]            after merging branches: the merge plan — recheck (+ coherence when the lock declares that role) behind a human gate
  init  --session [--goal "..."]        a session run: no plan, tasks added as the work goes (`add`), closed when the session ends (`close`)
  init  ... --worktree                  the run gets its own worktree + branch under .chongdae/wt/ (the shared tree may have other workers); `close` commits and merges it back — a conflict or red recheck becomes a merge run
  add   <id> [--brief ..] [--closes Q..] [--check ARGV]... [--tests F]... [--gate human]   a task in the session run; the start snapshot is taken now
  claim <id> [--by NAME]                take a task (defaults to git user.name); `run` skips tasks claimed by someone else
  drop  <id> --why WHY [--by NAME]      a session task that will not be done: leaves the open set, stays in the record with the reason
  close [--target DIR] [--run ID]       end a session run (open tasks recorded as such); a worktree run merges back — a completed plan run too
  report [--since REV]                  what this record says a reviewer should see, as `dwitbuk/findings@1` on stdout: changes no run
                                        claims (outside-run), runs that recorded no `touched` (unattributed), gates/decisions/retries passed
                                        by delegation, and every non-claim. chongdae knows its runs and git; a reviewer knows the type
  status [--target DIR]                 the run in progress (or the newest) and its open tasks; exit 0 always — for a skill's first look
  run   [--target DIR]                  advance one step. Exit 2 = stopped for the session agent or a human; the last line says what to do
  confirm <task> [--by NAME | --delegated "why"] [--target DIR]   record the human's confirmation of a produced artifact
  delegate --scope confirm,accept,... --why "..." --by NAME [--run ID]   declare a batch pre-approval once, as its own judgment; later
                                        judgments reference it: `--delegated D-xxxx` (recorded as {ref}, not the words repeated)
  accept  <task> [--by NAME | --delegated WHY]   a human accepts decisions a provider made beyond the contract (after writing them into the plan)
  retry   <task> [--by NAME | --delegated WHY]   a human sends a stopped task (blocked, failed, no response) out again; the next call gets the earlier attempts
  recheck [--target DIR]                after a merge: re-run every completed run's checks on this tree. exit 1 if any is red now

A plan may declare a `verifier` role (providers.verifier — a command; never the hands that built). After a task's checks pass and
before its gate, the verifier gets the contract, the touched files and the builder's report, and answers `dwitbuk/review@1`
(accept | reject + quoted findings). Reject is the failed path: `retry`. A task's `tests` are the contract's: a build that changes
them is rejected. A gate `{"human": true, "delegate": "after-verifier"}` refuses delegation until an accept.

chongdae has no brain. It does not write questions, plans or code. When a task's provider is `session`, it stops and asks the
session agent (the brain) to produce the artifact; then it checks the artifact's shape and stops again for the human.
Roles are names; who provides them comes from hunsu.lock.json `roles` (or the plan's own `providers`). A role with no
provider is skipped and recorded as a non-claim — never substituted.
Artifacts a task produces live in the project (task `path` is project-relative). `.chongdae/` holds only how a run went:
`plan.json` (the intent), `state.json` (status), `tasks/<id>.json` (one file per task, so two people's work on one run merges).
The run is the agent's container: the plugin's PreToolUse hook refuses Edit/Write in a project with no run in progress.
"""
import argparse
import io
import json
import os
import re
import shlex
import shutil
import sys

RUNS = ".chongdae"
DECISION = 2
DISPATCH = 3   # spawn: a native provider — the session must run the subagent and write the answer, then `run` again
WAITING = 4    # spawn: the provider is still working past the wait budget — `run` again keeps waiting (the pending record finds it)
WAIT_BUDGET = int(os.environ.get("CHONGDAE_WAIT", 480))   # seconds one `run` waits for providers before returning: a host's tool call has its own timeout (Claude Code: 10 min), and a run that outlives it gets backgrounded and orphaned
_CALL_DEADLINE = None   # set once per `run` call: the budget is the call's, not each spawn's — a call that finishes one provider and starts the next does not wait twice

BOOTSTRAP = [
    {"id": "questions", "role": "questions", "produces": "plan/questions@1", "path": "plan/questions.json",
     "needs": [], "gate": "human",
     "brief": "List the questions this goal must answer for the work to count as done. Each: {\"id\": \"Q-<word>\", \"text\": \"...\"} — "
              "name the id after the question (Q-drafts, Q-feed-order), never a bare number: numbered ids collide when parallel workers each add \"the next number\" and someone must renumber at the merge. "
              "If the questions cannot be settled because the goal is under-shaped, say so instead: {\"under-shaped\": \"why\"} — the run then turns into an ideation plan."},
    {"id": "plan", "role": "plan", "produces": "plan/document@1", "path": "plan/PLAN.md",
     "needs": ["questions"], "gate": "human",
     "brief": "Write the plan as Markdown. One `## <Q-id> ...` section per question, answering it with what will be built and a testable "
              "acceptance criterion (a sentence a check can decide). Slices come last under `## slices`, one per line, each naming the question ids it closes."},
    {"id": "model", "role": "modeler", "produces": "sidecar/registry@1", "path": None,
     "needs": ["plan"], "gate": None, "optional": True,
     "brief": "Register the plan document and its question sections in the project's semantic model; declare question<->section relations and the CQ 'every question has a section'."},
]


def merge_plan(target, base):
    """The merge is a run: two branches were each right alone; this tree must be right again, and someone must say so.
    One task — recheck and coherence are one job on one tree — behind one human gate. chongdae names its own recheck; the
    coherence checks come from the `coherence` role (hunsu.lock.json `roles`, argv with `{base}`) — a runner never names a provider."""
    checks = [["python3", "{plugin:chongdae}/chongdae.py", "recheck"]]   # run_checks falls back to `python` where only that exists
    brief = "Every completed run's checks, green again on the merged tree. Red means fix the tree, not the record."
    coherence = providers(target, {}).get("coherence")
    non_claims = []
    if coherence:
        checks += [[a.replace("{base}", base) for a in argv] for argv in (coherence if isinstance(coherence[0], list) else [coherence])]
        brief += " Relations one branch confirmed on what the other changed: re-read each; retire or re-confirm, until the coherence check is green."
    else:
        non_claims.append("no `coherence` role in the lock: what a semantic model would have said about this merge is not said")
    return {"artifact-type": "chongdae/plan@1", "goal": "merge (base %s)" % base, "kind": "merge", "base": base, "providers": {"merger": "session"},
            "non-claims": non_claims, "tasks": [{"id": "merge", "role": "merger", "needs": [], "gate": "human", "checks": checks, "brief": brief}]}


def load(path):
    if not os.path.exists(path):
        return {}
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def load_state(d):
    """The run's state: status from state.json, tasks from tasks/<id>.json (older runs kept tasks inside state.json — read as is)."""
    state = load(os.path.join(d, "state.json"))
    tasks = state.get("tasks") or {}
    folder = os.path.join(d, "tasks")
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json"):
                tasks[name[:-5]] = load(os.path.join(folder, name))
    state["tasks"] = tasks
    state.setdefault("non-claims", [])
    return state


def save_state(d, state):
    """One file per task, so tasks done on different branches merge as distinct files. state.json keeps only the run's own fields."""
    for tid, ts in state.get("tasks", {}).items():
        save(os.path.join(d, "tasks", tid + ".json"), {"artifact-type": "chongdae/task@1", **ts})
    save(os.path.join(d, "state.json"), {"artifact-type": "chongdae/run@1", **{k: v for k, v in state.items() if k != "tasks"}})


def all_tasks(plan, state):
    """The plan's tasks plus the ones added during a session run (each carries its own definition in its task file), the
    added ones in the order they were added (`seq`) — task files are read in name order, and a name is not a time."""
    added = sorted((ts for ts in state.get("tasks", {}).values() if "def" in ts), key=lambda ts: (ts.get("seq", 0), ts["def"].get("id", "")))
    return plan.get("tasks", []) + [ts["def"] for ts in added]


def me(target):
    """Who is acting on this machine: CHONGDAE_USER, else git user.name. Claims are compared against it."""
    import subprocess
    return os.environ.get("CHONGDAE_USER") or subprocess.run(["git", "config", "user.name"], cwd=target, capture_output=True, text=True).stdout.strip() or "unknown"


def now_utc():
    """The moment of a judgment, in UTC with the offset written (git writes both times with offsets; ours are normalized).
    For display and honesty only — order between machines is never decided by clocks, only by the record's own git history."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def head_sha(target):
    """The commit this tree stands on — a run pinned to it can be ordered by ancestry, not by anyone's clock."""
    import subprocess
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


# What stays on this machine: a worker's whole session (what it read, printed, thought) and the request exactly as sent carry
# this machine's paths and can be megabytes a call. They are kept for a local audit; what other people and workers need goes
# into the committed record as `<tag>.trace.json` — the model, the commands and their exit codes, the files changed — with
# the project as `.` and the home directory as `~`.
RECORD_IGNORE = ["*.transcript*.jsonl", "*.request.json", "*.request.*.json", "*.provider.log", "*.pending.json",
                 "*.last.txt", "*.schema.json", "sessions/"]


def ensure_record_ignore(target):
    """`.chongdae/.gitignore` lists what stays local. Written by chongdae, for chongdae's own files only."""
    path = os.path.join(target, RUNS, ".gitignore")
    have = io.open(path, encoding="utf-8").read().split("\n") if os.path.exists(path) else []
    missing = [p for p in RECORD_IGNORE if p not in have]
    if missing:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        head = [] if have and have != [""] else ["# chongdae: machine-local — each worker's full session and the request as sent stay on this machine;",
                                                "# the committed record carries <tag>.trace.json (commands, exit codes, files changed)"]
        with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(head + missing) + "\n")


def neutral_path(text, target):
    """This machine taken out of a string: the project -> `.`, a host's installed plugin -> `<plugin:NAME@VERSION>` (which
    marketplace it came from is this machine's business, which version it was is the record's), a temporary directory ->
    `<tmp>`, the home directory -> `~`."""
    import tempfile
    text = str(text)
    for root in sorted({os.path.abspath(target), os.path.realpath(target)}, key=len, reverse=True):
        text = text.replace(root + os.sep, "./").replace(root, ".")
    home = os.path.expanduser("~")
    text = re.sub(r"(?:%s|~)/\.(?:claude|codex)/plugins/cache/[^/\s\"']+/([^/\s\"']+)/([^/\s\"']+)" % re.escape(home),
                  lambda m: "<plugin:%s@%s>" % (m.group(1), m.group(2)), text)
    # a path above one plugin's version — a marketplace's cache or checkout — names only this machine's marketplaces
    text = re.sub(r"(?:%s|~)/\.(claude|codex)/plugins/(?:cache|marketplaces)(?:/[^/\s\"']+)?" % re.escape(home),
                  lambda m: "<%s-plugins>" % m.group(1), text)
    tmps = {tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir()), "/private/tmp", "/tmp"}
    for t in sorted(tmps, key=len, reverse=True):
        text = re.sub(r"%s/[^\s\"'/]+" % re.escape(t.rstrip("/")), "<tmp>", text)
    text = re.sub(r"/(?:private/)?var/folders/[^\s\"']*", "<tmp>", text)
    return text.replace(home, "~") if home and home != "~" else text


def trace_of(transcript, target):
    """A worker's session, reduced to what a reader of the record needs: the commands it ran with their exit codes, the files
    it changed (and, where the host says so, read). Codex: `command_execution` and `file_change` items; Claude Code: tool
    calls and their results."""
    commands, changed, read, calls = [], [], [], {}
    for line in io.open(transcript, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        it = d.get("item") or {}
        if d.get("type") == "item.completed" and it.get("type") == "command_execution":
            cmd = it.get("command", "")
            m = re.match(r"^/bin/(?:ba|z)?sh -l?c (.*)$", cmd, re.S)   # the host's shell wrapper; the command is its argument
            if m:
                try:
                    cmd = shlex.split(m.group(1))[0]
                except ValueError:
                    cmd = m.group(1)
            commands.append({"command": neutral_path(cmd, target), "exit": it.get("exit_code")})
        elif d.get("type") == "item.completed" and it.get("type") == "file_change":
            for c in it.get("changes") or []:
                entry = "%s %s" % (c.get("kind", "change"), neutral_path(c.get("path", ""), target))
                if entry not in changed:
                    changed.append(entry)
        elif d.get("type") == "assistant":
            for c in (d.get("message") or {}).get("content", []):
                if c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    if c.get("name") == "Bash":
                        calls[c.get("id")] = {"command": neutral_path(inp.get("command", ""), target), "exit": None}
                        commands.append(calls[c.get("id")])
                    elif c.get("name") in ("Edit", "Write", "NotebookEdit"):
                        entry = "%s %s" % (c["name"].lower(), neutral_path(inp.get("file_path", ""), target))
                        if entry not in changed:
                            changed.append(entry)
                    elif c.get("name") in ("Read", "Glob", "Grep"):
                        entry = neutral_path(inp.get("file_path") or inp.get("path") or inp.get("pattern") or "", target)
                        if entry and entry not in read:
                            read.append(entry)
        elif d.get("type") == "user":
            for c in (d.get("message") or {}).get("content", []) if isinstance((d.get("message") or {}).get("content"), list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                    calls[c["tool_use_id"]]["exit"] = 1 if c.get("is_error") else 0
    return {"commands": commands, "changed": changed, **({"read": read} if read else {})}


def write_traces(target, run_name):
    """For every kept session in the run without a trace yet, write its trace beside it (same tag and attempt number)."""
    d = os.path.join(target, RUNS, run_name)
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        m = re.match(r"^(.*)\.response\.transcript(\.\d+)?\.jsonl$", name)
        if not m:
            continue
        out = os.path.join(d, "%s.trace%s.json" % (m.group(1), m.group(2) or ""))
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(os.path.join(d, name)):
            continue
        response = load(os.path.join(d, "%s.response%s.json" % (m.group(1), m.group(2) or "")))
        w = response.get("worker") or {}
        save(out, {"artifact-type": "chongdae/trace@1", "worker": {k: w.get(k) for k in ("host", "model", "effort", "turns", "session") if w.get(k) is not None},
                   **trace_of(os.path.join(d, name), target),
                   "kept-locally": name})


def commit_record(target, run_name, message):
    """A judgment was written into the run's record: commit that record, and only it, right now. git's immutability then
    notarizes the judgment — its content (the tree hash), its time (committer date), and any later edit (a visible diff).
    Without this the record's durability was a habit of whoever remembered to commit; now it is the engine's.
    The paths are pinned to the run's directory so a dirty working tree (someone else's work in flight) is never swept in.
    Best effort by design: no repo, nothing staged, or an identity-less git config must not stop the run — the record on
    disk is still the record; `close` and the reviewer see uncommitted records as what they are."""
    import subprocess

    def git(*a):
        return subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")

    rel = RUNS + "/" + run_name
    ensure_record_ignore(target)
    try:
        write_traces(target, run_name)
    except (OSError, ValueError):
        pass   # a trace is a summary; the record commits without it rather than not at all
    # The commit is built on a scratch index from HEAD: only this run's directory and chongdae's .gitignore enter it — what
    # the person has staged stays theirs — and a file an earlier version committed that is now local-only leaves it (a
    # path-limited `git commit` would take the file back from the working tree, where it rightly stays).
    gitdir = git("rev-parse", "--absolute-git-dir").stdout.strip()
    if not gitdir:
        return None
    env = dict(os.environ, GIT_INDEX_FILE=os.path.join(gitdir, "chongdae-record-index"))
    scratch = lambda *a: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    has_head = git("rev-parse", "--verify", "-q", "HEAD").returncode == 0
    try:
        scratch("read-tree", "HEAD") if has_head else scratch("read-tree", "--empty")
        if scratch("add", "--", rel, RUNS + "/.gitignore").returncode:
            return None
        stale = [t for t in scratch("ls-files", "-ci", "--exclude-standard", "--", rel).stdout.split("\n") if t.strip()]
        if stale:
            scratch("rm", "--cached", "--quiet", "--", *stale)
        if has_head and scratch("diff-index", "--cached", "--quiet", "HEAD", "--").returncode == 0:
            return None   # nothing of this run changed -> nothing to notarize
        tree = scratch("write-tree").stdout.strip()
        made = git("commit-tree", tree, *(["-p", "HEAD"] if has_head else []), "-m", "%s: %s" % (run_name, message))
        if made.returncode or not made.stdout.strip():
            return None
        if git("update-ref", "HEAD", made.stdout.strip()).returncode:
            return None
    finally:
        try:
            os.remove(env["GIT_INDEX_FILE"])
        except OSError:
            pass
    git("reset", "-q", "--", rel, RUNS + "/.gitignore")   # the person's index now agrees with HEAD for the record, and only there
    return head_sha(target)


def non_claims(state):
    """Every non-claim in the run, prefixed with its task — the reader's view over the per-task files (and older runs' shared list)."""
    out = list(state.get("non-claims", []))
    for tid, ts in state.get("tasks", {}).items():
        out += ["%s: %s" % (tid, n) for n in ts.get("non-claims", [])]
    return out


def all_runs(target):
    root = os.path.join(target, RUNS)
    return sorted(os.path.join(root, d) for d in os.listdir(root) if d.startswith("run-")) if os.path.isdir(root) else []


def run_dir(target, run_id=None):
    """The run to act on: the one named, else the one still running, else the newest by id. Never by file time (clones share none)."""
    runs = all_runs(target)
    if run_id:
        match = [r for r in runs if os.path.basename(r) == run_id]
        if not match:
            raise SystemExit("no run %s" % run_id)
        return match[0]
    running = [r for r in runs if load_state(r).get("status") == "running"]
    return (running or runs or [None])[-1]


def is_self_recheck(argv):
    """A check that is chongdae's own recheck. Re-running it from inside a recheck recurses without end
    (a merge run's check is `chongdae recheck`; recheck re-runs every completed run's checks — including that one).
    The verdict it stood for is exactly what the outer recheck is already computing, so it is skipped, not lost."""
    return any(a == "recheck" for a in argv) and any("chongdae" in str(a) for a in argv)


def cmd_recheck(args):
    """After a merge: every completed run's checks, re-run on this tree. A run's `done` was true on its own branch; here it must be true again."""
    target = args.target
    red, green, unchecked = [], [], []
    for r in all_runs(target):
        plan, state = load(os.path.join(r, "plan.json")), load_state(r)
        if state.get("status") != "complete":
            continue
        for task in all_tasks(plan, state):
            if state["tasks"].get(task["id"], {}).get("status") != "done":
                continue
            checks = [c for c in task.get("checks", []) if not is_self_recheck(c)]
            if not checks:
                unchecked.append("%s/%s" % (os.path.basename(r), task["id"]))
                continue
            failed = run_checks(target, checks)
            (red if failed else green).append(("%s/%s" % (os.path.basename(r), task["id"]), failed))
    for name, _ in green:
        print("  still green  %s" % name)
    for name, failed in red:
        print("  RED          %s" % name)
        for f in failed:
            print("      %s" % f)
    if unchecked:
        print("  no checks    %s (artifact tasks — their shape held then; nothing re-decides them here)" % ", ".join(unchecked))
    print("recheck: %d green · %d red · %d without checks" % (len(green), len(red), len(unchecked)))
    # the verdict is a record, not a line on a screen: `.chongdae/rechecks/<time>.json`, so "recheck was green" can be pointed at
    import subprocess
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=target, capture_output=True, text=True).stdout.strip() or None
    rec = {"artifact-type": "chongdae/recheck@1", "at": now_utc(), "head": head, "green": [n for n, _ in green],
           "red": [{"task": n, "failed": f} for n, f in red], "unchecked": unchecked}
    path = os.path.join(target, RUNS, "rechecks", rec["at"].replace(":", "").replace("+", "p") + ".json")
    save(path, rec)
    print("  recorded -> %s" % os.path.relpath(path, target).replace(os.sep, "/"))
    return 1 if red else 0


def providers(target, plan):
    """role -> provider. The lock's `roles` (a human declaration hunsu checked) first; the plan's own `providers` may add or override."""
    lock = load(os.path.join(target, "hunsu.lock.json"))
    out = dict(lock.get("roles", {}))
    out.update(plan.get("providers", {}))
    return out


# ---------------------------------------------------------------- artifact checks (shape only; meaning is the human's)

def check_questions(path, state):
    doc = load(path)
    if doc.get("under-shaped"):
        return ["the goal is under-shaped: %s — this run should become an ideation plan (not implemented yet)" % doc["under-shaped"]]
    qs = doc.get("questions")
    if not isinstance(qs, list) or not qs:
        return ["questions.json needs a non-empty `questions` list"]
    bad = [q for q in qs if not (isinstance(q, dict) and re.fullmatch(r"Q[\w-]+", str(q.get("id", ""))) and str(q.get("text", "")).strip())]
    return ["%d question(s) lack an id like Q1 or Q-drafts, or a text" % len(bad)] if bad else []


def check_plan(path, state):
    text = io.open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    ids = [q["id"] for q in load(os.path.join(os.path.dirname(path), "questions.json")).get("questions", [])]   # sibling: plan/questions.json
    headings = re.findall(r"^## +(Q[\w-]+)\b", text, re.M)
    missing = [i for i in ids if i not in headings]
    problems = []
    if missing:
        problems.append("no `## <id>` section for %s" % ", ".join(missing))
    if not re.search(r"^## +slices", text, re.M):
        problems.append("no `## slices` section")
    return problems


CHECKS = {"plan/questions@1": check_questions, "plan/document@1": check_plan}


# ---------------------------------------------------------------- the state machine

def stop(msg, *lines):
    for line in lines:
        print("  " + line)
    print("decision: " + msg)
    return DECISION


def make_worktree(main, run_name, base=None):
    """The run's container, physically: a worktree under .chongdae/wt/<run-id> on branch run/<run-id>, branched from HEAD.
    A tree with git history may have other workers (people, agents, other machines) — the shared tree is not this run's to
    dirty. Machine-local files the environment needs (hunsu.local.json) are copied; everything else travels by commit."""
    import subprocess
    if subprocess.run(["git", "rev-parse", "HEAD"], cwd=main, capture_output=True).returncode:
        raise SystemExit("--worktree needs a commit to branch from — commit first (or run without --worktree)")
    path = os.path.join(main, RUNS, "wt", run_name)
    done = subprocess.run(["git", "worktree", "add", "-b", "run/" + run_name, path] + ([base] if base else []), cwd=main, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode:
        raise SystemExit("git worktree add failed: %s" % (done.stderr or done.stdout).strip()[-300:])
    # ignore the wt dir from inside the worktree's own .gitignore — main's tree stays untouched; the line lands in main with the merge
    ignore = os.path.join(path, ".gitignore")
    lines = io.open(ignore, encoding="utf-8").read().split("\n") if os.path.exists(ignore) else []
    if RUNS + "/wt/" not in lines:
        io.open(ignore, "a", encoding="utf-8", newline="\n").write(("" if not lines or lines[-1] == "" else "\n") + RUNS + "/wt/\n")
    local = os.path.join(main, "hunsu.local.json")
    if os.path.exists(local):
        shutil.copy(local, os.path.join(path, "hunsu.local.json"))
    print("worktree %s (branch run/%s) — work there; `close` commits it and merges back" % (path.replace(os.sep, "/"), run_name))
    return path


def cmd_init(args):
    target = args.target
    if run_dir(target) and load_state(run_dir(target)).get("status") == "running":
        raise SystemExit("a run is already in progress: %s — finish it or remove it" % run_dir(target))
    # Run ids are unique across machines (date + random), so runs made on different branches merge as distinct directories.
    # UTC, so the id's lexical order approximates creation order regardless of timezone — an approximation for humans only;
    # real order is `based_on`/`landed` ancestry in git, never a clock (id order can still invert under clock skew).
    import secrets, time
    run_name = "run-%s-%s" % (time.strftime("%Y%m%d-%H%M%S", time.gmtime()), secrets.token_hex(2))
    if getattr(args, "worktree", False):
        target = make_worktree(args.target, run_name, getattr(args, "base", None) if not getattr(args, "merge", False) else None)   # the run's container is physical: its own worktree, its own branch (from --base, else HEAD)
    d = os.path.join(target, RUNS, run_name)
    if args.plan:
        if args.plan == "-":
            # the plan is intent written before its run exists, so the write gate (no run -> no project write) would refuse it in the
            # tree; stdin needs no file, and the run keeps the only copy that matters (plan.json)
            try:
                plan = json.loads(sys.stdin.read() or "")
            except ValueError as err:
                raise SystemExit("--plan -: stdin is not JSON (%s)" % err)
        else:
            plan_path = args.plan if os.path.exists(args.plan) else os.path.join(target, args.plan)   # relative to the target, like a task's path
            if not os.path.exists(plan_path):
                raise SystemExit("no plan file %s" % args.plan)
            plan = load(plan_path)
        problems = plan_problems(plan)
        if problems:
            raise SystemExit("plan rejected:\n  " + "\n  ".join(problems))
    elif args.session:
        plan = {"artifact-type": "chongdae/plan@1", "goal": args.goal or "session", "kind": "session", "tasks": [], "providers": {"session": "session"}}   # other roles come from the lock: `add --role implementer` hands a task to the locked implementer
        if getattr(args, "from_doc", None):
            plan["from"] = args.from_doc   # the plan document whose `## Q-…` sections a task `closes`: providers get those sections as the contract
    elif args.merge:
        import subprocess
        base = args.base or subprocess.run(["git", "merge-base", "HEAD^1", "HEAD^2"], cwd=target, capture_output=True, text=True).stdout.strip()[:12]
        if not base:
            raise SystemExit("--merge needs --base REV (HEAD is not a merge commit, so no merge base can be found)")
        plan = merge_plan(target, base)
    else:
        plan = {"artifact-type": "chongdae/plan@1", "goal": args.goal, "kind": "bootstrap", "tasks": BOOTSTRAP,
                "providers": {"questions": "session", "plan": "session"}}   # the plan says who provides; chongdae assumes nothing
    save(os.path.join(d, "plan.json"), plan)
    state = {"status": "running", "tasks": {t["id"]: {"status": "todo"} for t in plan["tasks"]}, "non-claims": list(plan.get("non-claims", []))}
    state["created"] = {"at": now_utc(), "based_on": head_sha(target)}   # the commit this run starts from: its place in history is ancestry, not its id's timestamp
    if getattr(args, "worktree", False):
        state["worktree"] = {"main": os.path.abspath(args.target).replace(os.sep, "/"), "branch": "run/" + run_name}
    save_state(d, state)
    commit_record(target, run_name, "init (%s)" % plan.get("kind", "?"))
    print("run %s: goal %r — %s plan (%s). Now %s."
          % (os.path.basename(d), plan["goal"], plan.get("kind", "?"), " -> ".join(t["id"] for t in plan["tasks"]) or "no tasks yet",
             "`chongdae add <id> ...` for each piece of work, `chongdae run` to record it, `chongdae close` at the end" if args.session else "`chongdae run`"))
    if getattr(args, "worktree", False):
        print("this run lives in its worktree — every command from here on: --target %s" % target.replace(os.sep, "/"))
    return 0


def cmd_add(args):
    """A task in a session run, defined when the work starts. Its start snapshot is taken now, so `touched` is this task's own."""
    d = run_dir(args.target)
    if not d:
        raise SystemExit("no run in progress — `chongdae init --session`")
    plan, state = load(os.path.join(d, "plan.json")), load_state(d)
    if state.get("status") != "running":
        raise SystemExit("no run in progress — `chongdae init --session`")
    if plan.get("kind") != "session":
        raise SystemExit("tasks are added to session runs only; a plan run's tasks are the plan's")
    if args.id in state["tasks"] or any(t.get("id") == args.id for t in plan.get("tasks", [])):
        raise SystemExit("task %s exists" % args.id)
    task = {"id": args.id, "role": args.role, "brief": args.brief or "", "closes": args.closes or [], "needs": [], "checks": [shlex.split(c) for c in args.check or []],
            "tests": args.tests or [], "gate": "human" if args.gate == "human" else None}
    for when in ("before", "after"):
        if getattr(args, when) is not None:
            task[when] = getattr(args, when)
    problems = [x for x in plan_problems({"artifact-type": "chongdae/plan@1", "goal": "x", "tasks": [task]}) if "needs `path`" not in x]
    if problems:
        raise SystemExit("task rejected:\n  " + "\n  ".join(problems))
    ts = {"status": "todo", "def": task, "seq": 1 + max([t.get("seq", 0) for t in state["tasks"].values()] or [0]), "added": now_utc()}
    if task["role"] == "session":
        ts["start"] = dirty(args.target)   # the session works between `add` and `run`: what changed is measured from now
    # a provider's task starts when `run` spawns it (`start` is taken then): a build added alongside its test task must not see the test-writer's file as its own change
    if not task["checks"]:
        ts["non-claims"] = ["no check decides this task; done means the agent said so"]
    state["tasks"][args.id] = ts
    save_state(d, state)
    print("added %s to %s%s. Work, then `chongdae run`." % (args.id, os.path.basename(d), " (no checks — done will be a claim, recorded as such)" if not task["checks"] else ""))
    return 0


def cmd_drop(args):
    """A session task that will not be done — mis-specified, superseded, abandoned — leaves the open set with its reason, and
    stays in the record as `dropped`. Without this the cheap way out of a task was to close the run around it (or start a
    new run), which left it open forever and nobody looking; a drop is a decision, written down."""
    d = run_dir(args.target)
    plan, state = (load(os.path.join(d, "plan.json")), load_state(d)) if d else ({}, {})
    if plan.get("kind") != "session" or state.get("status") != "running":
        raise SystemExit("no session run in progress — only a session run's own tasks can be dropped; a plan's tasks are the plan's")
    ts = state["tasks"].get(args.task)
    if not ts:
        raise SystemExit("no task %s" % args.task)
    if ts["status"] in ("done", "skipped", "dropped"):
        raise SystemExit("%s is %s — nothing to drop" % (args.task, ts["status"]))
    ts["status"] = "dropped"
    ts["dropped"] = {"why": args.why, "by": args.by if args.by is not None else me(args.target), "at": now_utc()}
    ts["touched"] = touched_files(args.target, ts.get("start"))   # what changed in its window stays attributed to it, dropped or not
    ts.setdefault("non-claims", []).append("dropped, not done: %s" % args.why)
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "drop %s: %s" % (args.task, args.why))
    print("dropped %s: %s" % (args.task, args.why))
    return 0


def cmd_unstage(args):
    """A role hired before or after a task that cannot do its work here — a newbie on a project with nothing a newbie can
    run, say — comes off that task, with the reason. The task goes on without it; the record says the role did not look
    (a non-claim), and what it answered before it came off stays under `stages-taken-off`. Other tasks keep the role."""
    d = run_dir(args.target)
    if not d:
        raise SystemExit("no run")
    plan, state = load(os.path.join(d, "plan.json")), load_state(d)
    ts = state["tasks"].get(args.task)
    task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), None)
    if not ts or not task:
        raise SystemExit("no task %s" % args.task)
    if args.role not in stage_roles(plan, task, "before") + stage_roles(plan, task, "after"):
        raise SystemExit("%s is not hired before or after %s" % (args.role, args.task))
    ts.setdefault("unstaged", {})[args.role] = {"why": args.why, "by": args.by if args.by is not None else me(args.target), "at": now_utc()}
    rec = (ts.get("stages") or {}).pop(args.role, None)
    if rec:
        ts.setdefault("stages-taken-off", {})[args.role] = rec
    if ts.get("stages") == {}:
        ts.pop("stages")
    ts.setdefault("non-claims", []).append("%s did not look at this task (taken off: %s)" % (args.role, args.why))
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "unstage %s from %s: %s" % (args.role, args.task, args.why))
    print("%s taken off %s: %s — `chongdae run` goes on without it" % (args.role, args.task, args.why))
    return 0


def cmd_claim(args):
    """A person takes a task. chongdae does not assign; `run` on other machines skips what is claimed here."""
    d = run_dir(args.target)
    if not d:
        raise SystemExit("no run")
    state = load_state(d)
    ts = state["tasks"].get(args.task)
    if not ts:
        raise SystemExit("no task %s" % args.task)
    who = args.by if args.by is not None else me(args.target)
    if ts.get("claimed_by") and ts["claimed_by"] != who:
        raise SystemExit("%s is claimed by %s — they release it (claim --by \"\") or you agree with them, not with chongdae" % (args.task, ts["claimed_by"]))
    ts["claimed_by"] = who or None
    save_state(d, state)
    print("%s claimed by %s" % (args.task, who) if who else "%s released" % args.task)
    return 0


def runs_since(target, rev):
    """The runs whose record was not yet at `rev`: created after it, or still running there. Older runs were the previous review's."""
    import subprocess
    done = subprocess.run(["git", "ls-tree", "-r", "--name-only", rev, "--", RUNS], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
    then = set()
    for line in (done.stdout if done.returncode == 0 else "").splitlines():
        parts = line.split("/")
        if len(parts) >= 3 and parts[1].startswith("run-") and parts[2] == "state.json":
            shown = subprocess.run(["git", "show", "%s:%s" % (rev, line)], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                if json.loads(shown.stdout).get("status") == "complete":
                    then.add(parts[1])
            except ValueError:
                pass
    return {os.path.basename(r) for r in all_runs(target)} - then


def cmd_report(args):
    """chongdae's own findings about its record, typed `dwitbuk/finding@1` so a reviewer collects them without knowing chongdae."""
    import subprocess
    target = args.target
    findings = []

    def git(*a):
        done = subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return done.stdout if done.returncode == 0 else None

    # the tree vs the ledger: which changed files does no completed run claim?
    changed = set()
    if args.since:
        for line in (git("diff", "--name-only", "%s..HEAD" % args.since, "--", ".") or "").splitlines():
            changed.add(line.strip().replace("\\", "/"))
    for line in (git("status", "--porcelain", "--untracked-files=all", "--", ".") or "").splitlines():
        if len(line) > 3:
            changed.add(line[3:].strip().replace("\\", "/"))
    prefix = (git("rev-parse", "--show-prefix") or "").strip().replace("\\", "/")
    changed = {p[len(prefix):] if prefix and p.startswith(prefix) else p for p in changed}
    changed = {p for p in changed if not p.startswith((RUNS + "/", ".mangsang/", ".dwitbuk/", ".claude/", "reviews/", "hunsu")) and p != ".gitignore"}   # records, machine-local state, the host's settings, the environment (hunsu's own report covers it). Naming sibling record dirs here is chongdae's one known coupling to product names — accepted until a lock-declared record-paths convention earns its keep
    claimed, unattributed = set(), []
    for r in all_runs(target):
        name, plan, state = os.path.basename(r), load(os.path.join(r, "plan.json")), load_state(r)
        if state.get("status") != "complete":
            continue
        for task in all_tasks(plan, state):
            ts = state["tasks"].get(task["id"], {})
            if ts.get("status") in ("done", "dropped") and "touched" in ts:   # a dropped task's window is still a claim on what changed in it
                claimed.update(ts["touched"] or [])
            elif ts.get("status") == "done" and task.get("checks"):
                unattributed.append("%s/%s" % (name, task["id"]))
    for path in sorted(changed - claimed):
        findings.append({"kind": "outside-run", "where": path, "files": [path],
                         "text": "changed since %s; no completed run recorded touching it" % (args.since or "the beginning")})
    if unattributed:
        findings.append({"kind": "unattributed", "where": ", ".join(unattributed),
                         "text": "these runs completed without recording touched files; changes they made cannot be told from work outside runs"})
    # what no human decided, and what nobody claims
    def deleg_text(v):
        return "ref %s" % v.get("ref") if isinstance(v, dict) else v

    since_runs = runs_since(target, args.since) if args.since else None
    for r in all_runs(target):
        name, plan, state = os.path.basename(r), load(os.path.join(r, "plan.json")), load_state(r)
        if since_runs is not None and name not in since_runs:
            continue   # --since: what happened since that revision — a run whose record already existed there was reviewed then
        stamps = {}   # literal delegated reason -> where it was used, within this one run (refs are exempt: pointing at one declared judgment is their purpose)

        def stamp(v, where):
            if isinstance(v, str):
                stamps.setdefault(v, []).append(where)

        for tid, ts in state.get("tasks", {}).items():
            for key, label in (("confirmed", "gate"), ("accepted", "provider decisions")):
                d = ts.get(key)
                if isinstance(d, dict) and "delegated" in d:
                    stamp(d["delegated"], "%s/%s" % (name, tid))
                    n = len((ts.get("response") or {}).get("decisions", [])) if key == "accepted" else None
                    stood = " (verifier accepted)" if d.get("verifier") == "accept" else " (no verifier)" if key == "confirmed" else ""
                    findings.append({"kind": "delegated", "where": "%s/%s" % (name, tid),
                                     "text": "%s%s passed by delegation%s: %s" % (label, " (%d)" % n if n else "", stood, deleg_text(d["delegated"]))})
            staged = [(role, rec, "") for role, rec in (ts.get("stages") or {}).items()]
            staged += [(role, rec, " attempt %d" % i) for i, a in enumerate(ts.get("attempts", []), 1) for role, rec in (a.get("stages") or {}).items()]
            for role, rec, att in staged:
                resp = rec.get("response") or {}
                for f in resp.get("findings") or []:
                    findings.append({"kind": "stage-finding", "where": "%s/%s%s (%s, %s)" % (name, tid, att, role, rec.get("when", "?")),
                                     "text": "%s @ %s: %s — \u201c%s\u201d" % (f.get("kind"), f.get("where", ""), f.get("why", ""), f.get("quote", ""))})
                acc = rec.get("accepted")
                if isinstance(acc, dict) and "delegated" in acc:
                    stamp(acc["delegated"], "%s/%s %s" % (name, tid, role))
                    findings.append({"kind": "delegated", "where": "%s/%s %s" % (name, tid, role),
                                     "text": "%s findings (%d) accepted by delegation: %s" % (role, len(resp.get("findings") or []), deleg_text(acc["delegated"]))})
            for i, a in enumerate(ts.get("attempts", []), 1):
                if "delegated" in (a.get("retried") or {}):
                    stamp(a["retried"]["delegated"], "%s/%s attempt %d" % (name, tid, i))
                    findings.append({"kind": "delegated", "where": "%s/%s attempt %d" % (name, tid, i),
                                     "text": "retry after %s passed by delegation: %s" % (a.get("status"), deleg_text(a["retried"]["delegated"]))})
                # a verifier's reject outlives the attempt it stopped: the reviewer's ledger sees it, and sees it again if it recurs
                for f in ((a.get("review") or {}).get("findings") or []):
                    findings.append({"kind": "verifier-reject", "where": "%s/%s attempt %d: %s" % (name, tid, i, f.get("where", "")),
                                     "text": "%s: %s — record: \u201c%s\u201d — tree: \u201c%s\u201d" % (f.get("kind"), f.get("why"), f.get("record_quote"), f.get("tree_quote"))})
        # one reason string stamped across 3+ judgments: one judgment claiming to be many — the lie is the format's, and the format now has `delegate`
        for reason, wheres in sorted(stamps.items()):
            if len(wheres) >= 3:
                findings.append({"kind": "delegation-stamp", "where": ", ".join(wheres),
                                 "text": "the same delegated reason %r stamped on %d judgments — a repeated stamp is one judgment claiming to be many; "
                                         "declare it once (`chongdae delegate`) and reference it (--delegated D-xxxx), or write per-judgment reasons" % (reason, len(wheres))})
        for n in non_claims(state):
            findings.append({"kind": "non-claim", "where": name, "text": n})
        # a task left open when its run closed, or rejected and never retried: the cheap way past a rejection is to abandon the
        # task and open a new run — the record keeps it visible; this line makes someone look
        if state.get("status") == "complete":
            for tid, ts in state.get("tasks", {}).items():
                if ts.get("status") not in ("done", "skipped", "dropped"):
                    rej = ts.get("rejected")
                    findings.append({"kind": "left-open", "where": "%s/%s" % (name, tid),
                                     "text": ("rejected by %s (%s) and never retried" % (rej["by"], rej["why"]) if rej else "left open when the run closed")
                                             + " — `chongdae drop %s --why` if it will not be done, or a run that does it" % tid})
    print(json.dumps({"artifact-type": "dwitbuk/findings@1", "source": "chongdae", "findings": findings}, ensure_ascii=False, indent=1))
    return 0


def cmd_close(args):
    """A session run ends. Open tasks stay in the record as open; nothing is decided for them.
    A worktree run also merges back: commit the worktree, merge into main — clean merge + green recheck ends the run;
    a conflict or a red recheck leaves the branch for a merge run (`init --merge` in main). The worktree is removed
    only when the merge landed; otherwise it stays, and the record says why."""
    d = run_dir(args.target, getattr(args, "run", None))
    plan, state = (load(os.path.join(d, "plan.json")), load_state(d)) if d else ({}, {})
    wt = state.get("worktree")
    if plan.get("kind") != "session":
        # a plan/bootstrap run in a worktree ends by `run` (complete); `close` is then its way back to main
        if not (wt and state.get("status") == "complete"):
            raise SystemExit("no session run in progress" + (" — this %s run is %s; `chongdae run` completes it, then `close` merges its worktree back" % (plan.get("kind"), state.get("status")) if wt else ""))
        return merge_back(args.target, wt, os.path.basename(d))
    if state.get("status") != "running":
        raise SystemExit("no session run in progress")
    open_ = [tid for tid, ts in state["tasks"].items() if ts["status"] not in ("done", "skipped", "dropped")]
    state["status"] = "complete"
    state["open"] = open_
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "close (%d open)" % len(open_))
    dropped = [tid for tid, ts in state["tasks"].items() if ts["status"] == "dropped"]
    print("closed %s: %d task(s) done, %d open (%s)%s. non-claims: %s" % (os.path.basename(d), sum(ts["status"] == "done" for ts in state["tasks"].values()), len(open_), ", ".join(open_) or "-",
                                                                 ", %d dropped (%s)" % (len(dropped), ", ".join(dropped)) if dropped else "", non_claims(state) or "none"))
    if wt:
        return merge_back(args.target, wt, os.path.basename(d))
    return 0


def merge_back(wt_path, wt, run_name):
    wt_path = os.path.abspath(wt_path)   # every git call below runs in main: a relative path (`--target .` from inside the worktree) would name main
    """Commit the worktree and merge its branch into main. Exit 0: landed, worktree removed. Exit 2: a human or a
    merge run must finish it — the branch and worktree stay."""
    import subprocess
    main, branch = wt["main"], wt["branch"]

    def git(cwd, *a):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    if git(wt_path, "add", "-A").returncode:
        raise SystemExit("git add failed in the worktree")
    if git(wt_path, "diff", "--cached", "--quiet").returncode:   # something staged -> commit it
        done = git(wt_path, "commit", "-m", "%s: run results" % run_name)
        if done.returncode:
            raise SystemExit("commit failed in the worktree: %s" % (done.stderr or done.stdout).strip()[-300:])
    if git(main, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return stop("main tree is dirty — commit or stash it, then merge branch %s by hand (`git merge %s` + `chongdae init --merge` if recheck is needed)" % (branch, branch))
    done = git(main, "merge", "--no-ff", branch, "-m", "Merge %s (%s)" % (branch, run_name))
    if done.returncode:
        git(main, "merge", "--abort")
        return stop("merge of %s conflicts — resolve it in main (`git merge %s`, fix, commit), then `chongdae init --merge`; the worktree stays at %s" % (branch, branch, wt_path.replace(os.sep, "/")))
    failed = []
    for r in all_runs(main):
        st = load_state(r)
        if st.get("status") != "complete":
            continue
        for task in all_tasks(load(os.path.join(r, "plan.json")), st):
            ts = st["tasks"].get(task["id"], {})
            if ts.get("status") == "done" and task.get("checks"):
                failed += run_checks(main, [c for c in task["checks"] if not is_self_recheck(c)])   # a merge run's own `chongdae recheck` would recurse here
    if failed:
        return stop("merged, but recheck is red on main — fix the tree there (`chongdae init --merge` makes it a run); the worktree stays at %s" % wt_path.replace(os.sep, "/"),
                    *failed[:6])
    git(main, "worktree", "remove", "--force", wt_path)
    git(main, "branch", "-d", branch)
    # the run landed: pin the merge commit into its record (in main), so completed runs order by ancestry, and commit that judgment
    landed = (git(main, "rev-parse", "HEAD").stdout or "").strip()
    rec = os.path.join(main, RUNS, run_name, "state.json")
    if landed and os.path.exists(rec):
        st = load(rec)
        st["landed"] = {"at": now_utc(), "commit": landed}
        save(rec, st)
        commit_record(main, run_name, "landed as %s" % landed[:12])
    print("merged %s into main and removed the worktree — recheck green" % branch)
    return 0


def plan_problems(plan):
    """Shape of a plan the brain wrote. Content is the brain's and the human's; chongdae only refuses what it cannot run."""
    out = []
    if plan.get("artifact-type") != "chongdae/plan@1" or not plan.get("goal"):
        out.append("needs artifact-type chongdae/plan@1 and a goal")
    ids = [t.get("id") for t in plan.get("tasks", [])]
    if not ids or len(set(ids)) != len(ids):
        out.append("tasks need unique ids")
    for t in plan.get("tasks", []):
        if not t.get("role"):
            out.append("%s: no role" % t.get("id"))
        if not (t.get("path") or t.get("checks")):
            out.append("%s: needs `path` (an artifact to shape-check) or `checks` (commands that must exit 0) — otherwise nothing decides it is done" % t.get("id"))
        for n in t.get("needs", []):
            if n not in ids:
                out.append("%s: needs unknown task %s" % (t.get("id"), n))
        if t.get("tests") and not (isinstance(t["tests"], list) and all(isinstance(x, str) for x in t["tests"])):
            out.append("%s: `tests` must be a list of project-relative paths (the contract's own checks, protected from the build)" % t.get("id"))
        if t.get("gate") is not None and not (t["gate"] == "human" or isinstance(t["gate"], dict)):
            out.append("%s: `gate` is \"human\" or {\"human\": true, \"delegate\": \"after-verifier\"}" % t.get("id"))
        for when in ("before", "after"):
            if t.get(when) is not None and not (isinstance(t[when], list) and all(isinstance(x, str) and x for x in t[when])):
                out.append("%s: `%s` is a list of role names (people the plan hires around this task: [\"quibble\"], [\"newbie\"])" % (t.get("id"), when))
    st = plan.get("stages")
    if st is not None and not (isinstance(st, dict) and all(k in ("before", "after") and isinstance(v, list) for k, v in st.items())):
        out.append("`stages` is {\"before\": [roles], \"after\": [roles]} — the plan's defaults for tasks that say neither")
    return out


def stage_roles(plan, task, when):
    """The roles hired around a task: the task's own `before`/`after` list, else the plan's `stages` defaults. Not the
    verifier — that one is chongdae's own stage with a verdict; these answer with findings the person reads."""
    if task.get(when) is not None:
        return list(task[when])
    return list((plan.get("stages") or {}).get(when, []))


def dirty(target):
    """{path: content hash} of every file that differs from HEAD (tracked or untracked) under target, paths relative to target.
    None when there is no git — then nothing can be attributed, and the record says so."""
    import hashlib, subprocess
    try:
        done = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "."], cwd=target, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    if done.returncode:
        return None
    # porcelain paths are relative to the repository root; the record is relative to the target (a project can live in a subdirectory)
    prefix = subprocess.run(["git", "rev-parse", "--show-prefix"], cwd=target, capture_output=True, text=True, encoding="utf-8").stdout.strip().replace("\\", "/")
    out = {}
    for line in done.stdout.splitlines():
        path = line[3:].strip().replace("\\", "/") if len(line) > 3 else ""
        path = path[len(prefix):] if prefix and path.startswith(prefix) else path
        if path and not path.startswith((RUNS + "/", ".mangsang/", ".dwitbuk/", ".claude/")):   # records and machine-local state are nobody's work
            full = os.path.join(target, path)
            out[path] = hashlib.sha1(io.open(full, "rb").read()).hexdigest() if os.path.isfile(full) else "gone"
    return out


def touched_files(target, start=None):
    """What changed since the task started: dirty now and not identical at start. Without a start snapshot, the whole dirty set."""
    now = dirty(target)
    if now is None:
        return None
    start = start or {}
    return sorted(p for p, h in now.items() if start.get(p) != h)


def install_entry(entries, target):
    """The host keeps one install record per (scope, project). The one that applies to `target` is its own project-scope
    record, else the user-scope one, else — for a project that only enabled the plugin — the first; entries[0] was the first
    project that ever installed it, which loads a different copy once versions diverge."""
    want = os.path.realpath(target)
    for e in entries:
        if e.get("scope") == "project" and e.get("projectPath") and os.path.realpath(e["projectPath"]) == want:
            return e
    for e in entries:
        if e.get("scope") == "user":
            return e
    return entries[0] if entries else {}


def plugin_root(target, name):
    """Where plugin `name` lives on this machine: a local link in hunsu.local.json, else the host's installed plugins. Never a path in the plan."""
    links = load(os.path.join(target, "hunsu.local.json")).get("links", {})
    if name in links:
        root = links[name]
        return os.path.join(root, name) if os.path.isdir(os.path.join(root, name)) else root
    if name == "chongdae":
        return os.path.dirname(os.path.abspath(__file__))   # the one plugin this process knows the location of
    home = os.environ.get("HUNSU_CLAUDE_DIR") or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    for key, entries in load(os.path.join(home, "plugins", "installed_plugins.json")).get("plugins", {}).items():
        if key.split("@")[0] == name and entries:
            return install_entry(entries, target).get("installPath")
    raise SystemExit("plugin %r is not linked (hunsu.local.json) or installed here — a plan names plugins, never machine paths" % name)


def native_argv(target, provider):
    """A `native:` provider: the session dispatches the host's own subagent instead of a worker process. The prompt is the
    worker's, obtained with `--prompt-only`; the argv comes from the lock (`{"native": [argv]}`) or from the plugin's declared
    role (`native:plugin:role`). None when the provider is not native."""
    if isinstance(provider, dict) and isinstance(provider.get("native"), list):
        return list(provider["native"])
    if isinstance(provider, str) and provider.startswith("native:") and provider.count(":") == 2:
        _, plugin, role = provider.split(":")
        for m in (os.path.join(".claude-plugin", "plugin.json"), os.path.join(".codex-plugin", "plugin.json"), "plugin.json"):
            declared = (load(os.path.join(plugin_root(target, plugin), m)).get("roles") or {}).get(role)
            if declared:
                host = {"claude-code": "claude"}.get(os.environ.get("AGENT_HOST", "claude-code"), os.environ.get("AGENT_HOST", "claude"))
                return [str(a).replace("{host}", host) for a in declared]
        raise SystemExit("provider %r: plugin %s declares no role %r in its plugin.json `roles`" % (provider, plugin, role))
    return None


def resolve_argv(target, argv):
    """`{plugin:NAME}` -> that plugin's root on this machine. Plans stay portable; machines resolve."""
    out = []
    for a in argv:
        for m in set(re.findall(r"\{plugin:([\w.-]+)\}", a)):
            a = a.replace("{plugin:%s}" % m, plugin_root(target, m).replace(os.sep, "/"))
        out.append(a)
    return out


def run_checks(target, checks):
    """Every check is an argv run in the target; all must exit 0. Output tails come back for the stop message.
    `python`/`python3` in argv[0] resolves to whichever this machine has (macOS ships only `python3`) — plans stay portable."""
    import subprocess
    failed = []
    for argv in checks:
        argv = resolve_argv(target, argv)
        if argv and argv[0] in ("python", "python3") and not shutil.which(argv[0]):
            alt = next((c for c in ("python3", "python") if shutil.which(c)), None)
            argv = [alt or sys.executable] + argv[1:]
        done = subprocess.run(argv, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode:
            tail = (done.stdout + done.stderr).strip().split("\n")[-6:]
            failed.append("%s -> exit %d\n      %s" % (" ".join(argv), done.returncode, "\n      ".join(tail)))
    return failed


def pid_alive(pid):
    """Is the provider still running? A finished child of this very process is a zombie until reaped, and a zombie still
    answers kill(pid, 0) — so reap first (harmless when the pid is not our child), then probe."""
    try:
        pid = int(pid)
    except (ValueError, TypeError):
        return False
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)   # our child: (0, 0) while running, (pid, status) once it exited
        if done == pid:
            return False
    except (ChildProcessError, OSError, AttributeError):
        pass   # not our child (an earlier `run` started it) or no waitpid here: the probe below decides
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def checks_for_tests(tasks, task):
    """A task that writes the contract's tests has no check of its own: its output is the check. Whoever reads its request
    (a quibbler before it) sees the checks of the task that will run those tests — the build that protects the same files —
    instead of an empty list read as "nothing decides this"."""
    mine = set(task.get("tests") or [])
    if not mine or task.get("checks"):
        return []
    for other in tasks:
        if other.get("id") != task.get("id") and other.get("checks") and mine & set(other.get("tests") or []):
            return other["checks"]
    return []


def spawn(target, run, task, provider, plan, attempts=(), stage="build", extra=None):
    """Run a provider command with a request file; read its response file. The provider is argv with {request} and {response}.

    The request carries the contract: the task, the plan sections it closes, the checks that will decide it. Nothing else —
    the provider is a fresh process and must not need this session's context.

    The provider is detached (its own session, output to <tag>.provider.log) and its pid recorded in <tag>.pending.json
    BEFORE this call waits on it. A session that backgrounds `run` and exits kills `run` — but not the provider; the next
    `chongdae run` finds the pending record and resumes waiting (or consumes the response that landed meanwhile) instead
    of paying for the work twice. Returns (returncode, response, start_snapshot).
    """
    import subprocess
    import time
    tag = task["id"] + ("" if stage == "build" else "." + stage + (".%d" % (len(attempts) + 1) if attempts else ""))
    req_path = os.path.join(run, tag + ".request.json")
    res_path = os.path.join(run, tag + ".response.json")
    pend_path = os.path.join(run, tag + ".pending.json")
    log_path = os.path.join(run, tag + ".provider.log")
    pending = load(pend_path)
    proc = None
    native = native_argv(target, provider)
    if native and os.path.exists(res_path):   # the session wrote the subagent's answer: consume it like any provider's
        pending = pending or {"start": dirty(target)}
    elif not (pending and (os.path.exists(res_path) or pid_alive(pending.get("pid")))):
        sections = {}
        plan_doc = os.path.join(target, plan.get("from", ""))
        if plan.get("from") and os.path.exists(plan_doc):
            text = io.open(plan_doc, encoding="utf-8").read()
            for qid in task.get("closes", []):
                m = re.search(r"^## +%s\b.*?(?=^## |\Z)" % re.escape(qid), text, re.M | re.S)
                if m:
                    sections[qid] = m.group(0).strip()
        req = {"artifact-type": "chongdae/request@1", "stage": stage, "run": os.path.basename(run), "task": task["id"],
               "role": task["role"] if stage == "build" else ("verifier" if stage == "verify" else stage),
               "target": os.path.abspath(target).replace(os.sep, "/"), "goal": plan["goal"], "brief": task.get("brief", ""),
               "closes": task.get("closes", []), "contract": sections, "checks": task.get("checks", []) or checks_for_tests(all_tasks(plan, load_state(run)), task), "tests": task.get("tests", []),
               "response": res_path.replace(os.sep, "/")}
        if attempts:
            # A slice that spans calls: the next call is a fresh process. It resumes from the tree as the last call left it and from
            # these reports — not from anyone's memory. `touched` is what the tree already differs in.
            req["attempts"] = [{k: a.get(k) for k in ("status", "summary", "verified", "decisions", "non-claims", "retried", "review", "disputed-tests", "reopened") } for a in attempts]
            req["touched"] = touched_files(target)
        req.update(extra or {})
        save(req_path, req)
        if os.path.exists(res_path):
            os.remove(res_path)
        if native:
            # no process: the session runs the host's subagent with the worker's prompt and writes the answer where a worker would
            argv = resolve_argv(target, [a.replace("{request}", req_path).replace("{response}", res_path) for a in native]) + ["--prompt-only"]
            if argv and argv[0] in ("python", "python3") and not shutil.which(argv[0]):
                argv[0] = next((c for c in ("python3", "python") if shutil.which(c)), None) or sys.executable
            save(pend_path, {"native": argv, "start": dirty(target)})
            return DISPATCH, {"status": "dispatch", "prompt_argv": argv, "request": req_path, "response": res_path}, None
        argv = resolve_argv(target, [a.replace("{request}", req_path).replace("{response}", res_path) for a in (provider if isinstance(provider, list) else provider.split())])
        if argv and argv[0] in ("python", "python3") and not shutil.which(argv[0]):
            argv[0] = next((c for c in ("python3", "python") if shutil.which(c)), None) or sys.executable   # a plan written on one OS names the runtime the other lacks
        log = io.open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(argv, cwd=target, stdout=log, stderr=log, start_new_session=True)
        pending = {"pid": proc.pid, "argv": argv, "start": dirty(target), "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        save(pend_path, pending)
    # wait for the provider to END, not for its file to appear: a worker may write the response path more than once (a host's
    # raw last message first, its own whole answer after), and half an answer is not an answer
    if native and not os.path.exists(res_path):   # asked again before the session answered: the same instruction
        return DISPATCH, {"status": "dispatch", "prompt_argv": pending.get("native"), "request": req_path, "response": res_path}, None
    global _CALL_DEADLINE
    if _CALL_DEADLINE is None:
        _CALL_DEADLINE = time.time() + WAIT_BUDGET
    deadline = _CALL_DEADLINE
    while (proc.poll() is None if proc is not None else pid_alive(pending.get("pid"))):
        if time.time() > deadline:
            # still working: hand back to the session instead of outliving its tool call. The provider is detached and its pending
            # record stands; the next `run` resumes waiting for the same work. A session that backgrounds `run` to wait longer
            # ends up orphaning the provider — this is the loop that replaces that.
            since = pending.get("since") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return WAITING, {"status": "waiting", "pid": pending.get("pid") or proc.pid, "since": since, "log": log_path}, pending.get("start")
        time.sleep(2)   # our own child must be poll()ed — a finished child we never reap stays a zombie, and a zombie still answers kill(pid, 0)
    response = {}
    for _ in range(3):   # the provider may still be flushing the file when its pid vanishes
        try:
            response = load(res_path) if os.path.exists(res_path) else {}
            break
        except ValueError:
            time.sleep(1)
    if not isinstance(response, dict):   # a provider that wrote something other than an object wrote nothing
        response = {}
    code = 0 if response else 1
    if not response:
        tail = io.open(log_path, encoding="utf-8", errors="replace").read()[-600:] if os.path.exists(log_path) else ""
        response = {"status": "no-response", "summary": tail}
    start = pending.get("start")
    if os.path.exists(pend_path):
        os.remove(pend_path)
    return code, response, start


def cmd_status(args):
    d = run_dir(args.target)
    if not d:
        print("no run — `init --session --goal \"...\"` for a piece of work, `init --goal \"...\"` for the bootstrap plan, `init --plan FILE`, `init --merge` after a merge")
        return 0
    plan, state = load(os.path.join(d, "plan.json")), load_state(d)
    open_ = [t["id"] for t in all_tasks(plan, state) if state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped")]
    print("run %s (%s: %r) is %s — %d task(s), %d open: %s%s" % (os.path.basename(d), plan.get("kind", "?"), plan.get("goal", ""), state.get("status"),
                                                                 len(state["tasks"]), len(open_), ", ".join(open_) or "-",
                                                                 ". `run` advances it" if state.get("status") == "running" else ". Start a new run for new work"))
    return 0


SESSIONS = os.path.join(RUNS, "sessions")   # machine-local: session id -> where the host keeps that session's transcript (written by the SessionStart hook)


def session_model(target, session_id):
    """The model behind a session, from the host's own transcript. The host tells its subprocesses the session id but not the
    model; the SessionStart hook records where the transcript is, and the transcript names the model on every assistant line.
    (None, why) when it cannot be known — a session run with persistence off leaves no transcript."""
    rec = load(os.path.join(target, SESSIONS, session_id + ".json")) if session_id else {}
    path = rec.get("transcript")
    if not path:
        return None, "no session record (the SessionStart hook did not run for this session)"
    if not os.path.exists(path):
        return None, "no transcript on this host (session not persisted)"
    model = None
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"model"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "assistant":
                model = (d.get("message") or {}).get("model") or model
    return (model, None) if model else (None, "transcript has no assistant line yet")


def codex_session_model(thread_id):
    """Codex tells its subprocesses the thread id (CODEX_THREAD_ID), not the model; the rollout it keeps for that thread
    (~/.codex/sessions/**/rollout-*-<thread id>.jsonl) names the model on every turn_context line."""
    home = os.environ.get("HUNSU_CODEX_DIR") or os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    for dirpath, _, files in os.walk(os.path.join(home, "sessions")):
        for f in files:
            if f.endswith(thread_id + ".jsonl"):
                with io.open(os.path.join(dirpath, f), encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        m = re.search(r'"turn_context".*?"model":\s*"([^"]+)"', line)
                        if m:
                            return m.group(1), None
                return None, "rollout has no turn_context yet"
    return None, "no rollout for this thread on this host"


def waiting_text(what, d):
    return ("%s: the provider is still working (pid %s, since %s; its output so far: %s) — `chongdae run` again keeps waiting for the same work; "
            "do not background `run` and do not end the session — the provider is this session's child and dies with it"
            % (what, d.get("pid"), d.get("since"), d.get("log")))


def dispatch_text(what, d):
    return ("session agent: dispatch %s to this host's own subagent — get the prompt with `%s`, give it to a FRESH subagent of this host "
            "(Claude Code: the Agent tool, general-purpose, with that prompt as its task; Codex: spawn_agent), write its final JSON answer VERBATIM to %s "
            "(no edits, no additions), then `chongdae run`. The request is %s."
            % (what, " ".join('"%s"' % a if " " in a else a for a in d.get("prompt_argv") or []), d.get("response"), d.get("request")))


def plugin_versions(target, argv=()):
    """The versions a call ran with — to replay it, the skills and prompts must be those of the same versions. `used`: each
    plugin the provider's argv names, as installed here now; `locked`: every plugin the environment lock pins, with the
    content fingerprint the lock recorded for it (hunsu.lock.json), so a later reader can tell whether the installed copy
    was the locked one."""
    used = {}
    for m in sorted(set(re.findall(r"\{plugin:([\w.-]+)\}", " ".join(str(a) for a in argv)))):
        try:
            root = plugin_root(target, m)
        except SystemExit:
            used[m] = None
            continue
        for mf in (os.path.join(".claude-plugin", "plugin.json"), os.path.join(".codex-plugin", "plugin.json"), "plugin.json"):
            v = load(os.path.join(root, mf)).get("version")
            if v:
                used[m] = v
                break
    lock = load(os.path.join(target, "hunsu.lock.json")).get("plugins", {}) if target else {}
    locked = {name: "%s#%s" % (p.get("version"), p.get("fingerprint")) if p.get("fingerprint") else p.get("version") for name, p in sorted(lock.items())}
    return {k: v for k, v in (("used", used), ("locked", locked)) if v}


def performer(who, argv=None, response=None, target=None):
    """Who actually did the work, recorded like a commit's author line — a run without this cannot be replayed even loosely.
    A session provider: the host identifies itself in the env it gives its subprocesses (AI_AGENT is host_version_kind;
    CLAUDE_EFFORT when set; the session id), and the model comes from that session's transcript when the host kept one.
    A command provider: the un-resolved argv (portable), plus the worker's own account of its call (`worker` in the response:
    host, model, turns, cost, transcript) when the worker gave one."""
    if argv is not None:
        native = native_argv(target, who) if target is not None else None
        out = {"provider": "native" if native else "command", "argv": native or [str(a) for a in argv]}
        worker = (response or {}).get("worker") if isinstance(response, dict) else None
        if isinstance(worker, dict):
            out.update({k: v for k, v in worker.items() if v is not None})
        if target is not None:
            versions = plugin_versions(target, out["argv"])
            if versions:
                out["versions"] = versions
        if native:
            out["relayed_by"] = performer("session", target=target)   # the session ran the subagent and wrote its answer: that much is on record
        return out
    # which host is this session's: the env carries every ancestor's markers (a Codex session started from a Claude Code
    # shell sees AI_AGENT too), so the products' own AGENT_HOST decides, else the host whose session marker is present
    host = os.environ.get("AGENT_HOST") or ("codex" if os.environ.get("CODEX_THREAD_ID") else "claude-code")
    out = {"provider": "session", "host": host}
    if host == "codex":
        if os.environ.get("CODEX_VERSION"):
            out["agent"] = "codex_" + os.environ["CODEX_VERSION"]
        if os.environ.get("CODEX_THREAD_ID"):
            out["session"] = os.environ["CODEX_THREAD_ID"]
            model, why = codex_session_model(out["session"])
        else:
            model, why = None, "no CODEX_THREAD_ID in the environment"
    else:
        for key, name in (("AI_AGENT", "agent"), ("CLAUDE_EFFORT", "effort"), ("CLAUDE_CODE_SESSION_ID", "session")):
            if os.environ.get(key):
                out[name] = os.environ[key]
        model, why = session_model(target, out.get("session")) if target is not None else (None, "no target")
    if model:
        out["model"] = model
    else:
        out["model-unknown"] = why
    if target is not None:
        versions = plugin_versions(target)
        if versions:
            out["versions"] = versions
    return out


def cmd_run(args):
    global _CALL_DEADLINE
    if not getattr(args, "continuing", False):
        _CALL_DEADLINE = None   # a fresh budget for this call — an automatic resend continues the same call, and its budget
    target = args.target
    d = run_dir(target)
    if not d:
        raise SystemExit("no run — `chongdae init --goal ...`")
    plan, state = load(os.path.join(d, "plan.json")), load_state(d)
    if state["status"] != "running":
        print("run %s is %s" % (os.path.basename(d), state["status"]))
        return 0
    prov = providers(target, plan)
    who_am_i = me(target)
    for task in all_tasks(plan, state):
        ts = state["tasks"][task["id"]]
        if ts["status"] in ("done", "skipped", "dropped"):
            continue
        if any(state["tasks"][n]["status"] != "done" for n in task.get("needs", [])):
            continue
        if ts.get("claimed_by") and ts["claimed_by"] != who_am_i:
            print("  %s is claimed by %s — not this machine's to advance" % (task["id"], ts["claimed_by"]))
            continue
        who = prov.get(task["role"])
        if who is None:
            if task.get("optional"):
                ts["status"] = "skipped"
                ts["non-claims"] = ["no provider for role %r — %s not produced; nothing substituted" % (task["role"], task["produces"])]
                save_state(d, state)
                print("  skipped %s (role %s has no provider) — recorded as a non-claim" % (task["id"], task["role"]))
                continue
            return stop("role %r has no provider — declare one in hunsu.json `roles` (then lock) or in the plan's `providers`" % task["role"])
        # task paths are project-relative: artifacts belong to the project, .chongdae holds only how the run went
        path = os.path.join(target, task["path"]) if task.get("path") else None
        if "start" not in ts:
            ts["start"] = dirty(target)   # what the tree already differed in: `touched` is measured from here, not from HEAD
            save_state(d, state)
        if ts["status"] == "todo":
            # People hired before the work: each answers with findings about the contract; a finding is a plan question, so the
            # task waits until a human accepts them (having written the answers into the plan) — the hands do not move on an open question.
            code = run_stage(target, d, task, ts, state, plan, prov, "before", {"tests": task.get("tests", [])})
            if code is not None:
                return code
        if ts["status"] == "todo" and who != "session":
            # A command provider: a fresh process gets a request file and must leave a response file. chongdae reads only the response.
            if ts.get("rebaseline"):
                # the tests this build disputed were rewritten by the task that owns them; they are the contract again
                now = dirty(target) or {}
                for f in ts["rebaseline"]:
                    if f in now:
                        ts.setdefault("start", {})[f] = now[f]
                    else:
                        (ts.get("start") or {}).pop(f, None)
                ts.setdefault("rebaselined", []).append({"tests": ts.pop("rebaseline"), "at": now_utc()})
                save_state(d, state)
            if not ts.get("response"):
                code, response, before = spawn(target, d, task, who, plan, ts.get("attempts", []),
                                               extra={"amending": ts["amending"]} if ts.get("amending") else None)
                if code == DISPATCH:
                    return stop(dispatch_text(task["id"], response))
                if code == WAITING:
                    return stop(waiting_text(task["id"], response))
                ts["response"] = response
                ts["touched_by_provider"] = touched_files(target, before)
                ts["performed_by"] = performer(who, argv=who if isinstance(who, list) else [who], response=response, target=target)   # the un-resolved argv: portable, names host/model without machine paths
                if native_argv(target, who):
                    ts.setdefault("non-claims", []).append("%s: the answer was written by the session on a native subagent's behalf; chongdae did not observe the subagent" % task["id"])
                save_state(d, state)
            response = ts["response"]
            again = "then `chongdae retry %s --by NAME | --delegated WHY` sends it out again with this attempt attached" % task["id"]
            if response.get("status") == "blocked" and response.get("disputed-tests"):
                setattr(args, "continuing", True)
                if route_dispute(target, d, state, plan, task, response["disputed-tests"]):
                    return cmd_run(args)
            if response.get("status") == "blocked":
                return stop("%s: the provider stopped — it needs a decision the contract does not give: %s — write it into the plan, %s" % (task["id"], response.get("summary", ""), again),
                            *response.get("non-claims", []))
            refused = [n for n in response.get("non-claims", []) if str(n).startswith("checks-ran:")]
            if response.get("status") == "failed" and refused and (setattr(args, "continuing", True) or True) and auto_resend(target, d, state, task["id"], "the report named a check the session did not run: " + refused[0][:160]):
                return cmd_run(args)
            if response.get("status") != "done":
                return stop("%s: provider %r did not finish (%s) — see %s; fix what stopped it (or nothing, if it ran out of budget), %s"
                            % (task["id"], who, response.get("status"), os.path.join(d, task["id"] + ".response.json"), again))
            if response.get("decisions") and not ts.get("accepted"):
                # The provider settled something the contract did not. That is a plan change: a human writes it into the plan and accepts, or rejects the work.
                return stop("%s: the provider made %d decision(s) the contract did not — write each into the plan (or reject the work and reset the tree), "
                            "then `chongdae accept %s --by NAME | --delegated WHY` and re-run" % (task["id"], len(response["decisions"]), task["id"]),
                            *("%s: chose %r (alternatives: %s)" % (x["what"], x["chosen"], ", ".join(x["alternatives"]) or "-") for x in response["decisions"]))
            if not ts.get("reported"):
                ts["non-claims"] = ts.get("non-claims", []) + ["(provider) %s" % n for n in response.get("non-claims", [])]
                ts["reported"] = True
                save_state(d, state)
        if ts["status"] == "todo":
            if task.get("checks"):
                # Code tasks: done means the checks pass. Not started and failing look the same — both are "not yet".
                failed = run_checks(target, task["checks"])
                if failed:
                    return stop("session agent: %s — make these checks pass, then `chongdae run`" % task["id"], task.get("brief", ""), *failed)
                touched = touched_files(target, ts.get("start")) or []
                broken = [t for t in task.get("tests", []) if t in touched]
                if broken:
                    # The contract owns its checks. A build that edits them decided its own verdict — that is a reject, whoever built.
                    ts["rejected"] = {"by": "contract", "why": "changed protected tests: %s" % ", ".join(broken)}
                    save_state(d, state)
                    return stop("%s: the build changed the contract's tests (%s) — restore them (the contract decides, not the builder), "
                                "then `chongdae retry %s --by NAME | --delegated WHY`" % (task["id"], ", ".join(broken), task["id"]))
                if prov.get("verifier") and not ts.get("review"):
                    # Independent eyes before the gate: not the hands, and their verdict goes here, not back to the builder.
                    built = {k: (ts.get("response") or {}).get(k) for k in ("summary", "verified", "non-claims")} if ts.get("response") else None
                    by_provider = ts.get("touched_by_provider")
                    extra = {"touched": by_provider if by_provider is not None else touched, "tests": task.get("tests", []), "built": built}
                    if by_provider is not None:
                        extra["touched_since"] = sorted(set(touched) - set(by_provider))   # changed after the builder answered: a person's plan edits, say — not the builder's
                    code, review, _ = spawn(target, d, task, prov["verifier"], plan, ts.get("attempts", []), stage="verify", extra=extra)
                    if code == DISPATCH:
                        return stop(dispatch_text(task["id"] + " (verify)", review))
                    if code == WAITING:
                        return stop(waiting_text(task["id"] + " (verify)", review))
                    ts["review"] = review
                    ts["verified_by"] = performer(prov["verifier"], argv=prov["verifier"] if isinstance(prov["verifier"], list) else [prov["verifier"]], response=review, target=target)
                    if native_argv(target, prov["verifier"]):
                        ts.setdefault("non-claims", []).append("%s: the verdict was written by the session on a native subagent's behalf; chongdae did not observe the subagent" % task["id"])
                    save_state(d, state)
                if prov.get("verifier"):
                    review = ts["review"]
                    if review.get("verdict") not in ("accept", "reject"):
                        ts.pop("review", None)
                        save_state(d, state)
                        return stop("%s: the verifier did not answer (%s) — fix the verifier or its provider argv, then `chongdae run`" % (task["id"], review.get("summary") or review.get("status") or "no verdict"))
                    if review["verdict"] == "reject":
                        ts["rejected"] = {"by": "verifier", "why": "%d finding(s)" % len(review.get("findings", []))}
                        save_state(d, state)
                        if (setattr(args, "continuing", True) or True) and auto_resend(target, d, state, task["id"], "the verifier rejected: %d finding(s)" % len(review.get("findings", []))):
                            return cmd_run(args)
                        return stop("%s: the verifier rejected the slice — fix the tree (or the contract, and re-plan), then `chongdae retry %s --by NAME | --delegated WHY`" % (task["id"], task["id"]),
                                    *("%s @ %s: %s — record: \u201c%s\u201d — tree: \u201c%s\u201d" % (f.get("kind"), f.get("where"), f.get("why"), f.get("record_quote"), f.get("tree_quote"))
                                      for f in review.get("findings", [])))
            elif not task.get("path"):
                pass   # a session task with no check: the agent's word, already recorded as a non-claim when it was added
            else:
                if not (path and os.path.exists(path)):
                    return stop("session agent: produce %s at %s, then `chongdae run`" % (task["produces"], path), task["brief"])
                problems = CHECKS[task["produces"]](path, state)
                if problems:
                    return stop("%s does not pass its shape check — fix it, then `chongdae run`" % task["produces"], *problems)
            # People hired after the work: they see the result (touched files, the builder's report) and answer with findings for
            # the record — not a verdict; the gate stands as declared, and the reviewer's report carries what they found.
            built = {k: (ts.get("response") or {}).get(k) for k in ("summary", "verified", "non-claims")} if ts.get("response") else None
            code = run_stage(target, d, task, ts, state, plan, prov, "after", {"touched": touched_files(target, ts.get("start")) or [], "tests": task.get("tests", []), "built": built})
            if code is not None:
                return code
            ts["status"] = "produced"
            ts["checks"] = task.get("checks", [])
            ts["touched"] = touched_files(target, ts.get("start"))   # what this task changed: the reviewer joins runs to files with it
            if "performed_by" not in ts:
                ts["performed_by"] = performer(who, target=target)   # the session did the work: record which host/model/session, like a commit author
            save_state(d, state)
        if ts["status"] == "produced" and gate_of(task).get("human"):
            return stop("human: review %s (%s) — then `chongdae confirm %s --by <name>` or `--delegated \"<why the human handed this off>\"`"
                        % (task.get("produces", "task %s (checks passed: %s)" % (task["id"], "; ".join(" ".join(c) for c in task.get("checks", [])))), path or task.get("closes", ""), task["id"]))
        ts["status"] = "done"
        save_state(d, state)
        print("  done %s" % task["id"])
    if plan.get("kind") == "session":
        open_ = [t["id"] for t in all_tasks(plan, state) if state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped")]
        print("session run %s: %d task(s), %d open (%s) — `chongdae add` for the next piece, `chongdae close` at the end" % (os.path.basename(d), len(state["tasks"]), len(open_), ", ".join(open_) or "-"))
        return 0
    if any(state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped") for t in all_tasks(plan, state)):
        return stop("nothing this machine can advance — the open tasks are claimed elsewhere (or blocked on them); pull and `chongdae run` again")
    state["status"] = "complete"
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "complete")
    print("run %s complete. non-claims: %s" % (os.path.basename(d), non_claims(state) or "none"))
    return 0


DELEGATION_REF = re.compile(r"D-[0-9a-f]+\Z")


def delegation_record(run_d, reason, kind):
    """What `--delegated REASON` writes into the judgment. A reason of the form D-xxxx is a reference to a delegation
    declared once with `chongdae delegate` — resolved here (it must exist in this run and cover this judgment kind)
    and recorded as {\"ref\": id}: one judgment, pointed at, instead of its words repeated. Any other reason is this
    judgment's own words, recorded as given."""
    if not DELEGATION_REF.match(reason):
        return {"delegated": reason}
    path = os.path.join(run_d, "delegations", reason + ".json")
    if not os.path.exists(path):
        raise SystemExit("no delegation %s in %s — declare it first: `chongdae delegate --run %s --scope %s --why \"...\" --by NAME`"
                         % (reason, os.path.basename(run_d), os.path.basename(run_d), kind))
    rec = load(path)
    scope = rec.get("scope") or []
    if kind not in scope:
        raise SystemExit("delegation %s does not cover %r (its scope: %s) — declare one that does, or a person judges this one"
                         % (reason, kind, ", ".join(scope) or "-"))
    return {"delegated": {"ref": reason}}


def cmd_delegate(args):
    """An orchestrator's batch pre-approval, declared once as its own judgment (one record, one notary commit) instead of
    the same reason string pasted into dozens of judgments — one judgment masquerading as many. Later judgments reference
    it: `--delegated D-xxxx`."""
    import secrets
    d = run_dir(args.target, args.run)
    if not d:
        raise SystemExit("no run — a delegation belongs to a run")
    scope = [s.strip() for s in args.scope.split(",") if s.strip()]
    if not scope:
        raise SystemExit("--scope needs judgment kinds, e.g. confirm,accept,retry")
    did = "D-" + secrets.token_hex(4)
    save(os.path.join(d, "delegations", did + ".json"),
         {"artifact-type": "chongdae/delegation@1", "id": did, "scope": scope, "why": args.why, "by": args.by, "at": now_utc()})
    commit_record(args.target, os.path.basename(d), "delegate %s (%s)" % (did, ",".join(scope)))
    print(did)
    return 0


def contract_fingerprint(target, d, tid):
    """The text a `before` role answered: the task's brief and checks and the plan sections it closes, hashed."""
    import hashlib
    plan = load(os.path.join(d, "plan.json")); state = load_state(d)
    task = next((t for t in all_tasks(plan, state) if t["id"] == tid), {})
    text = json.dumps({"brief": task.get("brief"), "checks": task.get("checks"), "tests": task.get("tests")}, sort_keys=True)
    doc = os.path.join(target, plan.get("from", ""))
    if plan.get("from") and os.path.exists(doc):
        body = io.open(doc, encoding="utf-8").read()
        for qid in task.get("closes", []):
            m = re.search(r"^## +%s\b.*?(?=^## |\Z)" % re.escape(qid), body, re.M | re.S)
            text += "\n" + (m.group(0).strip() if m else "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def run_stage(target, d, task, ts, state, plan, prov, when, extra):
    """Run the roles hired `before` or `after` a task that have not answered yet. Returns a stop's exit code when the task
    must wait (a missing answer, unaccepted `before` findings), else None. Each answer is kept under `stages[role]` with who
    gave it; a role with no provider is a non-claim, never a substitute."""
    for role in stage_roles(plan, task, when):
        if role in (ts.get("unstaged") or {}):
            continue   # taken off this task, with the reason, by `unstage`: not a substitute answer — a non-claim
        rec = ts.setdefault("stages", {}).get(role)
        if rec and rec.get("response"):
            if when == "before" and rec["response"].get("findings") and not rec.get("accepted"):
                return stage_wait_text(task["id"], role, rec["response"])
            continue
        if rec and rec.get("skipped"):
            continue
        provider = prov.get(role)
        if provider is None:
            ts.setdefault("non-claims", []).append("%s: no provider for role %r (%s) — nobody %s; nothing substituted" % (task["id"], role, when, "quarrelled with the contract" if when == "before" else "looked at the result"))
            ts.setdefault("stages", {})[role] = {"skipped": "no provider"}
            save_state(d, state)
            continue
        code, response, _ = spawn(target, d, task, provider, plan, ts.get("attempts", []), stage=role, extra=extra)
        if code == DISPATCH:
            return stop(dispatch_text("%s (%s)" % (task["id"], role), response))
        if code == WAITING:
            return stop(waiting_text("%s (%s)" % (task["id"], role), response))
        by = performer(provider, argv=provider if isinstance(provider, list) else [provider], response=response, target=target)
        if response.get("status") != "done":
            # not an answer: kept as what happened (the reviewer sees it), but the role is asked again on the next `run`
            ts.setdefault("stages", {}).setdefault(role, {}).setdefault("failed", []).append({"response": response, "by": by, "when": when})
            save_state(d, state)
            return stop("%s: %s (%s) did not finish (%s: %s) — fix the provider or its argv, then `chongdae run` asks again; or take the role off this task: `chongdae unstage %s %s --why WHY`"
                        % (task["id"], role, when, response.get("status"), "; ".join(response.get("non-claims") or []) or response.get("summary", ""), task["id"], role))
        rec = {**ts.setdefault("stages", {}).get(role, {}), "response": response, "by": by, "when": when}
        if when == "before":
            rec["contract-fingerprint"] = contract_fingerprint(target, d, task["id"])   # what this answer was about: a retry re-hires only when it changed
        if native_argv(target, provider):
            ts.setdefault("non-claims", []).append("%s: %s's answer was written by the session on a native subagent's behalf; chongdae did not observe the subagent" % (task["id"], role))
        ts["stages"][role] = rec
        save_state(d, state)
        if when == "before" and response.get("findings"):
            return stage_wait_text(task["id"], role, response)
        print("  %s %s: %d finding(s)%s" % (role, task["id"], len(response.get("findings") or []), " — in the record" if when == "after" else ""))
    return None


def stage_wait_text(tid, role, response):
    lines = ["%s: %s found %d thing(s) the contract leaves open — decide each in the plan (or dismiss it there), then `chongdae accept %s --by NAME | --delegated WHY`"
             % (tid, role, len(response.get("findings") or []), tid)]
    for f in response.get("findings") or []:
        lines.append("%s @ %s: %s — \u201c%s\u201d" % (f.get("kind"), f.get("where", ""), f.get("why", ""), f.get("quote", "")))
    return stop(*lines)


def cmd_accept(args):
    """A human accepts the decisions a provider made beyond the contract (after writing them into the plan), or rejects by resetting the tree."""
    d = run_dir(args.target)
    state = load_state(d)
    ts = state["tasks"].get(args.task, {})
    # a `before` role's findings wait first (they precede the work); then the provider's decisions
    pending = [(role, rec) for role, rec in (ts.get("stages") or {}).items()
               if rec.get("when") == "before" and (rec.get("response") or {}).get("findings") and not rec.get("accepted")]
    if not pending and not (ts.get("response") or {}).get("decisions"):
        raise SystemExit("%s has no provider decisions or stage findings to accept" % args.task)
    if not (args.by or args.delegated):
        raise SystemExit("say who accepted (--by) or why the human delegated it (--delegated)")
    who = {**({"by": args.by} if args.by else delegation_record(d, args.delegated, "accept")), "at": now_utc()}
    if pending:
        role, rec = pending[0]
        rec["accepted"] = who
        save_state(d, state)
        commit_record(args.target, os.path.basename(d), "accept %s findings on %s (%s)" % (role, args.task, "by " + args.by if args.by else "delegated"))
        print("accepted %d finding(s) from %s on %s — the plan must now decide each; the work waits on nothing else from %s" % (len(rec["response"]["findings"]), role, args.task, role))
        return 0
    ts["accepted"] = who
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "accept decisions on %s (%s)" % (args.task, "by " + args.by if args.by else "delegated"))
    print("accepted %d decision(s) on %s — they are now the contract's; make sure the plan says so" % (len(ts["response"]["decisions"]), args.task))
    return 0


def gate_of(task):
    """`gate: "human"` or `gate: {"human": true, "delegate": "after-verifier"}` -> the dict form."""
    g = task.get("gate")
    return g if isinstance(g, dict) else ({"human": True} if g == "human" else {})


def cmd_retry(args):
    """A human sends a stopped task out again. The stopped attempt (and its review) stays in the record; the next call receives it."""
    d = run_dir(args.target)
    state = load_state(d)
    ts = state["tasks"].get(args.task, {})
    stopped = (ts.get("response") or {}).get("status") not in (None, "done") or ts.get("rejected")
    if ts.get("status") != "todo" or not stopped:
        raise SystemExit("%s is not stopped on a provider response or a rejection (status %s, response %s)" % (args.task, ts.get("status"), (ts.get("response") or {}).get("status")))
    if not (args.by or args.delegated):
        raise SystemExit("say who sent it again (--by) or why the human delegated it (--delegated)")
    n = resend(args.target, d, state, args.task, {"by": args.by} if args.by else delegation_record(d, args.delegated, "retry"))
    print("retry %s: attempt %d kept in the record; `chongdae run` sends the task out again with it attached" % (args.task, n))
    return 0


AUTO_RESENDS = 2   # per task: a verifier's reject or a refused report goes back to the hands this many times before a person is asked


def resend(target, d, state, task_id, retried, message=None):
    """Send a stopped task out again, keeping the stopped attempt (its response, review, stages) in the record under its
    number — the next call receives it. `retried` says who sent it: a person (`by`), a delegation, or chongdae itself."""
    ts = state["tasks"][task_id]
    attempt = {**(ts.pop("response", None) or {"status": "session"}), "retried": {**retried, "at": now_utc()}}
    for key in ("review", "rejected"):
        if key in ts:
            attempt[key] = ts.pop(key)
    if "stages" in ts:
        # a `before` role answered a contract; if that contract's text is what it was, the answer stands and the role is not
        # hired again (a retry for a report-format refusal cost a ten-minute quibble round each time). `after` roles answer
        # the result, which the retry will redo: they go with the attempt.
        keep, gone = {}, {}
        for role, rec in ts["stages"].items():
            if rec.get("when") == "before" and rec.get("contract-fingerprint") and rec["contract-fingerprint"] == contract_fingerprint(target, d, task_id):
                keep[role] = rec
            else:
                gone[role] = rec
        if gone:
            attempt["stages"] = gone
        if keep:
            ts["stages"] = keep
        else:
            ts.pop("stages")
    ts.setdefault("attempts", []).append(attempt)
    ts.pop("reported", None)
    n = len(ts["attempts"])
    # the attempt's files move aside under their number: the next `run` must find no response (a native provider's is written
    # by the session and would otherwise be read again as the new answer) and the record keeps what this attempt said
    for kind in ("response", "request", "pending", "response.transcript"):   # the build stage's files (verify files are numbered by spawn already)
        ext = "jsonl" if kind.endswith("transcript") else "json"
        src = os.path.join(d, "%s.%s.%s" % (task_id, kind, ext))
        if os.path.exists(src):
            os.replace(src, os.path.join(d, "%s.%s.%d.%s" % (task_id, kind, n, ext)))
    save_state(d, state)
    commit_record(target, os.path.basename(d), message or "retry %s (attempt %d kept)" % (task_id, n))
    return n


def route_dispute(target, d, state, plan, task, disputed):
    """The builder says some of the contract's tests contradict the contract. Tests are not the builder's to change and not a
    person's to fix by hand between attempts: the task that wrote them is reopened with the dispute (`amending`), and the
    build waits, re-baselines those tests once they are rewritten, and goes out again. Bounded like any automatic resend.
    Returns True when routed; False leaves the stop to a person."""
    files = sorted({str(x.get("test", "")).split("::")[0].split(" ")[0] for x in disputed if isinstance(x, dict)} & set(task.get("tests") or []))
    if not files:
        return False
    writer = next((t for t in all_tasks(plan, state) if t.get("id") != task["id"] and set(t.get("tests") or []) & set(files)
                   and state["tasks"].get(t["id"], {}).get("status") == "done"), None)
    bts = state["tasks"][task["id"]]
    routed = sum(1 for a in bts.get("attempts", []) if str((a.get("retried") or {}).get("auto", "")).startswith("tests disputed"))
    if not writer or routed >= AUTO_RESENDS:
        return False
    wts = state["tasks"][writer["id"]]
    attempt = {**(wts.pop("response", None) or {}), "reopened": {"by": "chongdae", "auto": "tests disputed by %s" % task["id"], "at": now_utc()},
               "disputed-tests": disputed}
    wts.setdefault("attempts", []).append(attempt)
    n = len(wts["attempts"])
    for kind in ("response", "request", "pending", "response.transcript"):
        ext = "jsonl" if kind.endswith("transcript") else "json"
        src = os.path.join(d, "%s.%s.%s" % (writer["id"], kind, ext))
        if os.path.exists(src):
            os.replace(src, os.path.join(d, "%s.%s.%d.%s" % (writer["id"], kind, n, ext)))
    wts["status"] = "todo"
    wts["amending"] = disputed
    wts.pop("reported", None)
    bts["rebaseline"] = files
    resend(target, d, state, task["id"], {"by": "chongdae", "auto": "tests disputed; %s reopened to amend %s" % (writer["id"], ", ".join(files))},
           "dispute %s: %s reopened to amend %s" % (task["id"], writer["id"], ", ".join(files)))
    print("  %s disputed %d test(s) in %s: %s reopened with the dispute; the build waits and goes out again after" % (task["id"], len(disputed), ", ".join(files), writer["id"]))
    return True


def auto_resend(target, d, state, task_id, why):
    """chongdae sends the work back itself — no person in between — when the stop is one the hands can answer: a verifier's
    findings (the tree must change) or a report a validator refused (the answer must be told again). Bounded by AUTO_RESENDS
    per task; past it, the stop goes to a person as before. Returns True when it resent."""
    ts = state["tasks"][task_id]
    done = sum(1 for a in ts.get("attempts", []) if (a.get("retried") or {}).get("auto"))
    if done >= AUTO_RESENDS:
        return False
    n = resend(target, d, state, task_id, {"by": "chongdae", "auto": why}, "auto-resend %s: %s" % (task_id, why))
    print("  %s: sent back to the provider automatically (%s; attempt %d kept, %d of %d automatic)" % (task_id, why, n, done + 1, AUTO_RESENDS))
    return True


def cmd_confirm(args):
    d = run_dir(args.target)
    state = load_state(d)
    ts = state["tasks"].get(args.task)
    if not ts or ts["status"] != "produced":
        raise SystemExit("%s is not waiting for confirmation (status: %s)" % (args.task, ts["status"] if ts else "unknown"))
    if not (args.by or args.delegated):
        raise SystemExit("say who confirmed (--by) or why the human delegated it (--delegated)")
    plan = load(os.path.join(d, "plan.json"))
    task = next((t for t in plan.get("tasks", []) if t.get("id") == args.task), {})
    verdict = (ts.get("review") or {}).get("verdict")
    if args.delegated and gate_of(task).get("delegate") == "after-verifier" and verdict != "accept":
        raise SystemExit("%s: this gate delegates only after a verifier accepts (verdict: %s) — a person must read it, or the plan must say otherwise" % (args.task, verdict or "none"))
    # Delegation is recorded with what stood in for the reader: a verifier's accept, or nothing. The reviewer counts the two apart.
    ts["confirmed"] = {**({"by": args.by} if args.by else {**delegation_record(d, args.delegated, "confirm"), "verifier": verdict}), "at": now_utc()}
    ts["status"] = "done"
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "confirm %s (%s)" % (args.task, "by " + args.by if args.by else "delegated"))
    print("confirmed %s (%s)" % (args.task, "by " + args.by if args.by else "delegated: " + args.delegated))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="chongdae", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "status", "run", "confirm", "accept", "retry", "recheck", "add", "claim", "drop", "unstage", "close", "report", "delegate"):
        p = sub.add_parser(name)
        p.add_argument("--target", default=".")
        if name == "init":
            p.add_argument("--goal", default=None)
            p.add_argument("--plan", default=None, help="a plan the session agent wrote (chongdae/plan@1): a path, or `-` for stdin (no file to write before the run exists); without it, the bootstrap plan")
            p.add_argument("--merge", action="store_true", help="the merge plan: recheck every completed run (+ coherence when the lock declares that role)")
            p.add_argument("--session", action="store_true", help="a session run: tasks are added as the work goes")
            p.add_argument("--from", dest="from_doc", default=None, help="session run: the plan document (plan/PLAN.md) whose `## Q-…` sections tasks `--closes`; providers receive those sections as the contract")
            p.add_argument("--base", default=None, help="with --merge: the revision the other side's relations are compared from (default: the merge base of HEAD^1 and HEAD^2)")
            p.add_argument("--worktree", action="store_true", help="the run's container is physical: its own worktree and branch under .chongdae/wt/ (from HEAD, or from --base REV: two independent slices branch from the same base); `close` merges it back")
        if name == "close":
            p.add_argument("--run", default=None, help="the run to close (default: the one running, else the newest) — a completed worktree run is named here to merge it back")
        if name in ("confirm", "accept", "retry"):
            p.add_argument("task")
            p.add_argument("--by", default=None)
            p.add_argument("--delegated", default=None)
        if name == "report":
            p.add_argument("--since", default=None, help="the revision the last review covered; changes since it are checked against the runs' `touched`")
        if name == "delegate":
            p.add_argument("--run", default=None, help="the run this delegation belongs to (default: the one running, else the newest)")
            p.add_argument("--scope", required=True, help="comma-separated judgment kinds it covers, e.g. confirm,accept,retry")
            p.add_argument("--why", required=True, help="why these judgments are handed off — the one reason, written once")
            p.add_argument("--by", required=True, help="the person who declared the delegation")
        if name == "unstage":
            p.add_argument("task")
            p.add_argument("role", help="a role hired before or after the task (quibble, newbie, ...)")
            p.add_argument("--why", required=True)
            p.add_argument("--by", default=None)
        if name == "drop":
            p.add_argument("task")
            p.add_argument("--why", required=True, help="why this task will not be done (mis-specified, superseded, abandoned)")
            p.add_argument("--by", default=None, help="who decided (default: git user.name)")
        if name == "claim":
            p.add_argument("task")
            p.add_argument("--by", default=None, help="who takes it (default: git user.name); an empty string releases")
        if name == "add":
            p.add_argument("id")
            p.add_argument("--role", default="session", help="who does it: `session` (this agent, the default) or a role the lock declares a provider for (`implementer`: a fresh process builds it from the brief and checks)")
            p.add_argument("--brief", default=None)
            p.add_argument("--closes", nargs="*", default=None)
            p.add_argument("--check", action="append", default=None, help="a check argv (quoted); repeatable")
            p.add_argument("--tests", nargs="*", default=None, help="the contract's test files, protected from the build")
            p.add_argument("--gate", choices=["human"], default=None)
            p.add_argument("--before", nargs="*", default=None, help="roles to run before the work (their findings must be accepted first): --before quibble")
            p.add_argument("--after", nargs="*", default=None, help="roles to run after the checks pass, before the gate; their findings go to the record: --after newbie")
    args = ap.parse_args(argv)
    return {"init": cmd_init, "status": cmd_status, "run": cmd_run, "confirm": cmd_confirm, "recheck": cmd_recheck, "accept": cmd_accept, "retry": cmd_retry,
            "add": cmd_add, "claim": cmd_claim, "drop": cmd_drop, "unstage": cmd_unstage, "close": cmd_close, "report": cmd_report, "delegate": cmd_delegate}[args.cmd](args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
