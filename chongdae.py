"""chongdae — runs a plan: a DAG of roles that produce artifacts, with checks in code and human gates in between.

  init  --goal "..." | --plan FILE     start a run: the bootstrap plan (questions -> plan document -> modeler) or a plan the session agent wrote
  init  --merge [--base REV]            after merging branches: the merge plan — recheck (+ coherence when the lock declares that role) behind a human gate
  init  --session [--goal "..."]        a session run: no plan, tasks added as the work goes (`add`), closed when the session ends (`close`)
  init  ... --worktree                  the run gets its own worktree + branch under .chongdae/wt/ (the shared tree may have other workers); `close` commits and merges it back — a conflict or red recheck becomes a merge run
  add   <id> [--brief ..] [--closes Q..] [--check ARGV]... [--tests F]... [--requires CAP]... [--gate human] [--role R [--why ..]]   a task in the session run;
                                        the start snapshot is taken now. The lock says who does it (checks -> implementer, new tests -> nitpick, else the
                                        session; `<role>@<cap>` for a task that --requires cap); `--role session --why` takes one back, recorded.
                                        --tests: what a nitpick task writes, what a task with --check may not change — `add` says which
  claim <id> [--by NAME]                take a task (defaults to git user.name); `run` skips tasks claimed by someone else
  drop  <id> --why WHY [--by NAME]      a session task that will not be done: leaves the open set, stays in the record with the reason
  dispute <build> --tests F... --why WHY [--by NAME | --delegated WHY]   a build's protected tests contradict the contract: the task
                                        that wrote them is reopened to amend them (or a tests task is made); the build then takes the
                                        amended files as its contract. A provider's build disputes in its answer (`disputed-tests`)
  close [--target DIR] [--run ID]       end a session run (open tasks recorded as such): the lock's `reviewer` role runs and what it wrote goes into the
                                        close commit; a worktree run merges back — a completed plan run too
  report [--since REV]                  what this record says a reviewer should see, as `dwitbuk/findings@1` on stdout: changes no run
                                        claims (outside-run), runs that recorded no `touched` (unattributed), gates/decisions/retries passed
                                        by delegation, and every non-claim. chongdae knows its runs and git; a reviewer knows the type
  status [--target DIR]                 the run in progress (or the newest) and its open tasks; exit 0 always — for a skill's first look
  show  [--run ID | --since REV | --path FILE]   what happened, for a reader after the fact (read-only, plain text, nothing cut):
                                        a run's tasks in order — who did each, every attempt with its verdict and findings, the
                                        judgments, checks, touched files and times; `--since`: one line per run and the totals;
                                        `--path`: the tasks that touched a file, newest first
  run   [--target DIR]                  advance one step. Exit 2 = stopped for the session agent or a human; the last line says what to do
  confirm <task> [--by NAME | --delegated "why"] [--target DIR]   record the human's confirmation of a produced artifact
  delegate --scope confirm,accept,... --why "..." --by NAME [--run ID]   declare a batch pre-approval once, as its own judgment; later
                                        judgments reference it: `--delegated D-xxxx` (recorded as {ref}, not the words repeated)
  accept  <task> [--by NAME | --delegated WHY]   a human accepts decisions a provider made beyond the contract (after writing them into the plan)
  retry   <task> [--by NAME | --delegated WHY] [--requires CAP..]   a human sends a stopped task (blocked, failed, no response) out again; the next call
                                        gets the earlier attempts. --requires: the sandbox lacked CAP — the task says so now, and goes to `<role>@<cap>` if locked
  recheck [--target DIR]                after a merge: re-run every completed run's checks on this tree. exit 1 if any is red now

A plan may declare a `verifier` role (providers.verifier — a command; never the hands that built). After a task's checks pass and
before its gate, the verifier gets the contract, the touched files and the builder's report, and answers `dwitbuk/review@1`
(accept | reject + quoted findings). Reject is the failed path: `retry`. A task's `tests` are the contract's: a build that changes
them is rejected. A gate `{"human": true, "delegate": "after-verifier"}` refuses delegation until an accept.

chongdae has no brain. It does not write questions, plans or code. When a task's provider is `session`, it stops and asks the
session agent (the brain) to produce the artifact; then it checks the artifact's shape and stops again for the human.
Roles are names; who provides them comes from hunsu.lock.json `roles` (or the plan's own `providers`). A role with no
provider is skipped and recorded as a non-claim — never substituted. A role may hold capability alternates, `<role>@<cap>[+<cap>]`
(`implementer@loopback`: the same member on a host whose sandbox can bind a port): a task that `requires` capabilities goes to the
alternate covering them (smallest set), else to the plain role; the record says which key (`performed_by.as`).
The engine and the hooks anchor to the project — the nearest directory holding `.chongdae/` — not to the shell's directory.
Artifacts a task produces live in the project (task `path` is project-relative). `.chongdae/` holds only how a run went:
`plan.json` (the intent), `state.json` (status), `tasks/<id>.json` (one file per task, so two people's work on one run merges),
`asked/` and `contract/` (what each provider was asked) — the record; and under `local/`, ignored, the work this machine
needed while the run went (requests as sent, responses, sessions, pending pids, logs, each task's private overlay).
The run is the agent's container: the plugin's PreToolUse hook refuses Edit/Write in a project with no run in progress.
"""
import argparse
import glob
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


# ---------------------------------------------------------------- plans

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


# ---------------------------------------------------------------- the record and the work: what a run writes, and where

def load(path):
    if not os.path.exists(path):
        return {}
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(path, data):
    if isinstance(data, dict) and str(data.get("artifact-type", "")).startswith("chongdae/"):
        # every record says which chongdae wrote it — a version, and `+g<sha>[-dirty]` when a working source did
        data = {"artifact-type": data["artifact-type"], "written_by": engine(), **{k: v for k, v in data.items() if k not in ("artifact-type", "written_by")}}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# A run's directory is two things, apart: the record — what a judgment wrote, committed, read by anyone — and the work —
# what this machine needed while the run went (the request as sent, the response as written, the worker's whole session,
# the pending pid, the log, the command lines, the flags the engine keeps between two `run` calls). The work lives under
# <run>/local/ (git-ignored, one line); the record is the run's root: plan.json, state.json, tasks/, asked/, contract/,
# delegations/. A task's working state is its record plus this machine's overlay (local/tasks/<id>.json): the keys below,
# at any depth, are the overlay's — the record never carries them.
LOCAL = "local"


PRIVATE_KEYS = ("session", "transcript", "kept-locally", "start", "start-head",   # the host session behind an author line; the snapshot a task measures from, and the commit it stood on
                "commands", "read",                                 # a worker's command lines and what it read: the record keeps the summary (`trace`)
                "reported", "rebaseline")                           # flags the engine keeps between two `run` calls

def split_private(o):
    """(public, private): the record without PRIVATE_KEYS at any depth, and a mirror holding only them."""
    if isinstance(o, dict):
        pub, priv = {}, {}
        for k, v in o.items():
            if k in PRIVATE_KEYS:
                priv[k] = v
                continue
            pub[k], q = split_private(v)
            if q:
                priv[k] = q
        return pub, priv
    if isinstance(o, list):
        pub, priv = [], {}
        for i, v in enumerate(o):
            p, q = split_private(v)
            pub.append(p)
            if q:
                priv[str(i)] = q
        return pub, ({"[]": priv} if priv else {})
    return o, {}


def merge_private(pub, priv):
    if isinstance(pub, list) and isinstance(priv, dict) and "[]" in priv:
        for i, q in priv["[]"].items():
            if int(i) < len(pub):
                pub[int(i)] = merge_private(pub[int(i)], q)
        return pub
    if isinstance(pub, dict) and isinstance(priv, dict):
        for k, q in priv.items():
            pub[k] = merge_private(pub[k], q) if k in pub and isinstance(q, dict) and k not in PRIVATE_KEYS else q
    return pub


def load_state(d):
    """The run's state: status from state.json, tasks from tasks/<id>.json (older runs kept tasks inside state.json — read as is),
    each merged with its machine-local part (local/tasks/<id>.json) when this machine has one."""
    state = load(os.path.join(d, "state.json"))
    tasks = state.get("tasks") or {}
    folder = os.path.join(d, "tasks")
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json"):
                tasks[name[:-5]] = merge_private(load(os.path.join(folder, name)), load(os.path.join(d, LOCAL, "tasks", name)))
    state["tasks"] = tasks
    state.setdefault("non-claims", [])
    return state


def save_state(d, state):
    """The record and the work, written apart: tasks/<id>.json is the record (one file per task, so tasks done on different
    branches merge as distinct files; never a PRIVATE_KEYS key), local/tasks/<id>.json this machine's overlay of exactly
    those keys. state.json keeps only the run's own fields."""
    for tid, ts in state.get("tasks", {}).items():
        pub, priv = split_private({k: v for k, v in ts.items() if k not in ("artifact-type", "written_by")})
        save(os.path.join(d, "tasks", tid + ".json"), {"artifact-type": "chongdae/task@1", **pub})
        local = os.path.join(d, LOCAL, "tasks", tid + ".json")
        if priv:
            save(local, priv)
        elif os.path.exists(local):
            os.remove(local)
    save(os.path.join(d, "state.json"), {"artifact-type": "chongdae/run@1", **{k: v for k, v in state.items() if k != "tasks"}})


def work_path(run, name):
    """A work file's place: <run>/local/<name>. The record never holds one."""
    return os.path.join(run, LOCAL, name)


def all_tasks(plan, state):
    """The plan's tasks plus the ones added during a session run (each carries its own definition in its task file), the
    added ones in the order they were added (`seq`) — task files are read in name order, and a name is not a time."""
    added = sorted((ts for ts in state.get("tasks", {}).values() if "def" in ts), key=lambda ts: (ts.get("seq", 0), ts["def"].get("id", "")))
    return plan.get("tasks", []) + [ts["def"] for ts in added]


def non_claims(state):
    """Every non-claim in the run, prefixed with its task — the reader's view over the per-task files (and older runs' shared
    list). The same sentence on several tasks is said once, with the tasks: a run of four no-check session tasks said
    "no check decides this task" four times, and a review of a day's runs read it thirty-five times."""
    out = list(state.get("non-claims", []))
    by_text = {}
    for tid, ts in sorted(state.get("tasks", {}).items(), key=lambda kv: (kv[1].get("seq", 0), kv[0])):   # task files read in name order; a name is not a time
        for n in ts.get("non-claims", []):
            by_text.setdefault(n, []).append(tid)
    for text, tids in by_text.items():
        out.append("%s: %s" % (tids[0], text) if len(tids) == 1 else "%s — %d task(s): %s" % (text, len(tids), ", ".join(tids)))
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


def record_root(start):
    """The nearest directory at or above `start` that holds a record (`.chongdae/`), or None. A run's worktree holds its own
    record, so a path inside `.chongdae/wt/<run>/` finds the worktree, not the main tree around it."""
    p = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(p, RUNS)):
            return p
        up = os.path.dirname(p)
        if up == p:
            return None
        p = up


def project_root(start):
    """The project a shell's directory belongs to: the nearest ancestor holding `.chongdae/`, else git's top level, else `start`.
    A hook's `cwd` is the shell's: after `cd tests` it was `<project>/tests`, the write hook found no run there and refused
    writes during a running run (guin-site, 2026-10-02)."""
    import subprocess
    found = record_root(start)
    if found:
        return found
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
        if top.returncode == 0 and top.stdout.strip():
            # git names it resolved (/private/var/… for /var/…): the same directory in the caller's spelling, so a file path
            # given in that spelling is still inside it
            real, p = os.path.realpath(top.stdout.strip()), os.path.abspath(start)
            while True:
                if os.path.realpath(p) == real:
                    return p
                up = os.path.dirname(p)
                if up == p:
                    return real
                p = up
    except OSError:
        pass
    return os.path.abspath(start)


def me(target):
    """Who is acting on this machine: CHONGDAE_USER, else git user.name. Claims are compared against it."""
    import subprocess
    return os.environ.get("CHONGDAE_USER") or subprocess.run(["git", "config", "user.name"], cwd=target, capture_output=True, text=True).stdout.strip() or "unknown"


def now_utc():
    """The moment of a judgment, in UTC with the offset written (git writes both times with offsets; ours are normalized).
    For display and honesty only — order between machines is never decided by clocks, only by the record's own git history."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def stamp():
    """A judgment's time and the chongdae that recorded it: one run can span versions."""
    return {"at": now_utc(), "chongdae": engine()}


_ENGINE = None

_UNCOMMITTED_TOLD = False

def engine():
    """`chongdae <version>` — with `+g<sha>[-dirty]` when this is a working source, not an installed release."""
    global _ENGINE
    if _ENGINE is None:
        root = os.path.dirname(os.path.abspath(__file__))
        v = next((load(os.path.join(root, mf)).get("version") for mf in (os.path.join(".claude-plugin", "plugin.json"), "plugin.json")
                  if load(os.path.join(root, mf)).get("version")), "unknown")
        _ENGINE = "chongdae %s%s" % (v, source_revision(root))
    return _ENGINE


def source_revision(root):
    """A plugin run from its working source (a directory marketplace, `hunsu dev`) is not the release its version names: the
    version gets the source's commit, `-dirty` when the tree has uncommitted changes — `1.2.0+g6cc62df-dirty` — so a record
    never passes an unreleased build off as the release. An installed copy (not a git tree) is the release: "" ."""
    import subprocess
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True)
        if top.returncode or os.path.realpath(top.stdout.strip()) != os.path.realpath(root):
            return ""   # not the root of its own repository: an installed copy inside something else
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip()
        return "+g%s%s" % (sha, "-dirty" if dirty else "") if sha else ""
    except OSError:
        return ""


def portable(o, target):
    """A record's copy of something that named this machine: every string with the machine taken out (neutral_path)."""
    if isinstance(o, dict):
        return {k: portable(v, target) for k, v in o.items()}
    if isinstance(o, list):
        return [portable(v, target) for v in o]
    return neutral_path(o, target) if isinstance(o, str) else o


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
        text = re.sub(r"%s/[^\s\"'`;|&)]*" % re.escape(t.rstrip("/")), "<tmp>", text)   # the whole path under it, not its first segment
    text = re.sub(r"/(?:private/)?var/folders/[^\s\"'`;|&)]*", "<tmp>", text)
    user = os.path.basename(home.rstrip(os.sep)) if home else ""
    if home and home != "~":
        # a host that names folders after paths (Claude Code: ~/.claude/projects/-Users-me-src-app) carries the home in the name
        text = text.replace(home.replace(os.sep, "-"), "~").replace(home, "~")
    if len(user) >= 3:
        text = re.sub(r"(?<![\w-])%s(?![\w-])" % re.escape(user), "<user>", text)   # the account's name, even written on its own
    return text


def head_sha(target):
    """The commit this tree stands on — a run pinned to it can be ordered by ancestry, not by anyone's clock."""
    import subprocess
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


# What stays on this machine: everything under a run's local/ — the request as sent, the response as written, a worker's
# whole session (megabytes, this machine's paths), the pending pid, the log, the full trace — and the sessions/ map.
# The record (the run's root) carries what other people and workers need: the contract as asked, who did it, what changed,
# what was judged — with the project as `.` and the home directory as `~`. The suffix patterns are for runs an earlier
# chongdae wrote with those files beside the record; a new run has none there.
RECORD_IGNORE = [LOCAL + "/", "sessions/",
                 "*.transcript*.jsonl", "*.request.json", "*.request.*.json", "*.provider.log", "*.pending.json",
                 "*.last.txt", "*.schema.json", "*.response.json", "*.response.*.json"]


def ensure_record_ignore(target):
    """`.chongdae/.gitignore` lists what stays local. Written by chongdae, for chongdae's own files only."""
    path = os.path.join(target, RUNS, ".gitignore")
    have = io.open(path, encoding="utf-8").read().split("\n") if os.path.exists(path) else []
    missing = [p for p in RECORD_IGNORE if p not in have]
    if missing:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        head = [] if have and have != [""] else ["# chongdae: a run's local/ is this machine's work (requests, responses, sessions, pending, logs);",
                                                "# the run's root is the committed record"]
        with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(head + missing) + "\n")


def commit_record(target, run_name, message, also=()):
    """A judgment was written into the run's record: commit that record, and only it, right now. git's immutability then
    notarizes the judgment — its content (the tree hash), its time (committer date), and any later edit (a visible diff).
    Without this the record's durability was a habit of whoever remembered to commit; now it is the engine's.
    The paths are pinned to the run's directory so a dirty working tree (someone else's work in flight) is never swept in;
    `also` names the few project paths a judgment wrote outside it (what the reviewer wrote at close).
    Best effort by design: no repo, nothing staged, or an identity-less git config must not stop the run — the record on
    disk is still the record; `close` and the reviewer see uncommitted records as what they are."""
    import subprocess

    def git(*a):
        return subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")

    rel = RUNS + "/" + run_name
    ensure_record_ignore(target)
    if settings(target).get("commit-records") is False:
        # the project (or this machine's overlay) says the record is written, not committed
        global _UNCOMMITTED_TOLD
        if not _UNCOMMITTED_TOLD:
            print("  (record written, not committed: settings.chongdae.commit-records is false)")
            _UNCOMMITTED_TOLD = True
        return None
    # The commit is built on a scratch index from HEAD: only this run's directory and chongdae's .gitignore enter it — what
    # the person has staged stays theirs — and a file an earlier version committed that is now local-only leaves it (a
    # path-limited `git commit` would take the file back from the working tree, where it rightly stays).
    gitdir = git("rev-parse", "--absolute-git-dir").stdout.strip()
    if not gitdir:
        return None
    env = dict(os.environ, GIT_INDEX_FILE=os.path.join(gitdir, "chongdae-record-index"))
    scratch = lambda *a: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    has_head = git("rev-parse", "--verify", "-q", "HEAD").returncode == 0
    also = [p for p in also if os.path.exists(os.path.join(target, p))]
    try:
        scratch("read-tree", "HEAD") if has_head else scratch("read-tree", "--empty")
        if scratch("add", "--", rel, RUNS + "/.gitignore", *also).returncode:
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
    git("reset", "-q", "--", rel, RUNS + "/.gitignore", *also)   # the person's index now agrees with HEAD for the record, and only there
    return head_sha(target)


def keep_contract(run, sections):
    """The plan sections a request carries, kept once per run per text — contract/<Q>-<hash>.md — so a section three tasks
    close is in the record once, and a section the plan changed between two calls is there twice, as two texts. Returns
    {section id: the record path} for the asked record."""
    import hashlib
    out = {}
    for qid, text in (sections or {}).items():
        name = "contract/%s-%s.md" % (qid, hashlib.sha256(text.encode("utf-8")).hexdigest()[:8])
        path = os.path.join(run, name)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text.rstrip("\n") + "\n")
        out[qid] = name
    return out


# ---------------------------------------------------------------- traces: what a session did, from the host's own record

def trace_of(transcript, target, since=None, project_only=False):
    """A worker's session, reduced to what a reader of the record needs: the commands it ran with their exit codes, the files
    it changed (and, where the host says so, read). Codex: `command_execution` and `file_change` items; Claude Code: tool
    calls and their results."""
    commands, changed, read, calls = [], [], [], {}
    elsewhere = 0
    home = os.path.expanduser("~")
    roots = {os.path.abspath(target), os.path.realpath(target)}
    roots |= {"~" + r[len(home):] for r in list(roots) if home and r.startswith(home + os.sep)}   # `cd ~/src/app` names it too
    def about_project(text, cwd):
        # a session works on many things; its trace for one project keeps what touched that project
        return not project_only or any(r in str(text) for r in roots) or (cwd and os.path.realpath(cwd) in roots)
    for line in io.open(transcript, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if since and d.get("timestamp") and str(d["timestamp"]).replace("Z", "+00:00") < since:
            continue   # a session's transcript holds everything it did; a task's trace is its own window
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
                        if not about_project(inp.get("command", ""), d.get("cwd")):
                            elsewhere += 1
                            continue
                        calls[c.get("id")] = {"command": neutral_path(inp.get("command", ""), target), "exit": None}
                        commands.append(calls[c.get("id")])
                    elif c.get("name") in ("Edit", "Write", "NotebookEdit"):
                        if not about_project(inp.get("file_path", ""), None):
                            elsewhere += 1
                            continue
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
    read = [r for r in read if not project_only or not os.path.isabs(r) or r.startswith(".")]
    return {"commands": commands, "changed": changed, **({"read": read} if read else {}),
            **({"elsewhere": "%d command(s) or edit(s) outside this project, kept only in the local session" % elsewhere} if elsewhere else {})}


def session_summary(trace):
    """A session is a person's (or an agent's) whole working day: its command lines carry whatever it was doing — other
    repositories, search patterns, names that are nobody's business in a committed record. The committed trace of a session
    task keeps what it changed in the project and how many commands it ran there; the command lines stay in the local
    transcript, where an audit on this machine reads them."""
    out = {"changed": trace.get("changed", []), "commands-run": len(trace.get("commands", [])),
           "command-lines": "kept in the local session transcript, not in the record"}
    if trace.get("elsewhere"):
        out["elsewhere"] = trace["elsewhere"]
    return out


def with_trace(who, response, run, target):
    """An author line with what its worker did, from the session the worker kept beside its response (local/): the record
    gets `trace` — the files it changed, how many commands it ran and how many failed; the command lines and what it read
    go to the overlay (PRIVATE_KEYS `commands`, `read`) — a model's run does not replay from its command lines, and a
    session's lines carry whatever else it was doing."""
    w = (response or {}).get("worker") if isinstance(response, dict) else None
    name = (w or {}).get("transcript") if isinstance(w, dict) else None
    path = os.path.join(run, LOCAL, os.path.basename(str(name))) if name else None
    if not (path and os.path.exists(path)):
        return who
    try:
        full = trace_of(path, target)
    except (OSError, ValueError):
        return who
    commands = full.pop("commands", [])
    failed = [c for c in commands if c.get("exit") not in (0, None)]
    read = full.pop("read", None)
    who["trace"] = {**full, "commands-run": len(commands), "commands-failed": len(failed)}
    who["commands"] = commands
    if read:
        who["read"] = read
    return who


SESSIONS = os.path.join(RUNS, "sessions")   # machine-local: session id -> where the host keeps that session's transcript (written by the SessionStart hook)

def session_transcript(target, session_id):
    """Where the host keeps a session's transcript: the SessionStart hook's record for this project, else the host's own
    layout — Claude Code keeps every session at ~/.claude/projects/<dir>/<session id>.jsonl, whichever directory it started in
    (a session started elsewhere that works on this project has no record here)."""
    import glob
    rec = load(os.path.join(target, SESSIONS, session_id + ".json")) if session_id else {}
    if rec.get("transcript") and os.path.exists(rec["transcript"]):
        return rec["transcript"]
    if not session_id or not re.fullmatch(r"[\w-]+", session_id):
        return None
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    found = glob.glob(os.path.join(home, "projects", "*", session_id + ".jsonl"))
    return found[0] if len(found) == 1 else None


def session_model(target, session_id):
    """The model behind a session, from the host's own transcript. The host tells its subprocesses the session id but not the
    model; the SessionStart hook records where the transcript is, and the transcript names the model on every assistant line.
    (None, why) when it cannot be known — a session run with persistence off leaves no transcript."""
    path = session_transcript(target, session_id)
    if not path:
        return None, "no transcript for this session on this host (no SessionStart record here, none under the host's projects)"
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
    home = os.environ.get("AGENT_CODEX_HOME") or os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
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


# ---------------------------------------------------------------- the environment: settings, providers, plugins, versions, who did it

def providers(target, plan):
    """role -> provider. The lock's `roles` (a human declaration hunsu checked) first; the plan's own `providers` may add or override."""
    lock = load(os.path.join(target, "hunsu.lock.json"))
    out = dict(lock.get("roles", {}))
    out.update(plan.get("providers", {}))
    return out


def hire(prov, task):
    """(the lock's key, its provider) for a task: a role may hold capability alternates — `implementer@loopback`, the same
    member on a host whose sandbox can bind a port (`<role>@<cap>[+<cap>]`). A task that `requires` capabilities goes to the
    alternate whose capabilities cover them (the smallest such set, then by name); otherwise, and for a task that requires
    nothing, to the plain role as before. guin-site, 2026-10-02: 14 of 15 tasks were self-performed because every hired role
    ran on a host whose sandbox could not bind the local port its tests needed."""
    role, need = task.get("role"), set(task.get("requires") or [])
    if need:
        fits = sorted((len(caps), key) for key, caps in alternates(prov, role) if need <= caps)
        if fits:
            return fits[0][1], prov[fits[0][1]]
    return role, prov.get(role)


def alternates(prov, role):
    """[(key, capabilities)] — the lock's `<role>@<cap>[+<cap>]` keys for `role`."""
    out = []
    for key in prov:
        base, at, caps = str(key).partition("@")
        if at and base == role and caps:
            out.append((key, set(c for c in caps.split("+") if c)))
    return out


def settings(target):
    """chongdae's settings: hunsu.json `settings.chongdae`, with this machine's overlay (hunsu.local.json `settings.chongdae`,
    never committed) on top — read where they are written, not from the lock."""
    out = dict(((load(os.path.join(target, "hunsu.json")).get("settings") or {}).get("chongdae") or {}))
    out.update(((load(os.path.join(target, "hunsu.local.json")).get("settings") or {}).get("chongdae") or {}))
    return out


def outside_runs(target):
    """Paths the project changes by its own procedure, not in runs (an author's posts, the site built from them):
    hunsu.json `settings.chongdae.outside-runs`, a human declaration read where it is written — not from the lock, so it
    holds while this source is tried under `hunsu dev`. Project-relative; an entry names a file or a directory. An entry
    that is absolute or climbs out of the project names nothing and is dropped."""
    declared = settings(target).get("outside-runs") or []
    out = []
    for p in declared if isinstance(declared, list) else []:
        p = str(p).replace("\\", "/").strip()
        while p.startswith("./"):
            p = p[2:]
        p = p.rstrip("/")
        if p and not p.startswith("/") and ":" not in p and ".." not in p.split("/"):
            out.append(p)
    return out


def under(rel, paths):
    """Is project-relative `rel` one of `paths` or inside one of them?"""
    return any(rel == p or rel.startswith(p + "/") for p in paths)


def install_entry(entries, target):
    """The host keeps one install record per (scope, project). The one that applies to `target` is its own project-scope
    record, else the user-scope one, else — for a project that only enabled the plugin — the first; entries[0] was the first
    project that ever installed it, which loads a different copy once versions diverge."""
    want = os.path.realpath(target)
    for scope in ("local", "project"):   # a local-scope install (this machine's, e.g. `hunsu dev`) is this project's too, and wins
        for e in entries:
            if e.get("scope") == scope and e.get("projectPath") and os.path.realpath(e["projectPath"]) == want:
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
    installed = load(os.path.join(home, "plugins", "installed_plugins.json")).get("plugins", {})
    # the copy this project runs: from the marketplace its manifest declares (or the one `hunsu dev` put it in development
    # from) — the first install record with a matching name belonged to whichever project installed it first, and a
    # site's builds once ran another project's 1.0.0 that way
    market = load(os.path.join(target, "hunsu.local.json")).get("dev", {}).get(name) \
        or (load(os.path.join(target, "hunsu.json")).get("plugins", {}).get(name) or {}).get("marketplace")
    if market:
        src = (load(os.path.join(home, "plugins", "known_marketplaces.json")).get(market) or {}).get("source") or {}
        if src.get("source") == "directory" and os.path.isdir(os.path.join(src.get("path", ""), name)):
            return os.path.join(src["path"], name)   # a directory marketplace is loaded in place by the host: the source, not a snapshot
        entries = installed.get("%s@%s" % (name, market)) or []
        want = os.path.realpath(target)
        mine = [e for e in entries if e.get("scope") == "user" or (e.get("projectPath") and os.path.realpath(e["projectPath"]) == want)]
        if mine:
            return install_entry(mine, target).get("installPath")
        raise SystemExit("plugin %s@%s is declared for this project but not installed for it here — `hunsu install`" % (name, market))
    for key, entries in installed.items():
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


def portable_argv(argv):
    """A check or provider as the record keeps it: an installed plugin's path -> `{plugin:NAME}`, anything else under this
    machine's home -> `~/…` (resolved again where it runs). A check given as `/Users/<me>/.claude/plugins/cache/…` was
    committed as is — it named the account and ran nowhere else."""
    home = os.path.expanduser("~").rstrip(os.sep)
    out = []
    for a in argv:
        a = str(a)
        if home and home != "~":
            a = re.sub(r"(?:%s|~)/\.(?:claude|codex)/plugins/cache/[^/\s\"']+/([^/\s\"']+)/[^/\s\"']+" % re.escape(home),
                       lambda m: "{plugin:%s}" % m.group(1), a)
            a = re.sub(r"%s(?=/|$)" % re.escape(home), "~", a)
        out.append(a)
    return out


def resolve_argv(target, argv):
    """`{plugin:NAME}` -> that plugin's root on this machine, a leading `~/` -> this machine's home. Plans stay portable;
    machines resolve."""
    out = []
    for a in argv:
        if a == "~" or a.startswith("~/"):
            a = os.path.expanduser(a)
        for m in set(re.findall(r"\{plugin:([\w.-]+)\}", a)):
            a = a.replace("{plugin:%s}" % m, plugin_root(target, m).replace(os.sep, "/"))
        out.append(a)
    return out


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
                used[m] = v + source_revision(root)
                break
    used["chongdae"] = engine().split(" ", 1)[1]   # the engine that ran the call is one of the versions it ran with
    locked = locked_versions(target) if target else {}
    return {k: v for k, v in (("used", used), ("locked", locked)) if v}


def locked_versions(target):
    """Every plugin the environment lock pins, with the content fingerprint it recorded (hunsu.lock.json)."""
    lock = load(os.path.join(target, "hunsu.lock.json")).get("plugins", {})
    return {name: "%s#%s" % (p.get("version"), p.get("fingerprint")) if p.get("fingerprint") else p.get("version") for name, p in sorted(lock.items())}


def against_run(who, state):
    """An author line's `versions.locked` against the run's: the same lock is said once, in state.json (`environment`);
    a call under a changed lock keeps its own."""
    locked = (who.get("versions") or {}).get("locked")
    if locked and locked == (state.get("environment") or {}).get("locked"):
        del who["versions"]["locked"]
        if not who["versions"]:
            del who["versions"]
    return who


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


# ---------------------------------------------------------------- the tree: what changed, the checks, worktrees

def record_paths(target):
    """Paths that are records or the environment, never a task's work: this run's own record dir, the host's settings, hunsu's
    files, and every path the other products declare (`record-paths` in hunsu.lock.json, from each plugin's `records`). A
    project without that lock key falls back to the siblings' names as they were before the lock carried them."""
    declared = load(os.path.join(target, "hunsu.lock.json")).get("record-paths")
    others = sorted({p for ps in (declared or {}).values() for p in ps}) if isinstance(declared, dict) else [".mangsang/", ".dwitbuk/", "reviews/"]
    return tuple([RUNS + "/", ".claude/", "hunsu"] + others)


def status_paths(target):
    """Every path `git status` says differs from HEAD (tracked or untracked), relative to the repository root: both sides of a
    rename or copy (`git mv a b` is a change to a and to b), never quoted (`-z`: a Korean or spaced name is itself). None
    when there is no git. The porcelain's text form wrote a rename as one string, `a -> b`, which named no file — a
    content move recorded that way claimed nothing, and the reviewer charged it as work outside any run."""
    import subprocess
    try:
        done = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all", "--", "."], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
    except OSError:
        return None
    if done.returncode:
        return None
    out, parts, i = [], done.stdout.split("\0"), 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        out.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":   # the next field is where it came from
            if i < len(parts) and parts[i]:
                out.append(parts[i])
            i += 1
    return [p.replace("\\", "/") for p in out]


def dirty(target, records_too=False):
    """{path: content hash} of every file that differs from HEAD (tracked or untracked) under target, paths relative to target.
    None when there is no git — then nothing can be attributed, and the record says so. The products' records are left out
    (nobody's work) unless `records_too`: what the reviewer wrote at close is a record, and the close commit wants it."""
    import hashlib, subprocess
    paths = status_paths(target)
    if paths is None:
        return None
    # porcelain paths are relative to the repository root; the record is relative to the target (a project can live in a subdirectory)
    prefix = subprocess.run(["git", "rev-parse", "--show-prefix"], cwd=target, capture_output=True, text=True, encoding="utf-8").stdout.strip().replace("\\", "/")
    out = {}
    for path in paths:
        path = path[len(prefix):] if prefix and path.startswith(prefix) else path
        if path and not path.startswith((RUNS + "/",) if records_too else record_paths(target)) and not re.search(r"(^|/)__pycache__/|\.py[co]$", path):   # records, machine-local state and interpreter leftovers are nobody's work
            full = os.path.join(target, path)
            out[path] = hashlib.sha1(io.open(full, "rb").read()).hexdigest() if os.path.isfile(full) else "gone"
    return out


def record_changes(target):
    """Files under the record paths that differ from HEAD now — the environment (hunsu's manifest, lock, judgments) and the
    products' records (`mangsang/`, `reviews/`), this run's own directory aside. They are never in `touched` (nobody's work by
    rule), and a verify request that says only `touched: []` while the tree shows them reads as a record that lies: a task whose
    whole work is `hunsu lock` or `mangsang confirm` was rejected for exactly that. The request lists them, so the reader knows
    they were left out by rule, not by omission."""
    rp = record_paths(target)
    return sorted(p for p in (dirty(target, records_too=True) or {}) if p.startswith(rp))


def file_hash(target, path):
    """A file's content hash as `dirty` writes it, or "gone"."""
    import hashlib
    full = os.path.join(target, path)
    return hashlib.sha1(io.open(full, "rb").read()).hexdigest() if os.path.isfile(full) else "gone"


def committed_since(target, head):
    """{path: content hash at `head`} for every file a commit since `head` changed (records and leftovers aside, as in `dirty`):
    work the session committed before `run` measured it. Empty when HEAD has not moved or there is no git."""
    import hashlib, subprocess
    if not head or head == head_sha(target):
        return {}
    done = subprocess.run(["git", "diff", "--name-only", "-z", "--no-renames", "--relative", head, "HEAD", "--", "."], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
    if done.returncode:
        return {}
    out = {}
    for path in done.stdout.split("\0"):
        path = path.replace("\\", "/")
        if path and not path.startswith(record_paths(target)) and not re.search(r"(^|/)__pycache__/|\.py[co]$", path):
            then = subprocess.run(["git", "show", "%s:./%s" % (head, path)], cwd=target, capture_output=True)
            out[path] = hashlib.sha1(then.stdout).hexdigest() if then.returncode == 0 else "gone"
    return out


def touched_files(target, start=None, head=None):
    """What changed since the task started: every file whose content is not what it was then. Without a start snapshot, the
    whole dirty set. A file dirty at start and clean now went back to HEAD — a change like any other, and the one a build
    makes when it takes the committed version of an uncommitted file for the real one (a contract's newest tests).
    `head`, the commit the tree stood on at start: a file a commit since then changed is measured against what it was there,
    so work the session committed before `run` is still this task's (guin-site's drop-nojekyll recorded `touched: []`
    for three committed files, and the report then had nobody to attribute them to)."""
    now = dirty(target)
    if now is None:
        return None
    start = start or {}
    then = committed_since(target, head)
    changed = {p for p, h in now.items() if start.get(p, then.get(p)) != h}
    for p, h in list(start.items()) + [(p, h) for p, h in then.items() if p not in start]:
        if p not in now and file_hash(target, p) != h:
            changed.add(p)
    return sorted(changed)


def keep_contract_tests(target, run, task):
    """The contract's tests as they are when the task starts — the working tree, not HEAD: a test written for this contract
    and not yet committed is its newest version. Kept among the run's work files, so a build that changes them can be undone
    by the runner instead of by whoever still remembers what they said."""
    for t in task.get("tests") or []:
        src = os.path.join(target, t)
        if os.path.isfile(src):
            dst = work_path(run, os.path.join("contract-tests", task["id"], t))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)


def restore_contract_tests(target, run, task, paths):
    """Put the contract's tests back as they were kept at the task's start. Returns the paths restored."""
    back = []
    for t in paths:
        kept = work_path(run, os.path.join("contract-tests", task["id"], t))
        if os.path.isfile(kept):
            shutil.copyfile(kept, os.path.join(target, t))
            back.append(t)
    return back


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


def is_self_recheck(argv):
    """A check that is chongdae's own recheck. Re-running it from inside a recheck recurses without end
    (a merge run's check is `chongdae recheck`; recheck re-runs every completed run's checks — including that one).
    The verdict it stood for is exactly what the outer recheck is already computing, so it is skipped, not lost."""
    return any(a == "recheck" for a in argv) and any("chongdae" in str(a) for a in argv)


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
    # the run landed: pin the merge commit into its record (in main) — the fact a reader orders completed runs by — and commit that judgment
    landed = (git(main, "rev-parse", "HEAD").stdout or "").strip()
    rec = os.path.join(main, RUNS, run_name, "state.json")
    if landed and os.path.exists(rec):
        st = load(rec)
        st["landed"] = {**stamp(), "commit": landed}
        save(rec, st)
        commit_record(main, run_name, "landed as %s" % landed[:12])
    print("merged %s into main and removed the worktree — recheck green" % branch)
    return 0


# ---------------------------------------------------------------- contracts: plan shapes, artifact checks, what decides a task

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
        for x in t.get("tests") or []:
            if isinstance(x, str) and re.search(r"\s", x.strip()):
                # `--tests "$(ls tests/*.py)"` arrives as one string: the guard looked that string up and watched nothing
                out.append("%s: `tests` entry %r holds several paths — one path per entry (`--tests a.py b.py`, unquoted)" % (t.get("id"), x[:80]))
        for c in t.get("checks") or []:
            # a check is one command: a shell line (`sh -c 'a && b'`) hides the commands inside it — the worker reports them as its
            # shell spelled them, the validator compares another spelling, and the record keeps a string nobody can re-run apart
            if isinstance(c, list) and len(c) >= 3 and os.path.basename(str(c[0])) in ("sh", "bash", "zsh", "dash") and str(c[1]).startswith("-") and "c" in str(c[1]):
                out.append("%s: a check is one command, not a shell line — `%s …` hides what it runs from the worker's report and the record; give each command its own check" % (t.get("id"), " ".join(str(x) for x in c[:2])))
        bad = [x for x in t.get("requires") or [] if x not in REQUIRES]
        if bad:
            out.append("%s: requires %s — known: %s" % (t.get("id"), ", ".join(bad), ", ".join(REQUIRES)))
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


def gate_of(task):
    """`gate: "human"` or `gate: {"human": true, "delegate": "after-verifier"}` -> the dict form."""
    g = task.get("gate")
    return g if isinstance(g, dict) else ({"human": True} if g == "human" else {})


# ---------------------------------------------------------------- one provider call

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


REQUIRES = ("network", "loopback")   # what a task may require of the sandbox its hands run in


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
    req_path = work_path(run, tag + ".request.json")
    res_path = work_path(run, tag + ".response.json")
    pend_path = work_path(run, tag + ".pending.json")
    log_path = work_path(run, tag + ".provider.log")
    os.makedirs(os.path.join(run, LOCAL), exist_ok=True)
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
               **({"domain": task["domain"]} if task.get("domain") else {}),
               # what the work requires of the sandbox it runs in (`requires` on the task; `needs` in a task already means the
               # tasks it waits for): a member that cannot give it refuses before it starts — five attempts on guin-site died
               # on a worker that could not open a local port, found only by trying
               **({"needs": list(task["requires"])} if task.get("requires") else {}),
               "response": res_path.replace(os.sep, "/")}
        if attempts:
            # A slice that spans calls: the next call is a fresh process. It resumes from the tree as the last call left it and from
            # these reports — not from anyone's memory. `touched` is what the tree already differs in.
            req["attempts"] = [{k: a.get(k) for k in ("status", "summary", "verified", "decisions", "non-claims", "retried", "review", "disputed-tests", "reopened") } for a in attempts]
            req["touched"] = touched_files(target)
        req.update(extra or {})
        save(req_path, req)
        # the request as sent names this machine's paths and stays local; what the provider was asked, portably, is
        # the record's — without it nobody else can put the same question to a worker again. The contract's sections are
        # kept once per run per text (contract/), and every asked record points at them: three tasks closing one section
        # carried three copies of it
        save(os.path.join(run, "asked", tag + ".json"), {**portable(req, target), "contract": keep_contract(run, sections)})
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


def waiting_text(what, d):
    return ("%s: the provider is still working (pid %s, since %s; its output so far: %s) — `chongdae run` again keeps waiting for the same work; "
            "do not background `run` and do not end the session — the provider is this session's child and dies with it"
            % (what, d.get("pid"), d.get("since"), d.get("log")))


def dispatch_text(what, d):
    return ("session agent: dispatch %s to this host's own subagent — get the prompt with `%s`, give it to a FRESH subagent of this host "
            "(Claude Code: the Agent tool, general-purpose, with that prompt as its task; Codex: spawn_agent), write its final JSON answer VERBATIM to %s "
            "(no edits, no additions), then `chongdae run`. The request is %s."
            % (what, " ".join('"%s"' % a if " " in a else a for a in d.get("prompt_argv") or []), d.get("response"), d.get("request")))


# ---------------------------------------------------------------- the run

def stop(msg, *lines):
    for line in lines:
        print("  " + line)
    print("decision: " + msg)
    return DECISION


def cmd_run(args):
    """Advance the run one step: every task whose needs are met, in order — hire its hands, decide it by its checks, place
    the eyes, run the people hired after it, stop at its gate — until the loop stops for someone (exit 2) or the run
    completes. The phases are functions below; each returns None to go on, or the exit code of the stop it printed."""
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
    ctx = {"args": args, "target": target, "d": d, "plan": plan, "state": state, "providers": providers(target, plan),
           "me": me(target), "claimed_now": set(), "waited": False}   # claimed_now: files the tasks completed in this call recorded as theirs
    for task in all_tasks(plan, state):
        ts = state["tasks"][task["id"]]
        if ts["status"] in ("done", "skipped", "dropped"):
            continue
        if any(state["tasks"][n]["status"] != "done" for n in task.get("needs", [])):
            continue
        if ts.get("claimed_by") and ts["claimed_by"] != ctx["me"]:
            print("  %s is claimed by %s — not this machine's to advance" % (task["id"], ts["claimed_by"]))
            continue
        if ts.get("rebaseline"):
            # this build's tests were disputed: it waits for the task amending them, then takes the amended files as its
            # contract — the next judgment keeps the fix instead of restoring what the dispute was about
            amenders = amending_tasks(plan, state, task, ts["rebaseline"])
            if amenders:
                ctx["waited"] = True
                print("  %s waits for %s to amend %s" % (task["id"], ", ".join(amenders), ", ".join(ts["rebaseline"])))
                continue
            rebaseline(target, d, task, ts)
            save_state(d, state)
        # a task the session took over (`take`) is the session's from then on, whoever the lock hired for its role
        who = "session" if ts.get("taken") else hire(ctx["providers"], task)[1]
        if who is None:
            if task.get("optional"):
                ts["status"] = "skipped"
                ts["non-claims"] = ["no provider for role %r — %s not produced; nothing substituted" % (task["role"], task["produces"])]
                save_state(d, state)
                print("  skipped %s (role %s has no provider) — recorded as a non-claim" % (task["id"], task["role"]))
                continue
            alts = [k for k, _ in alternates(ctx["providers"], task["role"])]
            return stop("role %r has no provider — declare one in hunsu.json `roles` (then lock) or in the plan's `providers`%s"
                        % (task["role"], " (the lock has %s, for tasks that require those capabilities: `chongdae retry %s --requires CAP`)" % (", ".join(alts), task["id"]) if alts else ""))
        # task paths are project-relative: artifacts belong to the project, .chongdae holds only how the run went
        path = os.path.join(target, task["path"]) if task.get("path") else None
        if "start" not in ts:
            absent = [t for t in task.get("tests") or [] if not os.path.isfile(os.path.join(target, t))]
            if absent and task.get("checks"):
                return stop("%s: its protected tests do not exist (%s) — the guard would watch nothing; the task that writes them runs first, "
                            "or fix the paths (`chongdae drop` and `add` again)" % (task["id"], ", ".join(absent)))
            ts["start"] = dirty(target)   # what the tree already differed in: `touched` is measured from here, not from HEAD
            ts["start-head"] = head_sha(target)   # and the commit under it: a commit made during the task is still the task's work
            keep_contract_tests(target, d, task)
            save_state(d, state)
        if ts["status"] == "todo":
            # People hired before the work: each answers with findings about the contract; a finding is a plan question, so the
            # task waits until a human accepts them (having written the answers into the plan) — the hands do not move on an open question.
            code = run_stage(target, d, task, ts, state, plan, ctx["providers"], "before", {"tests": task.get("tests", [])})
            if code is not None:
                return code
        if ts["status"] == "todo" and who != "session":
            # A command provider: a fresh process gets a request file and must leave a response file. chongdae reads only the response.
            code = run_hands(ctx, task, ts, who)
            if code is not None:
                return code
        if ts["status"] == "todo":
            code = decide_task(ctx, task, ts, who, path)
            if code is not None:
                return code
        if ts["status"] == "produced" and gate_of(task).get("human"):
            return stop("human: review %s (%s) — then `chongdae confirm %s --by <name>` or `--delegated \"<why the human handed this off>\"`"
                        % (task.get("produces", "task %s (checks passed: %s)" % (task["id"], "; ".join(" ".join(c) for c in task.get("checks", [])))), path or task.get("closes", ""), task["id"]))
        ts["status"] = "done"
        ts["done"] = stamp()   # when it became done: `show` tells a run's durations from it
        save_state(d, state)
        print("  done %s" % task["id"])
    if ctx["waited"] and not any(state["tasks"][t["id"]].get("rebaseline") and state["tasks"][t["id"]]["status"] == "todo"
                                 and amending_tasks(plan, state, t, state["tasks"][t["id"]]["rebaseline"]) for t in all_tasks(plan, state)):
        # a build passed over while its tests were amended by a task later in the order: the amendment is done now
        setattr(args, "continuing", True)
        return cmd_run(args)
    return end_of_pass(ctx)


def run_hands(ctx, task, ts, who):
    """A command provider: a fresh process gets a request file and must leave a response file. chongdae reads only the
    response — and routes what it says: a dispute over the contract's tests back to their writer, a refusal of the report
    over a check's spelling against chongdae's own run of the checks, a `blocked` or unfinished answer to a person,
    decisions beyond the contract to a person's `accept`."""
    args, target, d, state, plan = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"]
    if not ts.get("response"):
        code, response, before = spawn(target, d, task, who, plan, ts.get("attempts", []),
                                       extra={"amending": ts["amending"]} if ts.get("amending") else None)
        if code == DISPATCH:
            return stop(dispatch_text(task["id"], response))
        if code == WAITING:
            return stop(waiting_text(task["id"], response))
        ts["response"] = response
        ts["answered"] = stamp()   # when the hands' answer came back: the attempt's end, for `show`
        ts["touched_by_provider"] = touched_files(target, before)
        ts["performed_by"] = against_run(with_trace(performer(who, argv=who if isinstance(who, list) else [who], response=response, target=target), response, d, target), state)   # the un-resolved argv: portable, names host/model without machine paths
        key = hire(ctx["providers"], task)[0]
        if key != task["role"]:
            ts["performed_by"]["as"] = key   # the lock's capability alternate this task went to (`implementer@loopback`)
        if native_argv(target, who):
            ts.setdefault("non-claims", []).append("%s: the answer was written by the session on a native subagent's behalf; chongdae did not observe the subagent" % task["id"])
        save_state(d, state)
    response = ts["response"]
    again = ("then `chongdae retry %s --by NAME | --delegated WHY` sends it out again with this attempt attached — or, when the work is in the "
             "tree and the session will finish it, `chongdae take %s --why WHY` (checks, eyes and gate as for any task; a drop would record done work as not done)"
             % (task["id"], task["id"]))
    unattempted = [n for n in response.get("non-claims", []) if str(n).startswith("not attempted:")]
    lacked = sandbox_lacked(response)
    if (response.get("status") == "blocked" and unattempted) or (response.get("status") in ("blocked", "failed") and lacked is not None):
        # the member refused before starting (the task requires what its sandbox cannot give), or stopped mid-task because its
        # sandbox lacked a capability (`sandbox lacked: …`, `lacked: [...]`). Resending to the same member changes nothing, and
        # it is not a decision the contract lacks — it is a hiring question
        return hiring_stop(ctx, task, ts, response, lacked if lacked is not None else list(task.get("requires") or []),
                           unattempted + [n for n in response.get("non-claims", []) if str(n).startswith("sandbox lacked:")])
    if response.get("status") == "blocked" and response.get("disputed-tests"):
        setattr(args, "continuing", True)
        if route_dispute(target, d, state, plan, task, response["disputed-tests"]):
            return cmd_run(args)
    if response.get("status") == "blocked":
        return stop("%s: the provider stopped — it needs a decision the contract does not give: %s — write it into the plan, %s%s" % (
                        task["id"], response.get("summary", ""), again,
                        "; it disputes the contract's tests: `chongdae dispute %s --tests FILE... --why WHY` routes them to the task that wrote them" % task["id"]
                        if response.get("disputed-tests") else ""),
                    *response.get("non-claims", []))
    refused = [n for n in response.get("non-claims", []) if str(n).startswith("checks-ran:")]
    if response.get("status") == "failed" and refused and not ts.get("checks-ran-overruled"):
        # The validator refused the report for naming a check it did not see run. The checks decide a task, and
        # chongdae runs them itself right after — so when they pass here, the refusal was about the report's words,
        # not the tree: a worker ran `sh -c '…'` and reported it as the host's shell wrapper spelled it, twice, and
        # each refusal cost a build and a wait. Green here: the report stands as the worker's word, with the
        # mismatch on record. Red here: back to the hands, as before.
        if task.get("checks") and not run_checks(target, task["checks"]):
            ts["checks-ran-overruled"] = {"refused": [str(n)[:300] for n in refused], **stamp()}
            ts.setdefault("non-claims", []).append("%s: the validator refused the report for naming a check it did not see run (%s); chongdae ran the task's checks itself and they passed, so the report stands as the worker's word" % (task["id"], str(refused[0])[:160]))
            save_state(d, state)
            print("  %s: the report's check was not recognized by the validator; the checks pass here — going on, recorded" % task["id"])
        elif (setattr(args, "continuing", True) or True) and auto_resend(target, d, state, task["id"], "the report named a check the session did not run: " + refused[0][:160]):
            return cmd_run(args)
    if response.get("status") != "done" and not ts.get("checks-ran-overruled"):
        return stop("%s: provider %r did not finish (%s) — see %s; fix what stopped it (or nothing, if it ran out of budget), %s"
                    % (task["id"], who, response.get("status"), work_path(d, task["id"] + ".response.json"), again))
    if response.get("decisions") and not ts.get("accepted"):
        # The provider settled something the contract did not. That is a plan change: a human writes it into the plan and accepts, or rejects the work.
        return stop("%s: the provider made %d decision(s) the contract did not — write each into the plan, then `chongdae accept %s --by NAME | "
                    "--delegated WHY` and re-run; or reject the work: reset the tree, say why in the plan or brief, then `chongdae retry %s --by NAME | --delegated WHY`"
                    % (task["id"], len(response["decisions"]), task["id"], task["id"]),
                    *("%s: chose %r (alternatives: %s)" % (x["what"], x["chosen"], ", ".join(x["alternatives"]) or "-") for x in response["decisions"]))
    if not ts.get("reported"):
        ts["non-claims"] = ts.get("non-claims", []) + ["(provider) %s" % n for n in response.get("non-claims", [])]
        ts["reported"] = True
        save_state(d, state)
    return None


def sandbox_lacked(response):
    """The capabilities a member's sandbox lacked mid-task, as hacheong reports them: `lacked: ["loopback"]`, and a non-claim
    starting `sandbox lacked: `. [] when only the non-claim says so and names no capability chongdae knows; None when
    neither is there."""
    said = [str(n) for n in response.get("non-claims") or [] if str(n).startswith("sandbox lacked:")]
    field = response.get("lacked")
    if not said and not field:
        return None
    caps = [str(c) for c in field] if isinstance(field, list) else ([str(field)] if field else [])
    for n in said:
        caps += [c for c in REQUIRES if re.search(r"\b%s\b" % c, n[len("sandbox lacked:"):])]
    return list(dict.fromkeys(caps))


def hiring_stop(ctx, task, ts, response, caps, lines):
    """A member could not do the task here because of its sandbox: name what it lacked and the ways on — say so on the task
    (`retry --requires CAP`), which sends it to the lock's `<role>@<cap>` alternate when there is one; declare one when there
    is none; or the session takes it."""
    tid, role, prov = task["id"], task["role"], ctx["providers"]
    have = list(task.get("requires") or [])
    known = [c for c in caps if c in REQUIRES]
    want = have + [c for c in known if c not in have]
    used = (ts.get("performed_by") or {}).get("as") or role
    alt = hire(prov, {"role": role, "requires": want})[0] if want else role
    lacks = ", ".join(caps) or "a capability it did not name"
    ways = []
    if alt != role and alt != used:
        ways.append("`chongdae retry %s%s --by NAME | --delegated WHY` sends it to the lock's %s"
                    % (tid, " --requires " + " ".join(want) if want != have else "", alt))
    else:
        if used != role:
            ways.append("the lock's %s was hired for it and its sandbox lacked it too" % used)
        if want != have:
            ways.append("`chongdae retry %s --requires %s --by NAME | --delegated WHY` says on the task what its sandbox must give" % (tid, " ".join(want)))
        ways.append("hire a member whose sandbox can — `%s@%s` in hunsu.json `roles` (the same member on a host that gives %s), then `hunsu lock` and `chongdae retry %s%s`"
                    % (role, "+".join(want) or "CAP", "+".join(want) or "it", tid, " --requires " + " ".join(want) if want != have else ""))
    ways.append("or `chongdae take %s --why WHY` and the session does it" % tid)
    return stop("%s: %s (%s) — its sandbox lacked %s: a hiring question, not a decision the contract lacks; resending to the same member changes nothing. %s"
                % (tid, response.get("summary") or "the member cannot do this task here", used, lacks, "; ".join(ways)), *lines)


def decide_task(ctx, task, ts, who, path):
    """What makes a task done: its checks passing (a code task), its artifact passing its shape check (a bootstrap task), or
    — with no check — the agent's word, which must at least be the task's own. Then the eyes, then the people hired after,
    then the record of what it touched and who did it; the task is `produced` and waits at its gate, if it has one."""
    args, target, d, state, plan, prov = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"], ctx["providers"]
    if task.get("checks"):
        # Code tasks: done means the checks pass. Not started and failing look the same — both are "not yet".
        failed = run_checks(target, task["checks"])
        if failed:
            return stop("session agent: %s — make these checks pass, then `chongdae run`" % task["id"], task.get("brief", ""), *failed)
        touched = touched_files(target, ts.get("start"), ts.get("start-head")) or []
        broken = [t for t in task.get("tests", []) if t in touched]
        if broken:
            # The contract owns its checks. A build that edits them decided its own verdict — that is a reject, whoever built.
            ts["rejected"] = {"by": "contract", "why": "changed protected tests: %s" % ", ".join(broken)}
            back = restore_contract_tests(target, d, task, broken)
            if back:
                ts["rejected"]["restored"] = back
            save_state(d, state)
            left = [t for t in broken if t not in back]
            return stop("%s: the build changed the contract's tests (%s) — %s (the contract decides, not the builder), "
                        "then `chongdae retry %s --by NAME | --delegated WHY`" % (
                            task["id"], ", ".join(broken),
                            "restored as they were when the task started" if not left else "restore %s" % ", ".join(left), task["id"]))
        # Independent eyes before the gate: not the hands, and their verdict goes here, not back to the builder.
        code = place_eyes(ctx, task, ts, who, touched)
        if code is not None:
            return code
    elif not task.get("path"):
        if who == "session" and ts.get("amending"):
            # reopened by a dispute over the tests it wrote: done is the amendment, measured against the tests as the
            # disputing build protected them — not this task's word that it looked
            files = sorted({str(x.get("test", "")).split("::")[0].split(" ")[0] for x in ts["amending"] if isinstance(x, dict)})
            if files and not set(files) & set(touched_files(target, ts.get("start"), ts.get("start-head")) or []):
                return stop("session agent: %s — its tests were disputed; amend %s as the dispute says, then `chongdae run` (the build that protects "
                            "them takes the amended files as its contract once this task is done)" % (task["id"], ", ".join(files)),
                            *["%s: %s" % (x.get("test"), x.get("why")) for x in ts["amending"] if isinstance(x, dict)])
        # a session task with no check: done is the agent's word (a non-claim since `add`). It still has to be the
        # task's own word: a task added ahead of its work would otherwise be done here with the files the task before
        # it changed — a false claim a done task cannot take back
        if who == "session" and ctx["claimed_now"] and not touched_files(target, ts.get("start"), ts.get("start-head")):
            return stop("session agent: %s has changed nothing of its own — %s were the task before it — do its work, then "
                        "`chongdae run`; `chongdae drop %s --why` if it will not be done" % (task["id"], ", ".join(sorted(ctx["claimed_now"])), task["id"]),
                        task.get("brief", ""))
    else:
        if not (path and os.path.exists(path)):
            return stop("session agent: produce %s at %s, then `chongdae run`" % (task["produces"], path), task["brief"])
        problems = CHECKS[task["produces"]](path, state)
        if problems:
            return stop("%s does not pass its shape check — fix it, then `chongdae run`" % task["produces"], *problems)
    # People hired after the work: they see the result (touched files, the builder's report) and answer with findings for
    # the record — not a verdict; the gate stands as declared, and the reviewer's report carries what they found.
    built = {k: (ts.get("response") or {}).get(k) for k in ("summary", "verified", "non-claims")} if ts.get("response") else None
    code = run_stage(target, d, task, ts, state, plan, prov, "after", {"touched": touched_files(target, ts.get("start"), ts.get("start-head")) or [], "tests": task.get("tests", []), "built": built})
    if code is not None:
        return code
    ts["status"] = "produced"
    ts["checks"] = task.get("checks", [])
    ts["touched"] = touched_files(target, ts.get("start"), ts.get("start-head"))   # what this task changed: the reviewer joins runs to files with it
    earlier = [f for a in ts.get("attempts", []) if a.get("reopened") for f in a.get("touched") or []]
    if earlier and ts["touched"] is not None:
        ts["touched"] = sorted(set(ts["touched"]) | set(earlier))   # reopened to amend: what it wrote before is still its own
    ctx["claimed_now"].update(ts["touched"] or [])
    # those files are this task's now: a session task still open measures its own changes from here, not from its `add`
    now = dirty(target) or {}
    for t2 in all_tasks(plan, state):
        other = state["tasks"][t2["id"]]
        if other is not ts and other.get("status") == "todo" and isinstance(other.get("start"), dict) and (prov.get(t2["role"]) == "session" or other.get("taken")):
            for f in ts["touched"] or []:
                other["start"][f] = now.get(f) or file_hash(target, f)   # pinned: committed since, it may be clean at a newer HEAD
    if "performed_by" not in ts:
        ts["performed_by"] = against_run(performer(who, target=target), state)   # the session did the work: record which host/model/session, like a commit author
    if who == "session" and not ts.get("response"):
        # a session task's "done" is the agent's word; what the session did in the task's window is on the host's own
        # record — the same trace a worker's call gets, cut from the session transcript at the time the task was added
        transcript = session_transcript(target, (ts.get("performed_by") or {}).get("session", ""))
        if transcript:
            try:
                ts["performed_by"]["trace"] = {**session_summary(trace_of(transcript, target, since=str(ts.get("added") or ""), project_only=True)), "window-from": ts.get("added")}
            except (OSError, ValueError):
                pass
        else:
            ts.setdefault("non-claims", []).append("no session transcript here: what the session did for this task is its word alone")
    save_state(d, state)
    return None


def place_eyes(ctx, task, ts, who, touched):
    """Independent eyes before the gate: not the hands, and their verdict goes here, not back to the builder. A reject goes
    back to the hands on its own (twice) — unless the hands are the session reading the stop."""
    args, target, d, state, plan, prov = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"], ctx["providers"]
    if not prov.get("verifier"):
        return None
    if not ts.get("review"):
        built = {k: (ts.get("response") or {}).get(k) for k in ("summary", "verified", "non-claims")} if ts.get("response") else None
        by_provider = ts.get("touched_by_provider")
        extra = {"touched": by_provider if by_provider is not None else touched, "tests": task.get("tests", []), "built": built,
                 "excluded": {"record-paths": record_changes(target)}}
        if by_provider is not None:
            extra["touched_since"] = sorted(set(touched) - set(by_provider))   # changed after the builder answered: a person's plan edits, say — not the builder's
        last = next((a for a in reversed(ts.get("attempts", [])) if (a.get("review") or {}).get("verdict") == "reject" and isinstance(a.get("reviewed_tree"), dict)), None)
        if last:
            # a re-verification: what the last reject found, and what changed since that verdict. Re-reading the whole slice
            # each round cost the verifier its full time again and found a new edge each time — the rounds did not converge
            extra["recheck"] = {"findings": last["review"].get("findings", []), "changed_since": touched_files(target, last["reviewed_tree"]) or []}
        code, review, _ = spawn(target, d, task, prov["verifier"], plan, ts.get("attempts", []), stage="verify", extra=extra)
        if code == DISPATCH:
            return stop(dispatch_text(task["id"] + " (verify)", review))
        if code == WAITING:
            return stop(waiting_text(task["id"] + " (verify)", review))
        ts["review"] = review
        ts["verdict-given"] = stamp()   # when the eyes answered: the verification's end, for `show`
        ts["reviewed_tree"] = dirty(target)   # the tree this verdict was about: the next round is measured from here
        ts["verified_by"] = against_run(with_trace(performer(prov["verifier"], argv=prov["verifier"] if isinstance(prov["verifier"], list) else [prov["verifier"]], response=review, target=target), review, d, target), state)
        if native_argv(target, prov["verifier"]):
            ts.setdefault("non-claims", []).append("%s: the verdict was written by the session on a native subagent's behalf; chongdae did not observe the subagent" % task["id"])
        save_state(d, state)
    review = ts["review"]
    if review.get("verdict") not in ("accept", "reject"):
        ts.pop("review", None)
        ts.pop("verdict-given", None)
        save_state(d, state)
        return stop("%s: the verifier did not answer (%s) — fix the verifier or its provider argv, then `chongdae run`" % (task["id"], review.get("summary") or review.get("status") or "no verdict"))
    if review["verdict"] == "reject":
        ts["rejected"] = {"by": "verifier", "why": "%d finding(s)" % len(review.get("findings", []))}
        save_state(d, state)
        # back to the hands on its own — unless the hands are the session reading this stop: resending to it would
        # only run the verifier again on the same tree
        if who != "session" and (setattr(args, "continuing", True) or True) and auto_resend(target, d, state, task["id"], "the verifier rejected: %d finding(s)" % len(review.get("findings", []))):
            return cmd_run(args)
        return stop("%s: the verifier rejected the slice — fix the tree (or the contract, and re-plan), then `chongdae retry %s --by NAME | --delegated WHY`" % (task["id"], task["id"]),
                    *("%s @ %s: %s — record: “%s” — tree: “%s”" % (f.get("kind"), f.get("where"), f.get("why"), f.get("record_quote"), f.get("tree_quote"))
                      for f in review.get("findings", [])))
    return None


def end_of_pass(ctx):
    """Every task this machine could advance was advanced. A session run waits for the next `add` or `close`; a plan run
    with open tasks claimed elsewhere says so; a plan run with nothing open is complete — the reviewer is placed and the
    record committed."""
    args, target, d, state, plan = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"]
    if plan.get("kind") == "session":
        open_ = [t["id"] for t in all_tasks(plan, state) if state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped")]
        print("session run %s: %d task(s), %d open (%s) — `chongdae add` for the next piece, `chongdae close` at the end" % (os.path.basename(d), len(state["tasks"]), len(open_), ", ".join(open_) or "-"))
        return 0
    if any(state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped") for t in all_tasks(plan, state)):
        return stop("nothing this machine can advance — the open tasks are claimed elsewhere (or blocked on them); pull and `chongdae run` again")
    state["status"] = "complete"
    state["ended"] = stamp()   # when the run ended: `show` gives its duration from `created` to here
    save_state(d, state)
    wrote = place_reviewer(target, d, state, plan)
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "complete — %s" % plan.get("goal", ""), also=wrote)
    print("run %s complete. non-claims: %s" % (os.path.basename(d), non_claims(state) or "none"))
    return 0


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
        by = against_run(with_trace(performer(provider, argv=provider if isinstance(provider, list) else [provider], response=response, target=target), response, d, target), state)
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
        for f in response.get("findings") or []:   # what the session must relay to the person: said here, not left for it to dig out of JSON
            print("    %s @ %s: %s — \u201c%s\u201d" % (f.get("kind"), f.get("where", ""), f.get("why", ""), " ".join(str(f.get("quote", "")).split())[:160]))
    return None


def stage_wait_text(tid, role, response):
    lines = ["%s: %s found %d thing(s) the contract leaves open — decide each in the plan (or dismiss it there), then `chongdae accept %s --by NAME | --delegated WHY`"
             % (tid, role, len(response.get("findings") or []), tid)]
    for f in response.get("findings") or []:
        lines.append("%s @ %s: %s — \u201c%s\u201d" % (f.get("kind"), f.get("where", ""), f.get("why", ""), f.get("quote", "")))
    return stop(*lines)


def place_reviewer(target, d, state, plan):
    """The run has ended; its record is reviewed now, by the lock's `reviewer` role — placed by the runner, as the verifier
    is, never by the hands. The reviewer is a command run in the project (dwitbuk's `review` is one): whatever it wrote there
    is part of the closing record and goes into the close commit (returned as paths); what it said last is kept in
    state.json `reviewed`. No reviewer in the lock: a non-claim, nothing substituted. A reviewer that fails: also a non-claim
    — the run still closes."""
    import subprocess
    prov = providers(target, plan).get("reviewer")
    if not prov or prov == "session" or (isinstance(prov, dict) and prov.get("native")):
        state.setdefault("non-claims", []).append("no `reviewer` role in the lock%s: nobody reviewed this run's record when it ended"
                                                  % (" (it names the session or a native subagent — the reviewer is a command, never the hands)" if prov else ""))
        return []
    before = dirty(target, records_too=True) or {}
    try:
        # nothing that goes wrong here stops the run from ending: a reviewer that cannot be resolved or run is a non-claim
        argv = resolve_argv(target, [str(a) for a in (prov if isinstance(prov, list) else prov.split())])
        if argv and argv[0] in ("python", "python3") and not shutil.which(argv[0]):
            argv[0] = next((c for c in ("python3", "python") if shutil.which(c)), None) or sys.executable
        done = subprocess.run(argv, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        code, out = done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.TimeoutExpired, SystemExit) as err:
        code, out = 1, str(err)
    after = dirty(target, records_too=True) or {}
    wrote = sorted(p for p, h in after.items() if before.get(p) != h)
    said = [l for l in out.strip().split("\n") if l.strip()][-1:] or [""]
    rec = {"by": performer(prov, argv=prov if isinstance(prov, list) else [prov]), "said": said[0][:300], "wrote": wrote, **stamp()}
    if code:
        rec["exit"] = code
        state.setdefault("non-claims", []).append("the reviewer exited %d when this run ended: its review is not on record (%s)" % (code, said[0][:120]))
    state["reviewed"] = rec
    print("  reviewer: %s%s" % (said[0][:200], " — wrote %s" % ", ".join(wrote) if wrote else ""))
    return wrote


AUTO_RESENDS = 2   # per task: a verifier's reject or a refused report goes back to the hands this many times before a person is asked

def resend(target, d, state, task_id, retried, message=None):
    """Send a stopped task out again, keeping the stopped attempt (its response, review, stages) in the record under its
    number — the next call receives it. `retried` says who sent it: a person (`by`), a delegation, or chongdae itself."""
    ts = state["tasks"][task_id]
    response = ts.pop("response", None)
    attempt = {**(response or {"status": "session"}), "retried": {**retried, **stamp()}}
    if response:
        with_trace(attempt, response, d, target)   # what this attempt's worker did stays with the attempt
    for key in ("review", "rejected", "reviewed_tree", "answered", "verdict-given"):   # the attempt keeps its verdict and its times
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
    # what the provider said it did not claim was about the work this attempt did; the attempt keeps it (its response), the
    # task's own list keeps only what is still true — every attempt's copies piled up as near-duplicate findings
    if "non-claims" in ts:
        ts["non-claims"] = [n for n in ts["non-claims"] if not str(n).startswith("(provider) ")]
    n = len(ts["attempts"])
    # the attempt's files move aside under their number: the next `run` must find no response (a native provider's is written
    # by the session and would otherwise be read again as the new answer) and the record keeps what this attempt said
    for kind in ("response", "request", "pending", "response.transcript"):   # the build stage's files (verify files are numbered by spawn already)
        ext = "jsonl" if kind.endswith("transcript") else "json"
        src = work_path(d, "%s.%s.%s" % (task_id, kind, ext))
        if os.path.exists(src):
            os.replace(src, work_path(d, "%s.%s.%d.%s" % (task_id, kind, n, ext)))
    save_state(d, state)
    commit_record(target, os.path.basename(d), message or "retry %s (attempt %d kept)" % (task_id, n))
    return n


def disputed_files(disputed):
    """The files a dispute names: `test_a.py::test_x` -> `test_a.py`."""
    return sorted({str(x.get("test", "")).split("::")[0].split(" ")[0] for x in disputed if isinstance(x, dict)} - {""})


def writes_tests(task):
    """Is a task's `tests` what it writes (not what it protects)? A nitpick task's are; so are a task's that no check decides
    (a tests task the session took over, or did itself). A task with a check protects its `tests`: its judgment restores them."""
    return bool(task.get("tests")) and (task.get("role") == "nitpick" or not task.get("checks"))


def tests_writer(plan, state, task, files):
    """The task that wrote these tests — the newest done one whose `tests` it wrote and that names any of them."""
    found = [t for t in all_tasks(plan, state) if t.get("id") != task["id"] and writes_tests(t) and set(t.get("tests") or []) & set(files)
             and state["tasks"].get(t["id"], {}).get("status") == "done"]
    return found[-1] if found else None


def amending_tasks(plan, state, task, files):
    """The open tasks amending these tests for a dispute: the build that disputed them waits for them."""
    return [t["id"] for t in all_tasks(plan, state) if t.get("id") != task["id"] and state["tasks"].get(t["id"], {}).get("amending")
            and state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped") and set(t.get("tests") or []) & set(files)]


def rebaseline(target, d, task, ts):
    """The tests this build disputed were amended by the task that owns them; they are the contract again — in the build's
    start (so the amendment is not read as the build changing them) and in its kept copies (so a judgment that restores
    the contract's tests restores the amended ones, not what the dispute was about)."""
    now = dirty(target) or {}
    files = ts.pop("rebaseline")
    for f in files:
        ts.setdefault("start", {})[f] = now.get(f) or file_hash(target, f)
    keep_contract_tests(target, d, {"id": task["id"], "tests": files})
    ts.setdefault("rebaselined", []).append({"tests": files, **stamp()})


def route_dispute(target, d, state, plan, task, disputed, judgment=None):
    """Some of the contract's tests contradict the contract. Tests are not the build's to change and not a person's to fix by
    hand between attempts: the task that wrote them is reopened with the dispute (`amending`), and the build waits,
    re-baselines those tests once they are amended, and goes out again. `judgment` None: a provider's build said so in its
    answer — routed by chongdae, bounded like any automatic resend, and only to a writer on record. A judgment (`chongdae
    dispute`): the session or a person said so — routed as that judgment; with no writer on record, a tests task is made
    for the lock's nitpick (else the session). Returns the writer's id when routed; None leaves the stop to a person."""
    files = sorted(set(disputed_files(disputed)) & set(task.get("tests") or []))
    if not files:
        return None
    writer = tests_writer(plan, state, task, files)
    bts = state["tasks"][task["id"]]
    if judgment is None:
        routed = sum(1 for a in bts.get("attempts", []) if str((a.get("retried") or {}).get("auto", "")).startswith("tests disputed"))
        if not writer or routed >= AUTO_RESENDS:
            return None
        reopened = {"by": "chongdae", "auto": "tests disputed by %s" % task["id"]}
    else:
        reopened = {**{k: v for k, v in judgment.items() if k not in ("at", "chongdae")}, "disputed": "tests disputed by %s" % task["id"]}
    made = writer is None
    if made:
        writer = dispute_tests_task(target, d, state, plan, task, files, disputed)
    wts = state["tasks"][writer["id"]]
    if not made:
        attempt = {**(wts.pop("response", None) or {"status": "session"}), "reopened": {**reopened, **stamp()}, "disputed-tests": disputed,
                   **{k: wts.pop(k) for k in ("answered", "done", "touched") if k in wts}}
        wts.setdefault("attempts", []).append(attempt)
        n = len(wts["attempts"])
        for kind in ("response", "request", "pending", "response.transcript"):
            ext = "jsonl" if kind.endswith("transcript") else "json"
            src = work_path(d, "%s.%s.%s" % (writer["id"], kind, ext))
            if os.path.exists(src):
                os.replace(src, work_path(d, "%s.%s.%d.%s" % (writer["id"], kind, n, ext)))
    wts["status"] = "todo"
    wts["amending"] = disputed
    wts.pop("reported", None)
    # the amendment is measured from now, with the disputed files as the build protects them: a fix the session already made
    # in the tree (and a judgment then restored, or not yet) counts as the amendment
    wts["start"], wts["start-head"] = dirty(target) or {}, head_sha(target)
    for f in files:
        kept = work_path(d, os.path.join("contract-tests", task["id"], f))
        if os.path.isfile(kept):
            wts["start"][f] = file_hash(d, os.path.relpath(kept, d))
    bts["rebaseline"] = files
    what = "%s %s to amend %s" % (writer["id"], "made" if made else "reopened", ", ".join(files))
    retried = {"by": "chongdae", "auto": "tests disputed; " + what} if judgment is None else {**judgment, "disputed": "tests disputed; " + what}
    resend(target, d, state, task["id"], retried, "dispute %s: %s" % (task["id"], what))
    print("  %s disputed %d test(s) in %s: %s %s with the dispute (%s does it); the build waits and goes out again after"
          % (task["id"], len(disputed), ", ".join(files), writer["id"], "made" if made else "reopened",
             "the session" if wts.get("taken") or writer.get("role") == "session" else writer.get("role")))
    return writer["id"]


def dispute_tests_task(target, d, state, plan, task, files, disputed):
    """No task on record wrote the disputed tests: a tests task for them, the lock's nitpick when it declares one, else the
    session's — named after the build, its brief the dispute."""
    role = "nitpick" if providers(target, plan).get("nitpick") is not None else "session"
    tid, i = task["id"] + "-tests", 1
    while tid in state["tasks"] or any(t.get("id") == tid for t in plan.get("tasks", [])):
        i += 1
        tid = "%s-tests-%d" % (task["id"], i)
    tdef = {"id": tid, "role": role, "brief": "Amend %s: %s disputed them — %s" % (", ".join(files), task["id"], "; ".join(
                "%s: %s" % (x.get("test"), x.get("why")) for x in disputed if isinstance(x, dict))),
            "closes": list(task.get("closes") or []), "needs": [], "checks": [], "tests": files, "gate": None,
            **({"domain": task["domain"]} if task.get("domain") else {})}
    state["tasks"][tid] = {"status": "todo", "def": tdef, "seq": 1 + max([t.get("seq", 0) for t in state["tasks"].values()] or [0]),
                           "added": now_utc(), "non-claims": ["no check decides this task; done means the agent said so"]}
    return tdef


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


# ---------------------------------------------------------------- judgments: each one a record-only commit

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


def cmd_init(args):
    target = args.target
    if run_dir(target) and load_state(run_dir(target)).get("status") == "running":
        raise SystemExit("a run is already in progress: %s — finish it or remove it" % run_dir(target))
    # Run ids are unique across machines (date + random), so runs made on different branches merge as distinct directories.
    # UTC, so the id's lexical order approximates creation order regardless of timezone — an approximation for humans only;
    # real order is `based_on`/`landed` ancestry in git, never a clock (id order can still invert under clock skew) — recorded
    # for a reader; no command sorts by it.
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
        for t in plan.get("tasks", []) if isinstance(plan.get("tasks"), list) else []:
            if isinstance(t, dict) and isinstance(t.get("checks"), list):
                t["checks"] = [portable_argv(c) if isinstance(c, list) else c for c in t["checks"]]
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
    state["created"] = {**stamp(), "based_on": head_sha(target)}   # the commit this run starts from: its place in history is ancestry, not its id's timestamp
    locked = locked_versions(target)
    if locked:
        state["environment"] = {"locked": locked}   # the lock every call in this run ran under, once; a task says `locked` only when it differs
    if getattr(args, "worktree", False):
        state["worktree"] = {"main": os.path.abspath(args.target).replace(os.sep, "/"), "branch": "run/" + run_name}
    save_state(d, state)
    commit_record(target, run_name, "init (%s) — %s" % (plan.get("kind", "?"), plan.get("goal", "")))
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
    checks = [portable_argv(shlex.split(c)) for c in args.check or []]
    # Who does it is the lock's to say, not this session's to assume: a task with checks is a build, and a build goes to the
    # implementer the lock declares; a task that writes the contract's tests goes to the nitpicker. The session does a task
    # itself when nothing is declared for it (a plan section, a model), or when it says so and why — recorded, like a
    # delegation, so a record can show how much of the work the brain did with its own hands.
    declared = providers(args.target, plan)
    due = "implementer" if checks else ("nitpick" if args.tests and not all(os.path.exists(os.path.join(args.target, f)) for f in args.tests) else None)
    due = due if hire(declared, {"role": due, "requires": args.requires})[1] is not None else None
    role, own = args.role, None
    if role is None:
        role = due or "session"
    elif role == "nitpick" and checks:
        # a nitpick task is decided by its tests being red before the build, never by a check of its own: a task that
        # carries one is a build. A site sent "move the helpers into tests/support.py" to the nitpicker with a check; the
        # nitpicker did its own job (wrote a structure test) and the check failed with nobody having moved anything
        raise SystemExit("--role nitpick with --check: a nitpick task writes the contract's tests and has no check of its own (the build that protects "
                         "them has the check); a task decided by a check is a build — leave --role out and the lock's implementer does it")
    elif role == "session" and due:
        if not args.why:
            raise SystemExit("--role session: the lock declares %r for a task like this — say why the session does it itself (--why), "
                             "or leave --role out and %r does it" % (due, due))
        own = {"instead-of": due, "why": args.why, "by": args.by if args.by is not None else me(args.target), **stamp()}
    task = {"id": args.id, "role": role, "brief": args.brief or "", "closes": args.closes or [], "needs": [], "checks": checks,
            "tests": args.tests or [], "gate": "human" if args.gate == "human" else None, **({"domain": args.domain} if args.domain else {}),
            **({"requires": args.requires} if args.requires else {})}
    for when in ("before", "after"):
        if getattr(args, when) is not None:
            task[when] = getattr(args, when)
    problems = [x for x in plan_problems({"artifact-type": "chongdae/plan@1", "goal": "x", "tasks": [task]}) if "needs `path`" not in x]
    # a session build takes its start snapshot now: protected tests it names must exist already, or writing them would read
    # as the build changing its own contract (a provider's build takes its snapshot when spawned, after the tests' task ran)
    if task["role"] == "session" and task["checks"]:
        problems += ["--tests %s: does not exist yet — a session build's start is taken at `add`, so writing its tests after "
                     "would read as the build changing them; write the tests in their own task first (`add`, work, `run`), "
                     "then add this one" % f for f in task["tests"] if not os.path.exists(os.path.join(args.target, f))]
    # `--tests` is two things by role: the tests a task writes (nitpick's, or a task no check decides), or the files a build
    # may not change — its judgment restores them. A task that changes tests cannot also protect them: guin-site's
    # `tests-fix` named the files it corrected with --tests, and its own judgment restored its fix (2026-10-02)
    protects = bool(task["tests"]) and not writes_tests(task)
    if protects:
        for t2 in all_tasks(plan, state):
            o = state["tasks"].get(t2["id"], {})
            restored = set(((o.get("rejected") or {}).get("restored")) or []) & set(task["tests"])
            if o.get("status") == "todo" and restored and o.get("rejected", {}).get("by") == "contract":
                problems.append("--tests %s: %s's judgment restored %s because it changed them — a task with a check protects its --tests the same way, "
                                "so a task that corrects them would have its own fix restored too. If they contradict the contract: "
                                "`chongdae dispute %s --tests %s --why WHY` reopens the task that wrote them (or makes one) and %s keeps the fix; "
                                "if this task builds against them as they are, drop %s first"
                                % (" ".join(task["tests"]), t2["id"], ", ".join(sorted(restored)), t2["id"], " ".join(sorted(restored)), t2["id"], t2["id"]))
    if problems:
        raise SystemExit("task rejected:\n  " + "\n  ".join(problems))
    ts = {"status": "todo", "def": task, "seq": 1 + max([t.get("seq", 0) for t in state["tasks"].values()] or [0]), "added": now_utc()}
    if own:
        ts["self-performed"] = own
    if task["role"] == "session":
        ts["start"] = dirty(args.target)   # the session works between `add` and `run`: what changed is measured from now
        ts["start-head"] = head_sha(args.target)
        keep_contract_tests(args.target, d, task)
    # a provider's task starts when `run` spawns it (`start` is taken then): a build added alongside its test task must not see the test-writer's file as its own change
    if not task["checks"]:
        ts["non-claims"] = ["no check decides this task; done means the agent said so"]
    state["tasks"][args.id] = ts
    save_state(d, state)
    if task["role"] == "session":
        print("added %s to %s%s%s. Work, then `chongdae run`." % (args.id, os.path.basename(d), " (no checks — done will be a claim, recorded as such)" if not task["checks"] else "",
                                                                  " — the session does it itself, instead of the lock's %s: recorded" % own["instead-of"] if own else ""))
    else:
        key = hire(declared, task)[0]
        print("added %s to %s — %s does it (%s). `chongdae run` sends it out." % (args.id, os.path.basename(d), key,
              ("the lock's alternate for %s" % ", ".join(task["requires"])) if key != task["role"] else "the lock's provider" if args.role is None else "as asked"))
    if task["tests"]:
        if protects:
            print("  --tests: files %s may not change — %s (the contract decides, not the builder). A task that corrects tests "
                  "names them without a check; when a build's tests are wrong, `chongdae dispute %s --tests FILE... --why WHY`."
                  % (args.id, "its judgment restores any change it makes to them", args.id))
            others = [t2["id"] for t2 in all_tasks(plan, state) if t2["id"] != args.id and state["tasks"].get(t2["id"], {}).get("status") == "todo"
                      and set(t2.get("tests") or []) & set(task["tests"]) and not writes_tests(t2)]
            if others:
                print("  note: %s protect%s %s too" % (", ".join(others), "s" if len(others) == 1 else "", ", ".join(sorted(set(task["tests"]) & {f for t2 in all_tasks(plan, state) if t2["id"] in others for f in t2.get("tests") or []}))))
        else:
            print("  --tests: the tests %s writes (%s) — a build that names them protects them; this task may change them."
                  % (args.id, "the lock gives it to nitpick" if task["role"] == "nitpick" else "no check decides it"))
    return 0


def cmd_take(args):
    """The session finishes a task its hired hands could not: the work is in the tree (a sandbox stopped the worker, a guard
    judged the tree the session was also writing), and `drop` would record it as not done — three of guin-site's drops were
    done work (2026-09-30). The task becomes the session's: self-performed instead of its role, with the reason; the stopped
    attempt stays in `attempts`; `run` then decides it like any session task — its checks, the verifier, the gate."""
    d = run_dir(args.target)
    plan, state = (load(os.path.join(d, "plan.json")), load_state(d)) if d else ({}, {})
    if plan.get("kind") != "session" or state.get("status") != "running":
        raise SystemExit("no session run in progress — `take` is for a session run's own tasks")
    ts = state["tasks"].get(args.task)
    if not ts:
        raise SystemExit("no task %s" % args.task)
    if ts["status"] != "todo":
        raise SystemExit("%s is %s — only an open task can be taken" % (args.task, ts["status"]))
    task = ts["def"]
    hands = providers(args.target, plan).get(task["role"])
    if ts.get("taken") or hands == "session" or task["role"] == "session":
        raise SystemExit("%s is already the session's" % args.task)
    who = args.by if args.by is not None else me(args.target)
    taken = {"from": task["role"], "why": args.why, "by": who, **stamp()}
    ts["taken"] = taken
    ts["self-performed"] = {"instead-of": task["role"], "why": args.why, "by": who, "taken-over": True, **stamp()}
    for key in ("touched_by_provider", "checks-ran-overruled", "accepted"):
        ts.pop(key, None)
    was = ts.pop("performed_by", None)   # who made the stopped attempt goes with that attempt; the task's hands are the session's now
    ts.setdefault("non-claims", []).append("%s: taken over by the session from %s: %s" % (args.task, task["role"], args.why))
    if ts.get("response") or ts.get("rejected"):
        n = resend(args.target, d, state, args.task, {"by": who, "taken": args.why}, message="take %s: %s" % (args.task, args.why))
        if was:
            ts["attempts"][-1]["performed_by"] = was
            save_state(d, state)
        print("took %s from %s — its attempt %d stays in the record; the session finishes it, then `chongdae run` decides it" % (args.task, task["role"], n))
    else:
        save_state(d, state)
        commit_record(args.target, os.path.basename(d), "take %s: %s" % (args.task, args.why))
        print("took %s from %s — the session does it; then `chongdae run` decides it" % (args.task, task["role"]))
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
    if ts.get("response") and (ts["response"].get("status") == "done" or touched_files(args.target, ts.get("start"), ts.get("start-head"))):
        print("note: %s's hands changed the tree — if that work stands, `chongdae take %s --why` finishes it as done work instead" % (args.task, args.task))
    ts["status"] = "dropped"
    ts["dropped"] = {"why": args.why, "by": args.by if args.by is not None else me(args.target), **stamp()}
    ts["touched"] = touched_files(args.target, ts.get("start"), ts.get("start-head"))   # what changed in its window stays attributed to it, dropped or not
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
    ts.setdefault("unstaged", {})[args.role] = {"why": args.why, "by": args.by if args.by is not None else me(args.target), **stamp()}
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
    state["status"] = "complete"   # which tasks stayed open is the tasks' own status; `report`/`status` recount it, nothing read a copy
    state["ended"] = stamp()
    save_state(d, state)
    wrote = place_reviewer(args.target, d, state, plan)
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "close — %s (%d done, %d open)" % (plan.get("goal", ""), sum(ts["status"] == "done" for ts in state["tasks"].values()), len(open_)), also=wrote)
    dropped = [tid for tid, ts in state["tasks"].items() if ts["status"] == "dropped"]
    print("closed %s: %d task(s) done, %d open (%s)%s. non-claims: %s" % (os.path.basename(d), sum(ts["status"] == "done" for ts in state["tasks"].values()), len(open_), ", ".join(open_) or "-",
                                                                 ", %d dropped (%s)" % (len(dropped), ", ".join(dropped)) if dropped else "", non_claims(state) or "none"))
    if wt:
        return merge_back(args.target, wt, os.path.basename(d))
    return 0


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
    ts["confirmed"] = {**({"by": args.by} if args.by else {**delegation_record(d, args.delegated, "confirm"), "verifier": verdict}), **stamp()}
    ts["status"] = "done"
    ts["done"] = {k: ts["confirmed"][k] for k in ("at", "chongdae")}   # the confirmation is the moment it became done
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "confirm %s (%s)" % (args.task, "by " + args.by if args.by else "delegated"))
    print("confirmed %s (%s)" % (args.task, "by " + args.by if args.by else "delegated: " + args.delegated))
    return 0


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
    who = {**({"by": args.by} if args.by else delegation_record(d, args.delegated, "accept")), **stamp()}
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


def cmd_retry(args):
    """A human sends a stopped task out again. The stopped attempt (and its review) stays in the record; the next call receives it."""
    d = run_dir(args.target)
    state = load_state(d)
    ts = state["tasks"].get(args.task, {})
    stopped = (ts.get("response") or {}).get("status") not in (None, "done") or ts.get("rejected")
    # a provider's decisions wait for `accept`; not accepting them and sending the task out again is the other answer the stop
    # offers — the work is rejected, and the attempt (decisions included) stays in the record
    stopped = stopped or ((ts.get("response") or {}).get("decisions") and not ts.get("accepted"))
    if ts.get("status") != "todo" or not stopped:
        raise SystemExit("%s is not stopped on a provider response or a rejection (status %s, response %s)" % (args.task, ts.get("status"), (ts.get("response") or {}).get("status")))
    if not (args.by or args.delegated):
        raise SystemExit("say who sent it again (--by) or why the human delegated it (--delegated)")
    judgment = {"by": args.by} if args.by else delegation_record(d, args.delegated, "retry")
    plan, to = load(os.path.join(d, "plan.json")), ""
    if args.requires:
        # what the work requires of its sandbox, said on the task now that a member's sandbox lacked it: the request names it
        # (`needs`), and the lock's `<role>@<cap>` alternate, when it has one, is hired instead of the plain role
        task = ts["def"] if "def" in ts else next((t for t in plan.get("tasks", []) if t.get("id") == args.task), None)
        if task is None:
            raise SystemExit("no task %s in the plan" % args.task)
        task["requires"] = list(dict.fromkeys(list(task.get("requires") or []) + list(args.requires)))
        judgment["requires"] = task["requires"]
        if "def" not in ts:
            save(os.path.join(d, "plan.json"), plan)
        key = hire(providers(args.target, plan), task)[0]
        to = " — it requires %s now; %s" % (", ".join(task["requires"]), "the lock's %s does it" % key if key != task["role"]
                                             else "the lock has no %s@%s, so the plain %s does it again" % (task["role"], "+".join(task["requires"]), task["role"]))
    n = resend(args.target, d, state, args.task, judgment)
    print("retry %s: attempt %d kept in the record%s; `chongdae run` sends the task out again with it attached" % (args.task, n, to))
    return 0


def cmd_dispute(args):
    """The session (or a person) says some of a build's protected tests contradict the contract — the route a provider's
    build has in its answer's `disputed-tests`. guin-site, 2026-10-02: a session build found two test errors and a parser
    the machine could not load; every judgment of the build restored the tests, so the fix could not land, and a fix task
    added with `--tests` protected the very files it fixed. Recorded as a judgment; the task that wrote those tests is
    reopened with the dispute (or a tests task is made when none is on record), and once it is done the build takes the
    amended files as its contract, so its next judgment keeps the fix."""
    d = run_dir(args.target)
    plan, state = (load(os.path.join(d, "plan.json")), load_state(d)) if d else ({}, {})
    if state.get("status") != "running":
        raise SystemExit("no run in progress")
    ts = state["tasks"].get(args.task)
    task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), None)
    if not ts or not task:
        raise SystemExit("no task %s" % args.task)
    if ts["status"] != "todo":
        raise SystemExit("%s is %s — a dispute is about the contract of an open build" % (args.task, ts["status"]))
    protected = list(task.get("tests") or []) if not writes_tests(task) else []
    if not protected:
        raise SystemExit("%s protects no tests (it has %s) — nothing of its contract to dispute; a task that writes tests changes them itself"
                         % (args.task, "no --tests" if not task.get("tests") else "no check: its --tests are what it writes"))
    files = []
    for f in args.tests:
        f = f.replace("\\", "/").strip()
        while f.startswith("./"):
            f = f[2:]
        files.append(f.split("::")[0])
    stray = [f for f in files if f not in protected]
    if stray:
        raise SystemExit("%s: not among %s's protected tests (%s)" % (", ".join(stray), args.task, ", ".join(protected)))
    judgment = {**({"delegated": delegation_record(d, args.delegated, "dispute")["delegated"]} if args.delegated else
                   {"by": args.by if args.by is not None else me(args.target)}), "why": args.why}
    owner = tests_writer(plan, state, task, files)
    if owner is None and amending_tasks(plan, state, task, files):
        raise SystemExit("%s: already being amended by %s — `chongdae run` once it is done" % (", ".join(files), ", ".join(amending_tasks(plan, state, task, files))))
    writer = route_dispute(args.target, d, state, plan, task, [{"test": f, "why": args.why, "by": "session"} for f in files], judgment=judgment)
    wdef = next(t for t in all_tasks(plan, state) if t.get("id") == writer)
    hands = "the session" if state["tasks"][writer].get("taken") or hire(providers(args.target, plan), wdef)[1] == "session" else wdef.get("role")
    print("dispute %s: %s %s to amend %s — %s; %s waits for it, then takes the amended tests as its contract. `chongdae run` next."
          % (args.task, writer, "made" if owner is None else "reopened", ", ".join(files),
             "the session amends them (`run` stops for it until they change)" if hands == "the session" else "%s amends them" % hands, args.task))
    return 0


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
         {"artifact-type": "chongdae/delegation@1", "id": did, "scope": scope, "why": args.why, "by": args.by, **stamp()})
    commit_record(args.target, os.path.basename(d), "delegate %s (%s)" % (did, ",".join(scope)))
    print(did)
    return 0


# ---------------------------------------------------------------- reports: what the record says

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
        for path in (git("diff", "--name-only", "-z", "--no-renames", "%s..HEAD" % args.since, "--", ".") or "").split("\0"):
            if path:
                changed.add(path.replace("\\", "/"))
    changed.update(status_paths(target) or [])
    prefix = (git("rev-parse", "--show-prefix") or "").strip().replace("\\", "/")
    changed = {p[len(prefix):] if prefix and p.startswith(prefix) else p for p in changed}
    changed = {p for p in changed if not p.startswith(record_paths(target)) and p != ".gitignore"}   # records, machine-local state, the host's settings, the environment: the lock says which paths those are (each product declares its own); hunsu's own report covers the environment
    declared = outside_runs(target)
    by_procedure = sorted(p for p in changed if under(p, declared))
    changed -= set(by_procedure)
    if declared:   # not reported is not unseen: the reviewer is told what was left out and how much of it changed there
        findings.append({"kind": "non-claim", "where": "settings.chongdae.outside-runs",
                         "text": "%s: the project's own procedure, declared in hunsu.json; %d file(s) changed there since %s are not reported as outside-run"
                                 % (", ".join(declared), len(by_procedure), args.since or "the beginning")})
    claimed, unattributed = set(), []
    # Only a run whose work falls in the range claims a change in it: with --since, the runs whose record was not complete at
    # REV (the ones this report reviews). An earlier run's work was in the tree at REV already — its `touched` names paths, not
    # changes, and a path it once touched hid any later change made there outside a run. A run complete at REV whose work was
    # committed only after REV now shows as outside-run: a change the reviewer looks at, rather than one nobody sees.
    since_runs = runs_since(target, args.since) if args.since else None
    for r in all_runs(target):
        name, plan, state = os.path.basename(r), load(os.path.join(r, "plan.json")), load_state(r)
        if state.get("status") != "complete" or (since_runs is not None and name not in since_runs):
            continue
        for task in all_tasks(plan, state):
            ts = state["tasks"].get(task["id"], {})
            if ts.get("status") in ("done", "dropped") and "touched" in ts:   # a dropped task's window is still a claim on what changed in it
                claimed.update(ts["touched"] or [])
            elif ts.get("status") == "done" and task.get("checks"):
                unattributed.append("%s/%s" % (name, task["id"]))
    for path in sorted(changed - claimed):
        findings.append({"kind": "outside-run", "where": path, "files": [path],
                         "text": "changed since %s; no run completed since then recorded touching it" % args.since if args.since
                                 else "changed; no completed run recorded touching it"})
    if unattributed:
        findings.append({"kind": "unattributed", "where": ", ".join(unattributed),
                         "text": "these runs completed without recording touched files; changes they made cannot be told from work outside runs"})
    # what no human decided, and what nobody claims
    for r in all_runs(target):
        name, plan, state = os.path.basename(r), load(os.path.join(r, "plan.json")), load_state(r)
        if since_runs is not None and name not in since_runs:
            continue   # --since: what happened since that revision — a run whose record already existed there was reviewed then

        def deleg_text(v, run_d=r):
            # a ref points at a declared delegation: show whose words it points at, or the report's reader has an id and no reason
            if not isinstance(v, dict):
                return v
            rec = load(os.path.join(run_d, "delegations", "%s.json" % v.get("ref")))
            return "ref %s (%s: %s)" % (v.get("ref"), rec.get("by") or "?", rec.get("why") or "?") if rec else "ref %s" % v.get("ref")

        stamps = {}   # literal delegated reason -> where it was used, within this one run (refs are exempt: pointing at one declared judgment is their purpose)

        def stamp(v, where):
            if isinstance(v, str):
                stamps.setdefault(v, []).append(where)

        for tid, ts in state.get("tasks", {}).items():
            own = ts.get("self-performed")
            if isinstance(own, dict):
                # the brain did with its own hands what the lock had hired someone for: a fact of the record, with the reason —
                # and a reason stamped across tasks is one decision claiming to be many, like a delegation's
                stamp(own.get("why"), "%s/%s" % (name, tid))
                findings.append({"kind": "self-performed", "where": "%s/%s" % (name, tid), "layer": "observation",
                                 "text": "the session did this itself instead of the lock's %s (%s): %s" % (own.get("instead-of"), own.get("by"), own.get("why"))})
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
                # a verifier's reject outlives the attempt it stopped: the reviewer's ledger sees it, and sees it again if it recurs.
                # Once a later attempt of the task was accepted by the verifier, the reject was answered by that work: a fact of
                # the record then, not a charge someone still owes an answer to
                later_ok = (ts.get("review") or {}).get("verdict") == "accept"
                for f in ((a.get("review") or {}).get("findings") or []):
                    findings.append({"kind": "verifier-reject", "where": "%s/%s attempt %d: %s" % (name, tid, i, f.get("where", "")),
                                     **({"layer": "observation"} if later_ok else {}),
                                     "text": "%s: %s — record: \u201c%s\u201d — tree: \u201c%s\u201d%s" % (f.get("kind"), f.get("why"), f.get("record_quote"), f.get("tree_quote"),
                                                                          " (a later attempt was accepted by the verifier)" if later_ok else "")})
        for tid, ts in state.get("tasks", {}).items():   # a drop's reason is a judgment like the rest
            stamp((ts.get("dropped") or {}).get("why"), "%s/%s drop" % (name, tid))
        # one reason stamped across judgments with a different tail each time: guin-site opened ten reasons with the same clause
        # ("소유자가 구현을 맡김"), each with its own suffix, and the exact-string count saw ten judgments
        leads = {}
        for reason, wheres in stamps.items():
            lead = re.split(r"[:(（—–]", " ".join(str(reason).split()), 1)[0].strip()
            if len(lead) >= 8 and lead != reason.strip():
                leads.setdefault(lead, set()).add(reason)
        for lead, reasons in sorted(leads.items()):
            wheres = [w for r in sorted(reasons) for w in stamps[r]]
            if len(reasons) >= 2 and len(wheres) >= 3:
                findings.append({"kind": "delegation-stamp", "where": ", ".join(wheres),
                                 "text": "%d delegated reasons open with the same clause %r (%d judgments) — one decision written as many; "
                                         "declare it once (`chongdae delegate`) and reference it, or give each judgment its own reason" % (len(reasons), lead, len(wheres))})
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
    # a record written by a build that is not a release: it names a build nobody can install
    for r in all_runs(target):
        name = os.path.basename(r)
        for f in [os.path.join(r, "state.json")] + sorted(glob.glob(os.path.join(r, "tasks", "*.json"))):
            w = str(load(f).get("written_by", ""))
            if "+g" in w and git("ls-files", "--error-unmatch", os.path.relpath(f, target)) is not None:
                findings.append({"kind": "unreleased-writer", "where": os.path.relpath(f, target).replace(os.sep, "/"),
                                 "text": "committed as written by %s — a build that is not a release (its version carries +g<commit>); nobody can install what wrote it" % w})
    print(json.dumps({"artifact-type": "dwitbuk/findings@1", "source": "chongdae", "findings": findings}, ensure_ascii=False, indent=1))
    return 0


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
    # the verdict is what is printed and the exit code — a merge run's task carries it. A `.chongdae/rechecks/<time>.json` was
    # filed here until 1.12.1, read by nothing and never committed while the README said it was
    return 1 if red else 0


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


# ---------------------------------------------------------------- show: what happened in a run, for a reader

def as_utc(at):
    """A recorded time (ours: `+00:00`; git's: the committer's offset; a host's: `Z`) as an aware UTC datetime, or None."""
    import datetime
    try:
        t = datetime.datetime.fromisoformat(str(at).strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return (t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)).astimezone(datetime.timezone.utc)


def when(at, day=None):
    """A time for a reader: `2026-09-30 07:40:03Z`, or only `07:40:03Z` on the day already named."""
    t = as_utc(at)
    if t is None:
        return str(at) if at else "?"
    return t.strftime("%H:%M:%SZ") if day and t.strftime("%Y-%m-%d") == day else t.strftime("%Y-%m-%d %H:%M:%SZ")


def span(a, b):
    """The time between two recorded moments, `1h 38m` / `4m 12s`; None when either is unknown."""
    ta, tb = as_utc(a), as_utc(b)
    if ta is None or tb is None:
        return None
    s = int((tb - ta).total_seconds())
    return seconds_text(s) if s >= 0 else None


def seconds_text(s):
    return "%dd %dh" % (s // 86400, s % 86400 // 3600) if s >= 86400 else "%dh %02dm" % (s // 3600, s % 3600 // 60) if s >= 3600 else "%dm %02ds" % (s // 60, s % 60)


def record_commits(target, run_name):
    """The run's record commits, oldest first: [(committer time, subject)]. A run recorded before chongdae kept `ended` and
    `done` is timed from these — the engine committed each judgment as it was made."""
    import subprocess
    done = subprocess.run(["git", "log", "--reverse", "--format=%cI%x1f%s", "--", "%s/%s/" % (RUNS, run_name)], cwd=target,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [tuple(l.split("\x1f", 1)) for l in (done.stdout if done.returncode == 0 else "").splitlines() if "\x1f" in l]


def run_times(target, d, state, commits=None):
    """(created at, its source, ended at, its source) — the record's own times, else the record commits' (source "git")."""
    name = os.path.basename(d)
    commits = record_commits(target, name) if commits is None else commits
    created, c_src = (state.get("created") or {}).get("at"), "record"
    if not created and commits:
        created, c_src = commits[0][0], "git"
    ended, e_src = (state.get("ended") or {}).get("at"), "record"
    if not ended and state.get("status") == "complete":
        closing = [at for at, subj in commits if re.match(r"%s: (close|complete) — " % re.escape(name), subj)]
        ended, e_src = (closing[-1], "git") if closing else ((commits[-1][0], "git: the run's last record commit") if commits else (None, None))
    return created, c_src, ended, e_src


def deleg_words(run_d, v):
    """A delegated judgment's reason: its own words, or the declared delegation a ref points at (who, why)."""
    if not isinstance(v, dict):
        return str(v)
    rec = load(os.path.join(run_d, "delegations", "%s.json" % v.get("ref")))
    return "ref %s (%s: %s)" % (v.get("ref"), rec.get("by") or "?", rec.get("why") or "?") if rec else "ref %s" % v.get("ref")


def judged_by(run_d, j):
    """Who made a judgment: `by NAME`, `delegated: WHY`, or chongdae itself (`auto: WHY`)."""
    if not isinstance(j, dict):
        return "?"
    if "delegated" in j:
        extra = [x for x in ("%s: %s" % (k, j[k] if not isinstance(j[k], list) else ", ".join(j[k])) for k in ("disputed", "why", "requires") if j.get(k))]
        return "delegated: " + deleg_words(run_d, j["delegated"]) + (" (%s)" % "; ".join(extra) if extra else "")
    if j.get("auto"):
        return "by %s (auto: %s)" % (j.get("by", "chongdae"), j["auto"])
    if j.get("taken"):
        return "by %s (taken: %s)" % (j.get("by", "?"), j["taken"])
    extra = [x for x in ("%s: %s" % (k, j[k] if not isinstance(j[k], list) else ", ".join(j[k])) for k in ("disputed", "why", "requires") if j.get(k))]
    return "by %s%s" % (j.get("by") or "?", " (%s)" % "; ".join(extra) if extra else "")


def author_text(by):
    """An author line for a reader: provider, what ran, host, model, effort — and what its trace says it did."""
    if not isinstance(by, dict) or not by:
        return "nobody recorded"
    p = by.get("provider", "?")
    head = [p]
    if p in ("command", "native"):
        argv = [str(a) for a in by.get("argv") or []]
        head.append(next((a for a in argv if "{plugin:" in a), None) or (argv[1] if len(argv) > 1 else (argv[0] if argv else "?")))
    detail = [x for x in (by.get("host"), by.get("model"), "effort %s" % by["effort"] if by.get("effort") else None,
                          "%s turns" % by["turns"] if by.get("turns") is not None else None,
                          "$%s" % by["cost_usd"] if by.get("cost_usd") is not None else None) if x]
    if by.get("model-unknown"):
        detail.append("model unknown: %s" % by["model-unknown"])
    text = " ".join(head) + (" (%s)" % ", ".join(detail) if detail else "")
    tr = by.get("trace") or {}
    if tr:
        bits = ["changed %d file(s)" % len(tr.get("changed") or [])]
        if "commands-run" in tr:
            bits.append("%s command(s)%s" % (tr["commands-run"], " (%s failed)" % tr["commands-failed"] if tr.get("commands-failed") else ""))
        text += " — " + ", ".join(bits)
    if isinstance(by.get("relayed_by"), dict):
        text += "; relayed by " + author_text({k: v for k, v in by["relayed_by"].items() if k != "trace"})
    return text


def task_story(run_d, task, ts, day, run_end):
    """Every line a reader needs about one task, in the order it happened — text whole, never cut."""
    tid, role = task.get("id"), task.get("role", "?")
    out = ["", "%s  %s  (%s)" % (tid, ts.get("status", "?"), role)]
    pad = "    "
    if task.get("brief"):
        out.append("  brief: %s" % task["brief"])
    facts = [("closes " + ", ".join(task["closes"])) if task.get("closes") else None,
             ("domain " + task["domain"]) if task.get("domain") else None,
             ("tests " + ", ".join(task["tests"])) if task.get("tests") else None,
             ("requires " + ", ".join(task["requires"])) if task.get("requires") else None,
             ("needs " + ", ".join(task["needs"])) if task.get("needs") else None,
             ("gate " + json.dumps(task["gate"], ensure_ascii=False) if isinstance(task.get("gate"), dict) else "gate human") if task.get("gate") else None,
             ("before " + ", ".join(task["before"])) if task.get("before") else None,
             ("after " + ", ".join(task["after"])) if task.get("after") else None,
             ("claimed by " + ts["claimed_by"]) if ts.get("claimed_by") else None]
    if any(facts):
        out.append("  " + " · ".join(f for f in facts if f))
    # who did it: the role, and who stood in it
    own = ts.get("self-performed")
    if isinstance(own, dict):
        out.append("  self-performed: the session instead of the lock's %s — by %s at %s: %s" % (own.get("instead-of"), own.get("by"), when(own.get("at"), day), own.get("why")))
    if isinstance(ts.get("taken"), dict):
        tk = ts["taken"]
        out.append("  taken from %s by %s at %s: %s" % (tk.get("from"), tk.get("by"), when(tk.get("at"), day), tk.get("why")))
    if ts.get("amending") and ts.get("status") not in ("done", "dropped", "skipped"):
        out.append("  amending (disputed): %s" % "; ".join("%s — %s" % (x.get("test"), x.get("why")) for x in ts["amending"] if isinstance(x, dict)))
    if ts.get("performed_by"):
        hands = "session" if ts.get("taken") or role == "session" else (ts["performed_by"].get("as") or role)
        out.append("  who: %s%s" % ("" if hands == "session" else hands + " → ", author_text(ts["performed_by"])))
    # the attempts: each one's answer, its verdict with every finding, and the judgment that sent it again
    attempts = list(ts.get("attempts") or [])
    current = {k: ts[k] for k in ("review", "rejected", "answered", "verdict-given") if k in ts}
    if ts.get("response"):
        current = {**ts["response"], **current}
    if current:
        attempts.append({**current, "_current": True})
    for i, a in enumerate(attempts, 1):
        status = a.get("status") or ("session" if a.get("_current") else "?")
        line = "  attempt %d: %s" % (i, status)
        if (a.get("answered") or {}).get("at"):
            line += ", answered %s" % when(a["answered"]["at"], day)
        out.append(line)
        if a.get("summary"):
            out.append(pad + "said: %s" % a["summary"])
        if isinstance(a.get("performed_by"), dict):
            out.append(pad + "by: %s" % author_text(a["performed_by"]))
        for v in a.get("verified") or []:
            out.append(pad + "it ran: %s -> exit %s" % (v.get("check"), v.get("exit")) if isinstance(v, dict) else pad + "it ran: %s" % v)
        for x in a.get("decisions") or []:
            out.append(pad + "decided: %s — chose %r (alternatives: %s)" % (x.get("what"), x.get("chosen"), ", ".join(x.get("alternatives") or []) or "-"))
        failed = (a.get("validation") or {}).get("failed")
        if failed:
            out.append(pad + "its report was refused: %s" % ", ".join(str(f) for f in failed))
        for n in a.get("non-claims") or []:
            out.append(pad + "does not claim: %s" % n)
        rv = a.get("review") or {}
        if rv:
            out.append(pad + "verifier: %s%s%s" % (rv.get("verdict") or rv.get("status") or "?",
                                                   " at %s" % when(a["verdict-given"]["at"], day) if (a.get("verdict-given") or {}).get("at") else "",
                                                   " — %d finding(s)" % len(rv.get("findings") or []) if rv.get("findings") else ""))
            for f in rv.get("findings") or []:
                out.append(pad + "  %s @ %s: %s — record: “%s” — tree: “%s”" % (f.get("kind"), f.get("where"), f.get("why"), f.get("record_quote"), f.get("tree_quote")))
        rj = a.get("rejected")
        if isinstance(rj, dict) and rj.get("by") != "verifier":
            out.append(pad + "rejected by %s: %s%s" % (rj.get("by"), rj.get("why"), " (restored: %s)" % ", ".join(rj["restored"]) if rj.get("restored") else ""))
        for role_, rec in (a.get("stages") or {}).items():
            out += stage_lines(run_d, role_, rec, day, pad)
        if isinstance(a.get("reopened"), dict):
            out.append(pad + "reopened at %s %s" % (when(a["reopened"].get("at"), day), judged_by(run_d, a["reopened"])))
        if isinstance(a.get("retried"), dict):
            out.append(pad + "retried at %s %s" % (when(a["retried"].get("at"), day), judged_by(run_d, a["retried"])))
    if ts.get("verified_by"):
        out.append("  verified by: %s" % author_text(ts["verified_by"]))
    for role_, rec in (ts.get("stages") or {}).items():
        out += stage_lines(run_d, role_, rec, day, "  ")
    for role_, rec in (ts.get("unstaged") or {}).items():
        out.append("  %s taken off at %s by %s: %s" % (role_, when(rec.get("at"), day), rec.get("by"), rec.get("why")))
    # the checks, and what the record says of their outcome
    checks = task.get("checks") or []
    if checks:
        outcome = ("passed here when the task was produced" if "checks" in ts and ts.get("status") in ("produced", "done")
                   else "never passed here" if ts.get("status") in ("done", "dropped", "skipped") else "not passed yet")
        out.append("  checks (%s):" % outcome)
        out += ["    %s" % " ".join(str(x) for x in c) for c in checks]
    elif ts.get("status") in ("done", "produced") and not task.get("path"):
        out.append("  checks: none — done is the agent's word")
    if isinstance(ts.get("checks-ran-overruled"), dict):
        out.append("  the validator's refusal overruled at %s — the checks passed here: %s" % (when(ts["checks-ran-overruled"].get("at"), day), "; ".join(ts["checks-ran-overruled"].get("refused") or [])))
    for rb in ts.get("rebaselined") or []:
        out.append("  re-baselined at %s: %s" % (when(rb.get("at"), day), ", ".join(rb.get("tests") or [])))
    if isinstance(ts.get("accepted"), dict):
        out.append("  decisions accepted at %s %s" % (when(ts["accepted"].get("at"), day), judged_by(run_d, ts["accepted"])))
    if isinstance(ts.get("confirmed"), dict):
        c = ts["confirmed"]
        stood = "" if "by" in c else (" (verifier: %s)" % c.get("verifier") if c.get("verifier") else " (no verifier)")
        out.append("  confirmed at %s %s%s" % (when(c.get("at"), day), judged_by(run_d, c), stood))
    if isinstance(ts.get("dropped"), dict):
        dr = ts["dropped"]
        out.append("  dropped at %s by %s: %s" % (when(dr.get("at"), day), dr.get("by"), dr.get("why")))
    if "touched" in ts:
        out.append("  touched: %s" % (", ".join(ts["touched"] or []) or "nothing"))
    # its times
    end = (ts.get("done") or {}).get("at") or (ts.get("dropped") or {}).get("at")
    times = ["added %s" % when(ts["added"], day)] if ts.get("added") else []
    if ts.get("status") == "done":
        if end:
            times.append("done %s" % when(end, day))
        elif run_end:
            times.append("done — its time not recorded (an older chongdae); by the run's end, %s" % when(run_end, day))
        else:
            times.append("done — its time not recorded")
    elif ts.get("status") == "dropped" and end:
        times.append("dropped %s" % when(end, day))
    took = span(ts.get("added"), end) if ts.get("added") and end else None
    if took:
        times.append("took %s" % took)
    if times:
        out.append("  " + " · ".join(times))
    for n in ts.get("non-claims") or []:
        if not str(n).startswith("(provider) "):   # the provider's own are its attempt's, said above
            out.append("  non-claim: %s" % n)
    return out


def stage_lines(run_d, role, rec, day, pad):
    """A role hired before or after a task: who answered, what it found (whole), and who accepted it."""
    if rec.get("skipped"):
        return [pad + "%s: skipped (%s)" % (role, rec["skipped"])]
    resp = rec.get("response") or {}
    out = [pad + "%s (%s): %s — %d finding(s)%s" % (role, rec.get("when", "?"), resp.get("status", "no answer"), len(resp.get("findings") or []),
                                                     ", by " + author_text(rec["by"]) if rec.get("by") else "")]
    for f in resp.get("findings") or []:
        out.append(pad + "  %s @ %s: %s — “%s”" % (f.get("kind"), f.get("where", ""), f.get("why", ""), f.get("quote", "")))
    if isinstance(rec.get("accepted"), dict):
        out.append(pad + "  accepted at %s %s" % (when(rec["accepted"].get("at"), day), judged_by(run_d, rec["accepted"])))
    for x in rec.get("failed") or []:
        out.append(pad + "  did not finish: %s — %s" % ((x.get("response") or {}).get("status"), (x.get("response") or {}).get("summary", "")))
    return out


def run_tally(d, plan, state):
    """One run's counts: tasks by status, self-performed/taken, attempts, verifier rejects, delegated judgments."""
    t = {"tasks": 0, "done": 0, "dropped": 0, "open": 0, "skipped": 0, "self": 0, "taken": 0, "attempts": 0, "rejects": 0, "delegated": 0}
    for task in all_tasks(plan, state):
        ts = state["tasks"].get(task["id"], {})
        t["tasks"] += 1
        st = ts.get("status")
        t[st if st in ("done", "dropped", "skipped") else "open"] += 1
        t["self"] += 1 if ts.get("self-performed") else 0
        t["taken"] += 1 if ts.get("taken") else 0
        attempts = ts.get("attempts") or []
        t["attempts"] += len(attempts) + (1 if ts.get("response") or ts.get("review") or ts.get("rejected") or st in ("done", "produced") else 0)
        t["rejects"] += sum(1 for a in attempts + [ts] if (a.get("review") or {}).get("verdict") == "reject")
        judgments = [ts.get("confirmed"), ts.get("accepted")] + [a.get("retried") for a in attempts]
        judgments += [rec.get("accepted") for a in attempts + [ts] for rec in (a.get("stages") or {}).values()]
        t["delegated"] += sum(1 for j in judgments if isinstance(j, dict) and "delegated" in j)
    return t


def tally_text(t):
    return ("tasks %d: %d done, %d dropped, %d open%s · %d self-performed (%d taken) · %d attempt(s) · %d verifier reject(s) · %d delegated"
            % (t["tasks"], t["done"], t["dropped"], t["open"], ", %d skipped" % t["skipped"] if t["skipped"] else "", t["self"], t["taken"], t["attempts"], t["rejects"], t["delegated"]))


def cmd_show(args):
    """What happened in a run, for a person or an agent reading it after: plain text, every reader's text whole. Read-only.
    `--since REV`: one line per run since then, and their totals. `--path FILE`: the tasks that touched it, newest first."""
    target = args.target
    if args.since:
        names = runs_since(target, args.since)
        tot, seconds, rows = None, 0, []
        for r in all_runs(target):
            if os.path.basename(r) not in names:
                continue
            plan, state = load(os.path.join(r, "plan.json")), load_state(r)
            t = run_tally(r, plan, state)
            tot = {k: (tot or {}).get(k, 0) + v for k, v in t.items()}
            created, _, ended, e_src = run_times(target, r, state)
            took = span(created, ended) if ended else None
            if took:
                seconds += int((as_utc(ended) - as_utc(created)).total_seconds())
            rows.append("%s  %s  %s%s  %s — %s" % (os.path.basename(r), state.get("status", "?"), took or "-", " (git)" if took and e_src != "record" else "",
                                                 tally_text(t), plan.get("goal", "")))
        if not rows:
            print("no run since %s" % args.since)
            return 0
        print("\n".join(rows))
        print("total: %d run(s) · %s · %s in runs" % (len(rows), tally_text(tot), seconds_text(seconds)))
        return 0
    if args.path:
        want = args.path.replace("\\", "/").strip()
        while want.startswith("./"):
            want = want[2:]
        want = want.rstrip("/")
        found = 0
        for r in reversed(all_runs(target)):
            plan, state = load(os.path.join(r, "plan.json")), load_state(r)
            hits = [(t, state["tasks"].get(t["id"], {})) for t in all_tasks(plan, state)]
            hits = [(t, ts) for t, ts in hits if any(f == want or f.startswith(want + "/") for f in ts.get("touched") or [])]
            if not hits:
                continue
            created = (state.get("created") or {}).get("at")
            print("%s  %s  %s — %s" % (os.path.basename(r), when(created) if created else "?", state.get("status", "?"), plan.get("goal", "")))
            for t, ts in reversed(hits):
                found += 1
                hands = "session (taken from %s)" % t.get("role") if ts.get("taken") else ((ts.get("performed_by") or {}).get("as") or t.get("role", "?"))
                print("  %s  %s  %s%s — %s" % (t["id"], ts.get("status", "?"), "" if hands == "session" else hands + " → ", author_text(ts.get("performed_by")), t.get("brief") or "(no brief)"))
                if want not in (ts.get("touched") or []):
                    print("    touched there: %s" % ", ".join(f for f in ts["touched"] if f.startswith(want + "/")))
        if not found:
            print("no task in any run recorded touching %s (a task's `touched` never holds the record paths)" % want)
        return 0
    d = run_dir(target, args.run)
    if not d:
        print("no run")
        return 0
    plan, state = load(os.path.join(d, "plan.json")), load_state(d)
    created, c_src, ended, e_src = run_times(target, d, state)
    day = as_utc(created).strftime("%Y-%m-%d") if as_utc(created) else None
    print("run %s — %s, %s" % (os.path.basename(d), plan.get("kind", "?"), state.get("status", "?")))
    print("goal: %s" % plan.get("goal", ""))
    based = (state.get("created") or {}).get("based_on")
    line = "created %s%s%s" % (when(created), " (from git)" if c_src == "git" else "", " on %s" % based[:12] if based else "")
    if (state.get("created") or {}).get("chongdae"):
        line += " by %s" % state["created"]["chongdae"]
    if ended:
        line += " · ended %s%s" % (when(ended, day), " (from %s)" % e_src if e_src != "record" else "")
        took = span(created, ended)
        line += " · took %s" % took if took else ""
    elif state.get("status") == "running":
        line += " · still running"
    print(line)
    if isinstance(state.get("landed"), dict):
        print("landed %s as %s" % (when(state["landed"].get("at"), day), str(state["landed"].get("commit"))[:12]))
    if plan.get("from"):
        print("contract: %s" % plan["from"])
    print(tally_text(run_tally(d, plan, state)))
    tasks = all_tasks(plan, state)
    for task in tasks:
        for l in task_story(d, task, state["tasks"].get(task["id"], {}), day, ended):
            print(l)
    # what is left
    print("")
    open_ = [(t["id"], state["tasks"].get(t["id"], {})) for t in tasks if state["tasks"].get(t["id"], {}).get("status") not in ("done", "skipped", "dropped")]
    if open_:
        print("left open: %s" % ", ".join("%s (%s%s)" % (tid, ts.get("status", "?"), ", rejected by %s: %s" % (ts["rejected"].get("by"), ts["rejected"].get("why"))
                                                          if isinstance(ts.get("rejected"), dict) else "") for tid, ts in open_))
    else:
        print("left open: nothing")
    for n in state.get("non-claims") or []:
        print("run non-claim: %s" % n)
    rv = state.get("reviewed")
    if isinstance(rv, dict):
        print("reviewer at %s (%s): %s%s%s" % (when(rv.get("at"), day), author_text(rv.get("by")), rv.get("said", ""),
                                               " — wrote %s" % ", ".join(rv["wrote"]) if rv.get("wrote") else "", " — exited %s" % rv["exit"] if rv.get("exit") else ""))
    elif state.get("status") == "complete":
        print("reviewer: nothing on record")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="chongdae", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "status", "run", "confirm", "accept", "retry", "recheck", "add", "claim", "take", "drop", "dispute", "unstage", "close", "report", "delegate", "show"):
        p = sub.add_parser(name)
        p.add_argument("--target", default=None, help="the project (default: the nearest directory at or above this one that holds .chongdae/, else this one)")
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
        if name == "retry":
            p.add_argument("--requires", nargs="+", default=None, choices=list(REQUIRES), help="say on the task what its sandbox must give (a member's sandbox lacked it): added to its `requires`; the lock's `<role>@<cap>` alternate, when it has one, is hired")
        if name == "dispute":
            p.add_argument("task", help="the open build whose protected tests are wrong")
            p.add_argument("--tests", nargs="+", required=True, help="the protected test files that contradict the contract (FILE or FILE::test)")
            p.add_argument("--why", required=True, help="what in them contradicts the contract (or cannot run here) — the brief of the amendment")
            p.add_argument("--by", default=None, help="who disputes (default: git user.name)")
            p.add_argument("--delegated", default=None, help="instead of --by: why the human handed this off (or D-xxxx)")
        if name == "report":
            p.add_argument("--since", default=None, help="the revision the last review covered; changes since it are checked against the runs' `touched`")
        if name == "show":
            g = p.add_mutually_exclusive_group()
            g.add_argument("--run", default=None, help="the run to tell (default: the one running, else the newest)")
            g.add_argument("--since", default=None, help="one line per run whose record was not complete at REV, and their totals")
            g.add_argument("--path", default=None, help="the runs and tasks whose `touched` holds this file (or a file under this directory), newest first")
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
        if name == "take":
            p.add_argument("task")
            p.add_argument("--why", required=True, help="why the session finishes it (the worker's sandbox could not, a guard judged the tree the session was also writing)")
            p.add_argument("--by", default=None, help="who decided (default: git user.name)")
        if name == "drop":
            p.add_argument("task")
            p.add_argument("--why", required=True, help="why this task will not be done (mis-specified, superseded, abandoned)")
            p.add_argument("--by", default=None, help="who decided (default: git user.name)")
        if name == "claim":
            p.add_argument("task")
            p.add_argument("--by", default=None, help="who takes it (default: git user.name); an empty string releases")
        if name == "add":
            p.add_argument("id")
            p.add_argument("--role", default=None, help="who does it. Left out, the lock says: a task with --check goes to its `implementer`, one that writes --tests to its `nitpick`, anything else to this session. `session` where the lock declares a provider needs --why (recorded); any role the lock declares can be named outright")
            p.add_argument("--why", default=None, help="with --role session: why this session does the task itself, instead of the provider the lock declares for it")
            p.add_argument("--by", default=None, help="with --role session --why: who decided (default: git user.name)")
            p.add_argument("--brief", default=None)
            p.add_argument("--closes", nargs="*", default=None)
            p.add_argument("--check", action="append", default=None, help="a check argv (quoted); repeatable")
            p.add_argument("--tests", nargs="*", default=None, help="test files. For a nitpick task (or one no --check decides): the tests it writes. For a task with --check: files it may not change — its judgment restores them (`add` says which). A task that corrects a build's tests does not protect them: `chongdae dispute BUILD --tests F --why`")
            p.add_argument("--gate", choices=["human"], default=None)
            p.add_argument("--before", nargs="*", default=None, help="roles to run before the work (their findings must be accepted first): --before quibble")
            p.add_argument("--after", nargs="*", default=None, help="roles to run after the checks pass, before the gate; their findings go to the record: --after newbie")
            p.add_argument("--domain", default=None, help="what kind of artifact the task makes (code, site, plan, ...): carried in every request, so a worker reads it in that domain's terms")
            p.add_argument("--requires", nargs="*", default=None, choices=list(REQUIRES), help="what the work requires of the sandbox its hands run in (network, loopback): sent as the request's `needs`; a member that cannot give it refuses before starting. The lock's `<role>@<cap>[+<cap>]` alternate whose capabilities cover it is hired instead of the plain role")
    args = ap.parse_args(argv)
    if args.target is None:
        # the shell's directory is not the project: `cd tests` and then `chongdae run` found no run there
        args.target = record_root(os.getcwd()) or "."
    return {"init": cmd_init, "status": cmd_status, "run": cmd_run, "confirm": cmd_confirm, "recheck": cmd_recheck, "accept": cmd_accept, "retry": cmd_retry,
            "add": cmd_add, "claim": cmd_claim, "take": cmd_take, "drop": cmd_drop, "dispute": cmd_dispute, "unstage": cmd_unstage, "close": cmd_close, "report": cmd_report, "delegate": cmd_delegate, "show": cmd_show}[args.cmd](args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
