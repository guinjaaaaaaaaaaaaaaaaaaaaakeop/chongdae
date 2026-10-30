"""chongdae — runs a plan: a DAG of roles that produce artifacts, with checks in code and human gates in between.

  init  --goal "..." | --plan FILE     start a run: the bootstrap plan (questions -> plan document -> modeler) or a plan the session agent wrote
  init  --merge [--base REV]            after merging branches: the merge plan — recheck (+ coherence when the lock declares that role) behind a human gate
  init  --session [--goal "..."]        a session run: no plan, tasks added as the work goes (`add`), closed when the session ends (`close`)
  init  ... --worktree                  the run gets its own worktree + branch under .chongdae/wt/ (the shared tree may have other workers); `close` commits and merges it back — a conflict or red recheck becomes a merge run
  add   <id> [--brief ..] [--closes Q..] [--check ARGV]... [--tests F]... [--requires CAP]... [--gate human] [--role R [--why ..]] [--scope PATH..]
                                        a task in the session run; the start snapshot is taken now. The lock says who does it (checks -> implementer,
                                        new tests -> nitpick, else the session; `<role>@<cap>` for a task that --requires cap); `--role session --why`
                                        takes one back, recorded. `--role subagent` (or a lock role whose provider is `subagent`): the session's own
                                        sub-agent does it — declared hands, recorded as performed_by {provider: subagent, host, model}, not
                                        self-performed. --scope: the files/dirs its hands own — while scoped tasks are open, a changed file is the
                                        open task's whose scope holds it most narrowly, not the first to finish's; a file in two scopes or in none is
                                        said with the `adopt` that settles it; a record path in it (hunsu.json, mangsang/…) is the task's work there.
                                        `add <open id> --check C` attaches a check to an open session task with none (offered when hunsu.json
                                        settings.chongdae.checks-for declares one for its paths). --tests: what a nitpick task writes, what a task with --check may not
                                        change — `add` says which. A protected test the tests writer deleted (in its `touched`, gone from the tree)
                                        is deleted by the contract: said once, sent as `deleted-tests`, never restored or demanded; a build that
                                        recreates one is refused. --closes in a run started without `--from`: said at `add`, and `run` sends no
                                        quibbler or verifier a request whose contract is missing the sections
  init  ... --parent RUN/TASK           a child run: it does TASK of run RUN (typically a worktree run on its own branch). Recorded as
                                        `parent`; the parent's `show` lists its children and their states, read from the children's records
  claim <id> [--by NAME]                take a task for this machine; `run` skips tasks claimed by someone else. With hunsu.json
                                        `settings.chongdae.lease` ("local" | "git" | an argv) a claim is a hold in a lease store, not a line
                                        in the record: one per session (`lease-max`), renewed by `run`'s progress, lapsing after `lease-ttl`
                                        (default 30 min) without it, given back at done/drop/close (`--release` by hand) as a released
                                        marker that keeps the generation (`--list --prune` removes old ones); every take raises
                                        the task's generation, and only the current generation's result is accepted. Under a lease `run`
                                        advances only what this session holds, taking a ready unheld task when it holds none. A `--scope`
                                        path is a key too: overlapping scopes are not held at once
  claim --list                          every hold: machine/session, generation, age, last progress; lapsed and long-held (past
                                        `lease-ceiling`, default 4 h) marked
  claim --break <id> --why WHY [--by NAME]   take over a live hold: a judgment, recorded on the task and committed; the old holder is
                                        told at its next renewal and its result is refused
  (hunsu.json `settings.chongdae.remote`: absent — nothing is pushed; "sync" — each judgment's record commit is pushed, a failed
   push is said and retried at the next one; "shared" — fetched before a claim or a step, pushed after each judgment, and a push
   still refused after fetch-and-reconcile stops the command. Declaring it is the project's consent to chongdae pushing)
  (every judgment below: `--by NAME` writes a person's name; left out, the session signs as itself — {"agent": "<host> <model>"} —
   and `show`/`report` say "the session (<host> <model>)". The gates, confirm and accept, still need --by or --delegated)
  drop  <id> --why WHY [--by NAME]      a session task that will not be done: leaves the open set, stays in the record with the reason
  take  <id> --why WHY [--by NAME] [--checked CMD].. [--checked-red CMD]..   the session finishes a task its hired hands could not (the
                                        work is in the tree): self-performed, decided like any session task. --checked: a command chongdae runs now,
                                        its pass recorded as evidence it saw; --checked-red: a tests task's expected red run (non-zero recorded as
                                        red as expected, zero as passed before the build). `retry` takes both too. An open task owned by another
                                        session can be handed over with a reason; live checks, providers and unanswered native dispatches prevent a take
  did   <id> [--why WHY] [--approved-in source:ID] [--by NAME] (-- COMMAND... | --each FILE)   an operation outside the repository (deploy,
                                        secret deletion, remote database change): one command, run without a shell; recorded on the task as `did`
                                        {command, exit, tail, at, why, approved-in, signer} whatever the exit, printed, committed. A script outside
                                        the project is kept in the record (`outside`: sha256, its text when small) behind `<outside:NAME>` — the
                                        program only: a file given as an argument keeps its sha256 and size, and nothing that looks like secrets is
                                        kept (a value in the command or the tail is masked); the tail drops banners and rules. --each FILE: one command per line, one judgment, one commit; a failure stops the rest.
                                        `show` prints it; `report` lists it (an observation; an objection when it exited non-zero)
  dispute <build> --tests F... --why WHY [--by NAME | --delegated WHY]   a build's protected tests contradict the contract: the task
                                        that wrote them is reopened to amend them (or a tests task is made); the build then takes the
                                        amended files as its contract. A provider's build disputes in its answer (`disputed-tests`)
  adopt <task> FILE... --why WHY [--by NAME | --delegated WHY]   a judgment: these files are TASK's work — moved out of every other
                                        task's `touched` (pinned into an open one's start) and out of TASK's start. Two open session tasks
                                        share one tree, each measuring from its own `add`; work done before its task was added is in that
                                        task's start. `run` and `retry` say when a file's owner cannot be read off the tree
  close [--target DIR] [--run ID] [--anyway --why WHY]   end a session run (open tasks recorded as such): a finished task's work not
                                        committed stops it; the lock's `reviewer` role runs before it is final — an open objection the tree can
                                        answer (cq-failed, stale, a contradiction) stops it for the session, the review taken back; what the
                                        reviewer wrote goes into the close commit; `--anyway --why` closes with them standing, recorded. A worktree
                                        run merges back — a completed plan run too
  report [--since REV]                  what this record says a reviewer should see, as `dwitbuk/findings@1` on stdout: changes no run
                                        claims (outside-run), runs that recorded no `touched` (unattributed), gates/decisions/retries passed
                                        by delegation, and every non-claim. chongdae knows its runs and git; a reviewer knows the type
  status [--target DIR]                 the run in progress (or the newest) and its open tasks; exit 0 always — for a skill's first look
  show  [--run ID | --since REV | --path FILE] [--brief] [--after ISO --hands PATH..]   what happened, for a reader after the fact (read-only, plain text, nothing cut):
                                        a run's tasks in order — who did each, every attempt with its verdict and findings, the
                                        judgments, checks, touched files and times; `--since`: one line per run and the totals;
                                        `--path`: the tasks that touched a file, newest first. `--brief` (jokbo's reads): `--path FILE
                                        --brief` at most two lines (the last task that changed it; one open or dropped — said only while
                                        its run is open or it ended in the last 7 days, and no done task changed the file after it), nothing
                                        when nothing is on record; `--brief` alone the map — runs, this week's, the last closed
                                        `show --after ISO --hands PATH...` (jokbo's `hands` read): one JSON object, path -> the hired task
                                        whose provider changed it (out now, or answered since ISO); `{}` otherwise, never an error
  run   [TASK..] [--target DIR]         advance only the selected tasks, or ready tasks when none are named. Host sub-agent tasks must be
                                        named after their answers arrive. Exit 2 = stopped for the session agent or a human; the last line says what to do.
                                        One call takes at most about CHONGDAE_WAIT seconds (default 240) — chongdae's own checks (a tracked process
                                        of their own), the verifier and every provider count — then says `still working: …` (exit 4) and the next
                                        `run` resumes where it stopped: well under a host's 10-minute tool limit
  confirm <task> [--by NAME | --delegated "why"] [--target DIR]   record the human's confirmation of a produced artifact
  delegate --scope confirm,accept,... --why "..." --by NAME [--run ID]   declare a batch pre-approval once, as its own judgment; later
                                        judgments reference it: `--delegated D-xxxx` (recorded as {ref}, not the words repeated)
  accept  <task> [--by NAME | --delegated WHY]   a human accepts decisions a provider made beyond the contract (after writing them into the plan)
  retry   <task> [--by NAME | --delegated WHY] [--requires CAP..]   a stopped task (blocked, failed, no response) goes out again; the next call
                                        gets the earlier attempts. A session task is measured again (kept with the attempt) and the files its
                                        word names that its measure leaves out are said, with the `adopt` that settles them. --requires: the sandbox lacked CAP — the task says so now, and goes to `<role>@<cap>` if locked
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
A member whose sandbox lacked a capability (`lacked`, `sandbox lacked: …`, or a `not attempted:` refusal) goes to the lock's
alternate that can, with no stop. With none, no person is asked mid-run: the project decided it once, at setup (hunsu.json
`capabilities`, `{"loopback": "session"|"alternates", ...}`), and the session takes the task — recorded as taken and
self-performed with the reason — and `run` stops only for the session to do the work. `report` counts such tasks per run.
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
HELD = "held"   # decide_task: a session task with nothing of its own stays open, and the pass goes on to the next task

DISPATCH = 3   # spawn: a native provider — the session must run the subagent and write the answer, then `run` again

WAITING = 4    # spawn, and `run`'s exit: work is still going past the call's budget (a provider, or chongdae's own checks) — `run` again keeps waiting (the pending record finds it). Its own code, not DECISION's: a backgrounded `run … | tail` exited 0 and read as finished (guin-site, 10-15), and `run`'s own 2 could not tell "still working" from "stopped"

WAIT_BUDGET = int(os.environ.get("CHONGDAE_WAIT", 240))   # seconds one `run` call may take before it hands back: a host's tool call has its own timeout (Claude Code: 10 min), and a run that outlives it gets backgrounded and orphaned. Four minutes, not eight: guin-site's session saw `run` block ~8 minutes against the 10-minute limit and wrapped it in polling loops of its own

_CALL_DEADLINE = None   # set when a `run` call starts: the budget is the call's — chongdae's own checks, the verifier and every provider it starts count toward it. guin-site, 10-15: one call ran the suite (~4.5 min), the verifier (~1 min), resent and waited 240 s more — 8m35s, when the budget had counted only the last wait


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
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}   # a completed transaction can retire an overlay between a reader's directory listing and open


def save(path, data):
    if isinstance(data, dict) and str(data.get("artifact-type", "")).startswith("chongdae/"):
        # every record says which chongdae wrote it — a version, and `+g<sha>[-dirty]` when a working source did
        data = {"artifact-type": data["artifact-type"], "written_by": engine(), **{k: v for k, v in data.items() if k not in ("artifact-type", "written_by")}}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Hooks and readers remain available while a command writes. Publish a whole JSON document at once;
    # truncating the live file let another session read half a record. A unique temp also keeps workers apart.
    import tempfile
    fd, pending = tempfile.mkstemp(prefix=".chongdae-write-", dir=os.path.dirname(path))
    try:
        with io.open(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.remove(pending)


# A run's directory is two things, apart: the record — what a judgment wrote, committed, read by anyone — and the work —
# what this machine needed while the run went (the request as sent, the response as written, the worker's whole session,
# the pending pid, the log, the command lines, the flags the engine keeps between two `run` calls). The work lives under
# <run>/local/ (git-ignored, one line); the record is the run's root: plan.json, state.json, tasks/, asked/, contract/,
# delegations/. A task's working state is its record plus this machine's overlay (local/tasks/<id>.json): the keys below,
# at any depth, are the overlay's — the record never carries them.
LOCAL = "local"


PRIVATE_KEYS = ("session", "transcript", "kept-locally", "start", "start-head", "start-heads",   # the host session behind an author line; the snapshot a task measures from, and the commit(s) it stood on
                "added-in",                                         # the session that added a session task: a run two sessions share tells each its own
                "commands", "read",                                 # a worker's command lines and what it read: the record keeps the summary (`trace`)
                "reported", "rebaseline",                           # flags the engine keeps between two `run` calls
                "checked-tree", "checks-tree",                      # the tree a `--checked` command, or the task's own checks, ran on: what changed after is measured from it
                "checks-source", "review-source", "after-source",   # complete source snapshots: an edit committed meanwhile is still a changed input
                "completion-acks",                                 # launch tokens whose completed outcomes are durably applied to this task
                "lease-held", "lease-work", "lease-established")    # local lease ownership/progress, including that an explicit hold superseded added-in

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
    if isinstance(priv, str):
        return priv
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
    journal = os.path.join(d, LOCAL, "state-transaction.json")
    while True:
        before = load(journal)
        changes = before.get("files", {}) if before.get("phase") == "prepared" else {}

        def read(name):
            return json.loads(json.dumps(changes[name] or {})) if name in changes else load(os.path.join(d, name))

        state = merge_private(read("state.json"), read(LOCAL + "/state.json"))
        tasks = state.get("tasks") or {}
        folder = os.path.join(d, "tasks")
        names = set(os.listdir(folder)) if os.path.isdir(folder) else set()
        names.update(p[len("tasks/"):] for p in changes if p.startswith("tasks/"))
        for name in sorted(names):
            if name.endswith(".json"):
                tasks[name[:-5]] = merge_private(read("tasks/" + name), read(LOCAL + "/tasks/" + name))
        state["tasks"] = tasks
        state.setdefault("non-claims", [])
        # Readers never repair or lock. A prepared transaction is already a complete view; retry if a writer
        # published or finished another generation while we read the files outside that transaction.
        if before == load(journal):
            return state


def load_plan(d):
    """Read the plan's raw view without repairing a prepared transaction or taking a lock."""
    journal = os.path.join(d, LOCAL, "state-transaction.json")
    while True:
        before = load(journal)
        changes = before.get("files", {}) if before.get("phase") == "prepared" else {}

        def read(name):
            return json.loads(json.dumps(changes[name] or {})) if name in changes else load(os.path.join(d, name))

        plan = merge_private(read("plan.json"), read(LOCAL + "/plan.json"))
        if before == load(journal):
            return plan


def recover_state(d):
    """Finish a published state transaction before another mutation or record commit. Called under the command lock.

    The local journal contains private overlays as well as public files and never enters git. Replaying exact file
    values is idempotent; the committed marker stays as a generation fence for concurrent read-only commands.
    """
    path = os.path.join(d, LOCAL, "state-transaction.json")
    txn = load(path)
    if txn.get("phase") != "prepared":
        return
    for name, data in txn["files"].items():
        dest = os.path.join(d, name)
        if data is None:
            if os.path.exists(dest):
                os.remove(dest)
        else:
            save_changed(dest, data)
    save(path, {"id": txn["id"], "phase": "committed"})


def recover_project_states(target):
    for d in all_runs(target):
        recover_state(d)
        cleanup_completion_acks(d, load_state(d))


def save_state(d, state, plan=None):
    """The record and the work, written apart: tasks/<id>.json is the record (one file per task, so tasks done on different
    branches merge as distinct files; never a PRIVATE_KEYS key), local/tasks/<id>.json this machine's overlay of private
    keys and raw paths. state.json keeps only the run's own fields, with local/state.json its overlay.
    A file is written only when its raw content changed: rewriting
    every task file stamped the running version on records it did not touch — guin-site d281c8a, a `did` on one task,
    changed `written_by` 1.19.0 -> 1.20.0 in six done and dropped tasks nobody had judged again."""
    import uuid
    recover_state(d)
    prepare_completion_acks(d, state)
    files = {}

    def changed(name, data):
        path = os.path.join(d, name)
        if data is None:
            if os.path.exists(path):
                files[name] = None
            return
        old = load(path)
        normalized = json.loads(json.dumps(data, ensure_ascii=False))
        if not old or {k: v for k, v in old.items() if k != "written_by"} != {k: v for k, v in normalized.items() if k != "written_by"}:
            if str(normalized.get("artifact-type", "")).startswith("chongdae/"):
                normalized["written_by"] = engine()
            files[name] = normalized

    parent = os.path.dirname(os.path.abspath(d))
    target = os.path.dirname(parent) if os.path.basename(parent) == RUNS else None

    def record(name, data):
        local = LOCAL + "/" + name
        old = merge_private(load(os.path.join(d, name)), load(os.path.join(d, local)))
        normalized = json.loads(json.dumps(data, ensure_ascii=False))
        if old and {k: v for k, v in old.items() if k != "written_by"} == {k: v for k, v in normalized.items() if k != "written_by"}:
            return
        pub, priv = split_private(normalized)
        pub, raws = public_projection(pub, target)
        changed(name, pub)
        changed(local, merge_private(raws, priv) or None)

    if plan is not None:
        record("plan.json", plan)
    for tid, ts in state.get("tasks", {}).items():
        record("tasks/" + tid + ".json", {"artifact-type": "chongdae/task@1",
               **{k: v for k, v in ts.items() if k not in ("artifact-type", "written_by")}})
    record("state.json", {"artifact-type": "chongdae/run@1", **{k: v for k, v in state.items() if k != "tasks"}})
    if files:
        save(os.path.join(d, LOCAL, "state-transaction.json"), {"id": uuid.uuid4().hex, "phase": "prepared", "files": files})
        recover_state(d)
    cleanup_completion_acks(d, state)


def save_changed(path, data):
    """`save`, unless the file already says exactly this (its `written_by` aside): an unchanged record keeps the version that
    wrote it."""
    try:
        old = load(path)
    except (OSError, ValueError):
        old = None
    if isinstance(old, dict) and old:
        new = json.loads(json.dumps(data, ensure_ascii=False))   # what the file would read back as (tuples are lists there)
        if {k: v for k, v in old.items() if k != "written_by"} == {k: v for k, v in new.items() if k != "written_by"}:
            return
    save(path, data)


def work_path(run, name):
    """A work file's place: <run>/local/<name>. The record never holds one."""
    return os.path.join(run, LOCAL, name)


def all_tasks(plan, state):
    """The plan's tasks plus the ones added during a session run (each carries its own definition in its task file), the
    added ones in the order they were added (`seq`) — task files are read in name order, and a name is not a time."""
    added = sorted((ts for ts in state.get("tasks", {}).values() if "def" in ts), key=lambda ts: (ts.get("seq", 0), ts["def"].get("id", "")))
    return plan.get("tasks", []) + [ts["def"] for ts in added]


CLOSED = ("done", "skipped", "dropped")   # a task in one of these is out of the open set: `run`, `status`, `close` and the SessionStart line count alike


def open_tasks(plan, state):
    """The ids of the tasks still open, in order. One rule for every reader: the SessionStart hook counted a dropped task as
    open ("2 task(s) open: cleanup-build, cleanup-ops" while `run` said one) because it kept its own copy of the rule."""
    return [t["id"] for t in all_tasks(plan, state) if state.get("tasks", {}).get(t["id"], {}).get("status") not in CLOSED]


def non_claims(state, unseen=False):
    """Every non-claim in the run, prefixed with its task — the reader's view over the per-task files (and older runs' shared
    list). The same sentence on several tasks is said once, with the tasks: a run of four no-check session tasks said
    "no check decides this task" four times, and a review of a day's runs read it thirty-five times. `unseen`: without the
    providers' non-claims a verifier read and accepted (`seen-non-claims`)."""
    out = list(state.get("non-claims", []))
    by_text = {}
    for tid, ts in sorted(state.get("tasks", {}).items(), key=lambda kv: (kv[1].get("seq", 0), kv[0])):   # task files read in name order; a name is not a time
        seen = set((ts.get("seen-non-claims") or {}).get("texts") or []) if unseen else set()
        for n in ts.get("non-claims", []):
            if n in seen:
                continue
            by_text.setdefault(n, []).append(tid)
    for text, tids in by_text.items():
        out.append("%s: %s" % (tids[0], text) if len(tids) == 1 else "%s — %d task(s): %s" % (text, len(tids), ", ".join(tids)))
    return out


LOCK_STANDING = ("no `reviewer` role in the lock",)   # a non-claim about the lock, not the run: the same at every close until the lock changes


def said_last_run(target, d, state):
    """The lock's standing non-claims this run shares with the run that ended before it: kept in the record, not printed at
    the close again — "no `reviewer` role in the lock" closed each of a day's ten runs (sagoforce, 10-26); `hunsu check` says it."""
    mine = [n for n in state.get("non-claims", []) if n.startswith(LOCK_STANDING)]
    if not mine:
        return set()
    ended = sorted((st for st in (load_state(r) for r in all_runs(target) if r != d) if st.get("status") == "complete"),
                   key=lambda st: str(st["ended"].get("at") if isinstance(st.get("ended"), dict) else st.get("ended") or ""))   # by when it ended: two runs opened in one second sort by their suffix
    return set(mine) & set(ended[-1].get("non-claims", [])) if ended else set()


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
    names = {os.path.basename(r) for r in running}
    children = [r for r in running if (load_state(r).get("parent") or {}).get("run") in names]   # a child started beside its running parent is the one being worked
    return (children or running or runs or [None])[-1]


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


def agent_signer(target):
    """Who signs a judgment made with no `--by`: the session, as chongdae knows it (host and model, from the host's env and
    the session's transcript) — `{"agent": "claude-code claude-opus-5-5"}`. A person's name is written only when `--by NAME`
    gives it. Until 1.17.0 an omitted `--by` wrote git user.name, so every drop, take, retry, claim and adopt the session
    decided alone read as the owner's decision (guin-site: 73 of 80 self-performed records signed with the owner's name)."""
    p = performer("session", target=target)
    return {"agent": " ".join(x for x in (p.get("host"), p.get("model")) if x) or "unknown"}


def signer(args):
    """`--by NAME` when given, else the session (agent_signer)."""
    by = getattr(args, "by", None)
    return by if by else agent_signer(args.target)


def signer_text(by):
    """A signer for a reader: a person's NAME as written, or `the session (claude-code claude-opus-5-5)`."""
    if isinstance(by, dict) and by.get("agent"):
        return "the session (%s)" % by["agent"]
    if isinstance(by, dict):
        return by.get("machine") or "?"
    return str(by) if by else "?"


def is_agent(by):
    """Was this judgment signed by the session, not a person?"""
    return isinstance(by, dict) and bool(by.get("agent"))


def claim_owner(claimed):
    """The machine a claim belongs to (what `run` compares with `me`): a name, or the machine a session's claim was made on."""
    return claimed.get("machine") if isinstance(claimed, dict) else claimed


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
    return path_prefixes(text, target, narrow=False)


def path_prefixes(text, target, narrow=True):
    """Shared machine-path policy; narrow projections exclude account names and require path boundaries."""
    import tempfile
    text = str(text)
    start = r"(?<![^\s\"'`=(\[,:;|&>])" if narrow else ""
    wrapped_start = start + r"(?P<strong>\*\*)?"

    def keep_wrapper(replacement):
        return lambda m: (m.group("strong") or "") + replacement

    def boundary(prefix):
        separators = {"/", os.sep, os.altsep} - {None}
        if "\\" in prefix:
            separators.add("\\")
        return r"(?=$|[\s\"'`;|&),:" + re.escape("".join(sorted(separators))) + r"]|(?(strong)\*\*|(?!)))"
    roots = {os.path.abspath(target), os.path.realpath(target)} if target is not None else set()
    for root in sorted(roots, key=len, reverse=True):
        if narrow:
            text = re.sub(wrapped_start + re.escape(root) + boundary(root), keep_wrapper("."), text)
        else:
            text = text.replace(root + os.sep, "./").replace(root, ".")
    home = os.path.expanduser("~")
    text = re.sub(start + r"(?:%s|~)/\.(?:claude|codex)/plugins/cache/[^/\s\"']+/([^/\s\"']+)/([^/\s\"']+)" % re.escape(home),
                  lambda m: "<plugin:%s@%s>" % (m.group(1), m.group(2)), text)
    # a path above one plugin's version — a marketplace's cache or checkout — names only this machine's marketplaces
    text = re.sub(start + r"(?:%s|~)/\.(claude|codex)/plugins/(?:cache|marketplaces)(?:/[^/\s\"']+)?" % re.escape(home),
                  lambda m: "<%s-plugins>" % m.group(1), text)
    tmps = {tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir()), "/private/tmp", "/tmp"}
    # In public projections a temp prefix must begin a path, not a relative path's segment.
    temp_start = wrapped_start if narrow else ""
    temp_tail = r"(?:(?(strong)(?!\*\*))[^\s\"'`;|&)])*" if narrow else r"[^\s\"'`;|&)]*"
    temp_replacement = keep_wrapper("<tmp>") if narrow else "<tmp>"
    for t in sorted(tmps, key=len, reverse=True):
        text = re.sub(temp_start + re.escape(t.rstrip("/")) + "/" + temp_tail, temp_replacement, text)   # the whole path under it, not its first segment
    text = re.sub(temp_start + r"/(?:private/)?var/folders/" + temp_tail, temp_replacement, text)
    user = os.path.basename(home.rstrip(os.sep)) if home else ""
    if home and home != "~":
        if narrow:
            return re.sub(wrapped_start + re.escape(home) + boundary(home), keep_wrapper("~"), text)
        # a host that names folders after paths (Claude Code: ~/.claude/projects/-Users-me-src-app) carries the home in the name
        text = text.replace(home.replace(os.sep, "-"), "~").replace(home, "~")
    if not narrow and len(user) >= 3:
        text = re.sub(r"(?<![\w-])%s(?![\w-])" % re.escape(user), "<user>", text)   # the account's name, even written on its own
    return text


class MachinePathKey(SystemExit):
    """A machine-path dictionary key cannot be published or renamed safely."""


def public_projection(obj, target, _location=""):
    """Copy public values and retain changed strings in a mirror that merge_private can restore."""
    if isinstance(obj, dict):
        public, raws = {}, {}
        for key, value in obj.items():
            projected_key = path_prefixes(key, target) if isinstance(key, str) else key
            if projected_key != key:
                raise MachinePathKey("machine-path key at %s: %s" % (_location or "<root>", projected_key))
            location = (_location + "." if _location else "") + str(key)
            public[key], raw = public_projection(value, target, location)
            if raw:
                # merge_private restores PRIVATE_KEYS wholesale, even for a standalone derived export.
                raws[key] = json.loads(json.dumps(value)) if key in PRIVATE_KEYS else raw
        return public, raws
    if isinstance(obj, list):
        public, raws = [], {}
        for i, value in enumerate(obj):
            projected, raw = public_projection(value, target, "%s[%d]" % (_location, i))
            public.append(projected)
            if raw:
                raws[str(i)] = raw
        return public, {"[]": raws} if raws else {}
    if isinstance(obj, str):
        public = path_prefixes(obj, target)
        return public, obj if public != obj else {}
    return obj, {}


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
    have = []
    if os.path.exists(path):
        with io.open(path, encoding="utf-8") as fh:
            have = fh.read().split("\n")
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

    recover_state(os.path.join(target, RUNS, run_name))

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
    # Two independent projects can share one git directory (subdirectories of a repository). Their command locks
    # intentionally differ, so their scratch indices must differ too; one read-tree must never erase the other's index.
    import tempfile
    fd, index_path = tempfile.mkstemp(prefix="chongdae-record-", dir=gitdir)
    os.close(fd)
    os.remove(index_path)   # git expects an absent index or a valid one, not mkstemp's empty file
    env = dict(os.environ, GIT_INDEX_FILE=index_path)
    scratch = lambda *a: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    base = git("rev-parse", "--verify", "-q", "HEAD").stdout.strip()
    has_head = bool(base)
    also = [p for p in also if os.path.exists(os.path.join(target, p))]
    try:
        if (scratch("read-tree", base) if has_head else scratch("read-tree", "--empty")).returncode:
            return None
        if scratch("add", "--", rel, RUNS + "/.gitignore", *also).returncode:
            return None
        stale = [t for t in scratch("ls-files", "-ci", "--exclude-standard", "--", rel).stdout.split("\n") if t.strip()]
        if stale:
            scratch("rm", "--cached", "--quiet", "--", *stale)
        if has_head and scratch("diff-index", "--cached", "--quiet", base, "--").returncode == 0:
            return None   # nothing of this run changed -> nothing to notarize
        wrote = scratch("write-tree")
        if wrote.returncode or not wrote.stdout.strip():
            return None
        tree = wrote.stdout.strip()
        made = git("commit-tree", tree, *(["-p", base] if has_head else []), "-m", "%s: %s" % (run_name, message))
        if made.returncode or not made.stdout.strip():
            return None
        # Other agents may commit source directly while a check runs. The command lock protects our record,
        # not their git calls: never replace a newer HEAD with a tree built from an older commit.
        if git("update-ref", "HEAD", made.stdout.strip(), base if has_head else "0" * len(made.stdout.strip())).returncode:
            print("  (record written, not committed: HEAD changed during its commit; a later record commit will include it)")
            return None
    finally:
        try:
            os.remove(env["GIT_INDEX_FILE"])
        except OSError:
            pass
    git("reset", "-q", "--", rel, RUNS + "/.gitignore", *also)   # the person's index now agrees with HEAD for the record, and only there
    push_record(target)   # `remote: sync | shared` only — absent, nothing is pushed
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
        # a shell left in a directory below the project (`cd engine`, a nested repository) is still in it: sagoforce 10-26
        # counted those commands "outside this project"
        here = os.path.realpath(cwd) if cwd else None
        return not project_only or any(r in str(text) for r in roots) or bool(here and any(here == r or here.startswith(r + os.sep) for r in roots))
    # Claude Code keeps a session's sub-agents beside it, `<session>/subagents/agent-<id>.jsonl`, each line as the session's:
    # their edits are the session's hands too (sagoforce 10-26: eight fix batches' edits were in no trace)
    stem = transcript[:-len(".jsonl")] if transcript.endswith(".jsonl") else None
    sub = sorted(glob.glob(os.path.join(glob.escape(stem), "subagents", "agent-*.jsonl"))) if stem else []
    for line in (line for path in [transcript] + sub for line in io.open(path, encoding="utf-8", errors="replace")):
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
    out.setdefault("subagent", "subagent")   # the session's own sub-agents: always at hand, like the session itself (`add --role subagent`)
    return out


SESSION_HANDS = ("session", "subagent")   # providers whose work happens in this session's tree, between `add` and `run`


def session_tree(prov, task, ts):
    """Is this task's work done in the session's own tree — by the session, its sub-agent, or a task the session took? Such a
    task's start is taken at `add`, and `run` decides it from the tree, never by spawning a worker."""
    return bool((ts or {}).get("taken")) or task.get("role") in SESSION_HANDS or hire(prov, task)[1] in SESSION_HANDS


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


def checks_for(target, paths):
    """[(prefix, command)] — the checks hunsu.json `settings.chongdae.checks-for` ({"<path prefix>": "<command>"}) declares for
    these paths (a task's scope entries or the files it changed): a prefix that holds one of them, or that one of them (a scope
    directory) holds. guin-site `lexicon-descriptions` changed 8 lexicon JSON files with no `--check` and became a carried
    objection, though the project runs a test group over `lexicons/`; chongdae cannot know a project's test layout, so the
    project says it once here."""
    declared = settings(target).get("checks-for")
    if not isinstance(declared, dict):
        return []
    out = []
    for prefix, command in sorted(declared.items()):
        pre = str(prefix).replace("\\", "/")
        while pre.startswith("./"):
            pre = pre[2:]
        if not isinstance(command, str) or not command.strip():
            continue
        if any(p == "" or p.startswith(pre) or pre.startswith(p.rstrip("/") + "/") for p in (clean_path(x) for x in paths or [])):
            out.append((pre, command.strip()))
    return out


def check_offer(target, task, files=()):
    """The line that gives a task with no check the check its project declares for its scope or its files (checks_for), or
    None: `chongdae add TASK --check "COMMAND"` attaches it to the open task."""
    if task.get("checks"):
        return None
    found = checks_for(target, list(task.get("scope") or []) + list(files or []))
    if not found:
        return None
    commands = list(dict.fromkeys(c for _, c in found))
    return ("hunsu.json settings.chongdae.checks-for checks %s with %s, and no check decides %s (done would be your word, and the reviewer "
            "carries it): `chongdae add %s %s` attaches %s" % (", ".join(sorted({p for p, _ in found})), ", ".join("`%s`" % c for c in commands),
                                                            task["id"], task["id"], " ".join("--check %s" % shlex.quote(c) for c in commands), "it" if len(commands) == 1 else "them"))


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
    # `subagent`: the session's own sub-agent (the host's Agent tool) did the work — declared hands, not self-performed. It
    # runs in this session's host on its model unless the session said otherwise; chongdae sees the session, not the sub-agent
    out = {"provider": "subagent" if who == "subagent" else "session", "host": host}
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


def record_scope(target, task):
    """The entries of a task's own `--scope` that are record paths (`hunsu.json`, `mangsang`, …): a task whose work is another
    product's records — `hunsu lock`, a mangsang confirm — says so by scoping it, and inside its scope those files are its work.
    guin-site run-20261015-094800-de3e: `plugins-lock` (`--scope hunsu.json hunsu.lock.json …`) and `site-build-stale`
    (`--scope mangsang`) recorded `touched: []`, `run` held both as "has changed nothing of its own", the reviewer raised both,
    and no commit lines were printed. This run's record and the host's settings are never anyone's work."""
    rp = record_paths(target)
    out = []
    for c in (task or {}).get("scope") or []:
        if c and not (c + "/").startswith((RUNS + "/", ".claude/")) and (c.startswith(rp) or (c + "/").startswith(rp)):
            out.append(c)
    return tuple(out)


def in_entries(path, entries):
    """Is `path` one of `entries`, or under one of them?"""
    return any(path == e or path.startswith(e + "/") for e in entries or ())


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
        if len(entry) < 4 or entry.endswith("/"):   # a directory is a repository of its own (`?? engine/`): nested_repos counts it
            continue
        out.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":   # the next field is where it came from
            if i < len(parts) and parts[i]:
                out.append(parts[i])
            i += 1
    return [p.replace("\\", "/") for p in out]


def nested_repos(target):
    """The repositories inside the project that its own git does not hold: a directory with its own `.git` that the project's
    status names as one untracked or ignored entry (`?? engine/`, `!! engine/`). A workspace of sibling repositories keeps
    them so — sagoforce, 10-26: six, all in `.gitignore`; 43 of 47 tasks recorded `touched: []`, the verifier accepted 24
    empty packets (one a 33-file change), and `adopt` refused a committed file as nothing anyone changed. A submodule is the
    project's own (its gitlink is tracked). Paths relative to target, `/` separators.
    ponytail: a repository below an ignored directory that is not one (`vendor/x/.git`) is not found."""
    import subprocess
    try:
        done = subprocess.run(["git", "status", "--porcelain", "-z", "--ignored=matching", "--untracked-files=normal", "--", "."],
                              cwd=target, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
    except OSError:
        return []
    if done.returncode:
        return []
    prefix = subprocess.run(["git", "rev-parse", "--show-prefix"], cwd=target, capture_output=True, text=True, encoding="utf-8").stdout.strip().replace("\\", "/")
    out = []
    for entry in done.stdout.split("\0"):
        if entry[:3] in ("?? ", "!! ") and entry.endswith("/"):
            path = entry[3:].rstrip("/").replace("\\", "/")
            path = path[len(prefix):] if prefix and path.startswith(prefix) else path
            if path and not path.startswith(RUNS + "/") and os.path.exists(os.path.join(target, path, ".git")):
                out.append(path)
    return sorted(out)


def nested_heads(target):
    """{nested repository: the commit it stands on} — what a task's work in each is measured from, beside `start-head`."""
    return {n: h for n in nested_repos(target) for h in [head_sha(os.path.join(target, n))] if h}


def repo_of(target, path, nested=None):
    """(the nested repository holding `path`, the path inside it) — ("", path) when the project's own git holds it."""
    for n in sorted(nested_repos(target) if nested is None else nested, key=len, reverse=True):
        if path.startswith(n + "/"):
            return n, path[len(n) + 1:]
    return "", path


def dirty(target, records_too=False, keep=()):
    """{path: content hash} of every file that differs from HEAD (tracked or untracked) under target, paths relative to target.
    None when there is no git — then nothing can be attributed, and the record says so. The products' records are left out
    (nobody's work) unless `records_too`: what the reviewer wrote at close is a record, and the close commit wants it; `keep`,
    record paths a task's own scope names (record_scope), are kept too."""
    import hashlib, subprocess
    paths = status_paths(target)
    if paths is None:
        return None
    # porcelain paths are relative to the repository root; the record is relative to the target (a project can live in a subdirectory)
    prefix = subprocess.run(["git", "rev-parse", "--show-prefix"], cwd=target, capture_output=True, text=True, encoding="utf-8").stdout.strip().replace("\\", "/")
    skip = (RUNS + "/",) if records_too else record_paths(target)
    out = {}

    def take(path, inner):
        # records, machine-local state and interpreter leftovers are nobody's work — inside a nested repository by its own path
        if path and (not inner.startswith(skip) or in_entries(path, keep)) and not re.search(r"(^|/)__pycache__/|\.py[co]$", path):
            full = os.path.join(target, path)
            out[path] = hashlib.sha1(io.open(full, "rb").read()).hexdigest() if os.path.isfile(full) else "gone"
    for path in paths:
        path = path[len(prefix):] if prefix and path.startswith(prefix) else path
        take(path, path)
    for n in nested_repos(target):
        for path in status_paths(os.path.join(target, n)) or []:
            take(n + "/" + path, path)
    return out


def source_tree(target, keep=()):
    """Content and executable bits of git-visible source, including nested repositories.

    A dirty-file snapshot alone cannot witness a review: a committed edit leaves it
    empty again. Record commits must not invalidate a review either. Read the files,
    not HEAD, and exclude records except the task's explicitly scoped record work.
    Scopes name ownership, not dependencies: changes anywhere in this source tree
    invalidate a check/review that was already in flight.
    """
    import hashlib, stat, subprocess
    out, skip, repositories, seen = {}, record_paths(target), [""], set()
    for repo in repositories:
        if repo in seen:
            continue
        seen.add(repo)
        cwd = os.path.join(target, repo) if repo else target
        done = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."],
                              cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
        if done.returncode:
            return None
        for inner in set(done.stdout.split("\0")) - {""}:
            inner = inner.replace("\\", "/")
            path = repo + "/" + inner if repo else inner
            if inner.startswith((RUNS + "/", ".claude/")) or ((inner.startswith(skip) and not in_entries(path, keep))) \
                    or re.search(r"(^|/)__pycache__/|\.py[co]$", path):
                continue
            full = os.path.join(target, path)
            try:
                info = os.lstat(full)
                if stat.S_ISLNK(info.st_mode):
                    out[path] = "link:" + os.readlink(full)
                elif stat.S_ISREG(info.st_mode):
                    with open(full, "rb") as fh:
                        digest = hashlib.sha256()
                        for block in iter(lambda: fh.read(1024 * 1024), b""):
                            digest.update(block)
                    out[path] = "%s:%s" % (int(bool(info.st_mode & 0o111)), digest.hexdigest())
                elif stat.S_ISDIR(info.st_mode) and os.path.exists(os.path.join(full, ".git")):
                    # A tracked submodule is a gitlink in this repository's
                    # index. HEAD alone misses edits inside its working tree;
                    # recurse into it, including further nested submodules.
                    out[path] = "repository"
                    repositories.append(path.rstrip("/"))
                else:
                    out[path] = "directory"
            except FileNotFoundError:
                out[path] = "gone"
        repositories.extend((repo + "/" if repo else "") + name for name in nested_repos(cwd))
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


def committed_since(target, head, keep=(), heads=None):
    """{path: content hash at `head`} for every file a commit since `head` changed (records and leftovers aside, as in `dirty`):
    work the session committed before `run` measured it. Empty when HEAD has not moved or there is no git. `heads`, each nested
    repository's commit then (nested_heads): a commit in one since is the work too, its paths prefixed by the repository's."""
    import hashlib, subprocess
    out = {}
    for n, h in [("", head)] + sorted((heads or {}).items()):
        cwd = os.path.join(target, n) if n else target
        if not h or not os.path.isdir(cwd) or h == head_sha(cwd):
            continue
        done = subprocess.run(["git", "diff", "--name-only", "-z", "--no-renames", "--relative", h, "HEAD", "--", "."], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
        if done.returncode:
            continue
        for inner in done.stdout.split("\0"):
            inner = inner.replace("\\", "/")
            path = n + "/" + inner if n else inner
            if inner and (not inner.startswith(record_paths(target)) or in_entries(path, keep)) and not re.search(r"(^|/)__pycache__/|\.py[co]$", path):
                then = subprocess.run(["git", "show", "%s:./%s" % (h, inner)], cwd=cwd, capture_output=True)
                out[path] = hashlib.sha1(then.stdout).hexdigest() if then.returncode == 0 else "gone"
    return out


def touched_files(target, start=None, head=None, keep=(), heads=None):
    """What changed since the task started: every file whose content is not what it was then. Without a start snapshot, the
    whole dirty set. A file dirty at start and clean now went back to HEAD — a change like any other, and the one a build
    makes when it takes the committed version of an uncommitted file for the real one (a contract's newest tests).
    `head`, the commit the tree stood on at start: a file a commit since then changed is measured against what it was there,
    so work the session committed before `run` is still this task's (guin-site's drop-nojekyll recorded `touched: []`
    for three committed files, and the report then had nobody to attribute them to)."""
    now = dirty(target, keep=keep)
    if now is None:
        return None
    start = start or {}
    then = committed_since(target, head, keep, heads)
    changed = {p for p, h in now.items() if start.get(p, then.get(p)) != h}
    for p, h in list(start.items()) + [(p, h) for p, h in then.items() if p not in start]:
        if p not in now and file_hash(target, p) != h:
            changed.add(p)
    return sorted(changed)


def adopted_files(ts):
    """The files a judgment (`adopt`) gave this task: its own whatever the measure says."""
    return {f for a in ts.get("adopted") or [] if isinstance(a, dict) for f in a.get("files") or []}


def measured(target, ts):
    """What a task changed: its measure from its start snapshot, and the files a judgment gave it (`adopt`). None without git."""
    found = touched_files(target, ts.get("start"), ts.get("start-head"), record_scope(target, ts.get("def")), ts.get("start-heads"))   # record files its own scope names are its work
    if found is None:
        return None
    return sorted(set(found) | adopted_files(ts))


def clean_path(p):
    """A project-relative path as the record writes it: `/` separators, no leading `./`, no trailing `/`. `.` is the project."""
    p = str(p).replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.rstrip("/")
    return "" if p == "." else p


def scope_depth(path, scope):
    """How narrowly `scope` (a task's `--scope` entries) holds `path`: the deepest entry that is the path or a directory above
    it, counted in segments (the whole project, `.`, is 0); None when no entry holds it."""
    best = None
    for s in scope or []:
        if s == "" or path == s or path.startswith(s + "/"):
            depth = len(s.split("/")) if s else 0
            best = depth if best is None or depth > best else best
    return best


def scoped_measure(target, plan, state, tid, ts, prov):
    """(files, notes, held): what task `tid` changed, with the files its hands own by scope. A task added with `--scope` names the
    files and directories its hands own; while scoped tasks are open, a changed file is the open task's whose scope holds
    it — the narrowest — not whichever task finishes first: a file another open task's scope holds more narrowly is left
    for that task (not counted, not pinned). A file held equally by this task's scope and another's, or held by no scope
    while scoped tasks are open, stays with this task by the window rule and is said, with the `adopt` that settles it.
    No scoped task open: the window rule alone, as before. guin-site, 2026-10-04: 11 sub-agents did 14 tasks in one tree,
    and concurrent ones needed `adopt` to split the files each had been told were its own."""
    found = measured(target, ts)
    if found is None:
        return None, [], {"settled": set(), "ties": {}}
    tasks = {t["id"]: t for t in all_tasks(plan, state)}
    mine = (tasks.get(tid) or ts.get("def") or {}).get("scope") or []
    others = []
    for oid, t2 in tasks.items():
        o = state["tasks"].get(oid, {})
        if oid != tid and t2.get("scope") and o.get("status") == "todo" and isinstance(o.get("start"), dict) and session_tree(prov, t2, o):
            others.append((oid, t2["scope"]))
    if not mine and not others:
        return found, [], {"settled": set(), "ties": {}}
    fixed = adopted_files(ts)
    keep, tie, nowhere, left, settled = [], {}, [], {}, set()
    for f in found:
        if f in fixed:
            keep.append(f)
            continue
        holders = [(scope_depth(f, sc), oid) for oid, sc in [(tid, mine)] + others if scope_depth(f, sc) is not None]
        if not holders:
            keep.append(f)
            nowhere.append(f)
            continue
        top = max(h for h, _ in holders)
        best = sorted(oid for h, oid in holders if h == top)
        if tid in best:
            keep.append(f)
            if len(best) == 1:
                settled.add(f)
            if len(best) > 1:
                tie.setdefault(tuple(o for o in best if o != tid), []).append(f)
        else:
            left.setdefault(tuple(best), []).append(f)
    notes = []
    for owners, fs in sorted(left.items()):
        if len(owners) == 1:
            notes.append("scope: %s %s in %s's scope — left for it, not counted as %s's" % (", ".join(fs), "is" if len(fs) == 1 else "are", owners[0], tid))
        else:
            notes.append("scope: %s %s held equally by %s's scopes — left for them, not counted as %s's; `chongdae adopt %s %s --why WHY` settles it"
                         % (", ".join(fs), "is" if len(fs) == 1 else "are", " and ".join(owners), tid, owners[0], " ".join(fs)))
    for owners, fs in sorted(tie.items()):
        notes.append("scope: %s %s in %s's scope and %s's alike — %s counts %s by its window; `chongdae adopt %s %s --why WHY` if %s %s's"
                     % (", ".join(fs), "is" if len(fs) == 1 else "are", tid, " and ".join(owners), tid, "it" if len(fs) == 1 else "them",
                        owners[0], " ".join(fs), "it is" if len(fs) == 1 else "they are", owners[0]))
    if nowhere:
        scoped = sorted(([tid] if mine else []) + [o for o, _ in others])
        notes.append("scope: %s %s in no open task's scope (scoped and open: %s) — %s counts %s by its window; `chongdae adopt TASK %s --why WHY` gives %s to the task whose work %s"
                     % (", ".join(nowhere), "is" if len(nowhere) == 1 else "are", ", ".join(scoped), tid, "it" if len(nowhere) == 1 else "them",
                        " ".join(nowhere), "it" if len(nowhere) == 1 else "them", "it is" if len(nowhere) == 1 else "they are"))
    # held: `settled`, the files this task's scope alone holds most narrowly (no brief contests them); `ties`, the files another
    # open task's scope holds as narrowly — not pinned away from it, which keeps measuring them until `adopt` settles them
    return sorted(keep), notes, {"settled": settled, "ties": {f: list(o) for o, fs in tie.items() for f in fs}}


def names_file(task, path):
    """Does a task's own word name this file as its work — the tests it writes, or its brief (the path, or the file's name as a
    word)? A build's protected tests are its contract, not its work: they do not count."""
    if path in (task.get("tests") or []):
        return writes_tests(task)
    brief = task.get("brief") or ""
    if path in brief:
        return True
    base = path.rsplit("/", 1)[-1]
    return len(base) > 3 and re.search(r"(?<![\w./-])%s(?![\w-])" % re.escape(base), brief) is not None


def held_at_start(target, task, ts, files=None):
    """The files this task's own word names that were already changed when it started — in its start snapshot, unchanged
    since, so its measure does not count them: work done before its task was added (the contract edited before its task,
    the order slip every guin-site review found), or a file another task's finish pinned there (`pinned`)."""
    start = ts.get("start") if isinstance(ts.get("start"), dict) else {}
    mine = set(measured(target, ts) or [])
    return sorted(f for f in (files if files is not None else start) if f in start and f not in mine and names_file(task, f)
                  and start[f] == file_hash(target, f))


def contested(target, plan, state, tid, files):
    """{file: [(open task id, "after" | "before")]} — the files among `files` that another open session task's brief or tests
    name, and that changed after it was added ("after": it measures them as its own too) or were already changed when it was
    added ("before": its start holds them, so it measures nothing there). Whose work such a file is cannot be read off the
    tree: two open session tasks share one tree, and each measures from its own `add`. guin-site, 2026-10-02: escape-tests
    (added first, no check of its own) and escape-build (its brief named src/lib/outputs.ts) were open together; the session
    had written outputs.ts before adding escape-build, so escape-build's start held it, escape-tests finished first and
    counted it as its own, and escape-build's diff was empty on every retry."""
    out = {}
    prov = providers(target, plan)
    for t2 in all_tasks(plan, state):
        other = state["tasks"].get(t2["id"], {})
        if t2["id"] == tid or other.get("status") != "todo" or not isinstance(other.get("start"), dict):
            continue
        if not session_tree(prov, t2, other):
            continue
        named = [f for f in files if names_file(t2, f)]
        if not named:
            continue
        theirs = set(measured(target, other) or [])
        before = set(held_at_start(target, t2, other, named)) - set(other.get("pinned") or {})
        for f in named:
            if f in theirs or f in before:
                out.setdefault(f, []).append((t2["id"], "after" if f in theirs else "before"))
    return out


def contested_lines(tid, shared, plan, state):
    """What `contested` found, said: the file, who else names it and when it changed, and the judgment that settles it."""
    lines = []
    for f, ids in sorted(shared.items()):
        for o, how in ids:
            t2 = next((t for t in all_tasks(plan, state) if t.get("id") == o), {})
            said = "tests" if f in (t2.get("tests") or []) else "brief"
            if how == "after":
                fact = "changed after %s was added, and %s's %s names it — %s measures it as its own too" % (o, o, said, o)
            else:
                fact = "was already changed when %s was added (its start holds it, so it measures nothing there), and %s's %s names it" % (o, o, said)
            lines.append("note: %s %s; %s counts it. chongdae does not guess whose it is: `chongdae adopt %s %s --why WHY` if it is %s's work "
                         "(done before its task was added, or for it), `chongdae adopt %s %s --why WHY` to settle it as %s's"
                         % (f, fact, tid, o, f, o, tid, f, tid))
    return lines


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
    """Every check is an argv run in the target; all must exit 0. Output tails come back for the stop message."""
    return check_runs(target, checks)[0]


def check_runs(target, checks):
    """(failed, ran): every check run in the target — `failed` the stop message's lines for those that did not exit 0, `ran`
    a record per check ({command, exit, tail, at, chongdae}, the command as the plan writes it: portable). `python`/`python3`
    in argv[0] resolves to whichever this machine has (macOS ships only `python3`) — plans stay portable."""
    import subprocess
    failed, ran = [], []
    for given in checks:
        argv = resolve_argv(target, given)
        if argv and argv[0] in ("python", "python3") and not shutil.which(argv[0]):
            alt = next((c for c in ("python3", "python") if shutil.which(c)), None)
            argv = [alt or sys.executable] + argv[1:]
        done = subprocess.run(argv, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        tail = (done.stdout + done.stderr).strip().split("\n")[-6:]
        ran.append({"command": shlex.join(str(a) for a in given), "exit": done.returncode, "tail": portable(kept_tail(done.stdout + done.stderr), target), **stamp()})
        if done.returncode:
            failed.append("%s -> exit %d\n      %s" % (" ".join(argv), done.returncode, "\n      ".join(tail)))
    return failed, ran


def checks_worker(target, job):
    """`chongdae.py _checks TARGET JOB`: the task's checks, run by chongdae in a process of their own, so a `run` call can hand
    back while they run (budget_checks). Writes {failed, ran, tree} beside the job — `tree`, the tree they left."""
    spec = load(job)
    source_before = source_tree(target, spec.get("keep") or ())
    failed, ran = check_runs(target, spec.get("checks") or [])
    save(job[:-len(".json")] + ".result.json", {"failed": failed, "ran": ran, "tree": dirty(target) or {},
                                               "launch-token": os.environ.get("CHONGDAE_LAUNCH_TOKEN"),
                                               "source-before": source_before, "source": source_tree(target, spec.get("keep") or ())})
    return 0


def budget_checks(target, d, task, again=True, result_source=None):
    """(code, failed, ran): the task's checks, run inside the `run` call's budget. They run as a process of their own, tracked
    like a provider (<task>.checks.pending.json): past the budget the call hands back (code WAITING) and the next `run` waits
    for the same process — never killed mid-way, never started twice — and reads what it found. A result is the tree's only
    while the tree is what the checks left: changed since, they run again. guin-site, 10-15: the suite took ~4.5 minutes of a
    call whose budget counted only provider waits."""
    import subprocess
    import time
    base = work_path(d, task["id"] + ".checks")
    job, res_path, pend_path = base + ".json", base + ".result.json", base + ".pending.json"
    cleanup_completion_acks(d, load_state(d))
    pending = load(pend_path)
    checks = task.get("checks") or []
    if pending and pending.get("checks") != checks:
        # the task's checks changed since (a dispute, a re-plan): what runs answers other checks — the one stop that is needed
        if pid_alive(pending.get("pid")):
            try:
                os.killpg(int(pending["pid"]), 15)
            except (OSError, ValueError, AttributeError):
                pass
        pending = {}
    if pending and not completed_payload(pending, "checks") and not os.path.exists(res_path) and not pending_alive(pend_path, pending):
        pending = {}   # it died without a result: run them again
    if not pending:
        if os.path.exists(res_path):
            os.remove(res_path)
        os.makedirs(os.path.dirname(job), exist_ok=True)
        save(job, {"checks": checks, "keep": record_scope(target, task)})
        pending = launch_pending(pend_path, [sys.executable, os.path.abspath(__file__), "_checks", os.path.abspath(target), job],
                                 target, base + ".log", checks=checks)
    else:
        resume_launch(pend_path, pending)   # recover an intent whose caller died before/just after Popen
    global _CALL_DEADLINE
    if _CALL_DEADLINE is None:
        _CALL_DEADLINE = time.time() + WAIT_BUDGET
    nap = 0.05
    while pending_alive(pend_path, pending):
        if time.time() > _CALL_DEADLINE:
            return WAITING, {"status": "waiting", "pid": pending.get("pid"), "since": pending.get("since"), "log": base + ".log", "checks": True}, None
        time.sleep(nap)
        nap = min(nap * 2, 1.0)
    result = completed_payload(pending, "checks")
    if result is None:
        result = {}
        for _ in range(3):
            try:
                result = load(res_path)
                break
            except ValueError:
                time.sleep(0.2)
        if (pending.get("launch") or {}).get("token") and result.get("launch-token") != pending["launch"]["token"]:
            result = {}   # an old worker's result cannot answer this launch
    if not result:
        retire_check_completion(pend_path, res_path)
        return None, ["%s: chongdae's run of the checks left no result (see %s)" % (task["id"], base + ".log")], []
    now = source_tree(target, record_scope(target, task))
    if "source" not in result or result.get("source-before") != result.get("source") or result.get("source") != now:
        # Writers may change and commit while a check runs. Never stamp the new
        # tree with an old pass. Retry once, then yield the work back if it moves
        # again; no unbounded loop and no claim that a changing tree passed.
        retire_check_completion(pend_path, res_path)
        if again:
            return budget_checks(target, d, task, again=False, result_source=result_source)
        return None, ["%s: source changed while its checks ran; wait for the writers, then `chongdae run %s` again" % (task["id"], task["id"])], result.get("ran") or []
    if result_source is not None:
        result_source["source"] = result.get("source")
    retain_completion(d, task["id"], pend_path, pending, "checks", result)
    return None, result.get("failed") or [], result.get("ran") or []


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


def landing_raws(public, child, target):
    """Only projection-matching strings cross from a child; private state never does.

    Compare each leaf with the merged public record, so a merge's changed values win.
    This is a projection mirror, not a copy of the child's local directory.
    """
    if isinstance(public, dict) and isinstance(child, dict):
        raws = {}
        for key in public.keys() & child.keys():
            if key not in PRIVATE_KEYS:
                raw = landing_raws(public[key], child[key], target)
                if raw:
                    raws[key] = raw
        return raws
    if isinstance(public, list) and isinstance(child, list):
        raws = {}
        for i, (value, original) in enumerate(zip(public, child)):
            raw = landing_raws(value, original, target)
            if raw:
                raws[str(i)] = raw
        return {"[]": raws} if raws else {}
    if isinstance(child, str) and public != child and public == path_prefixes(child, target):
        return child
    return {}


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
    # close already holds the destination lock. Bring only this run's matching raw
    # strings across, preserving any overlay the destination already owns.
    child = load_state(os.path.join(wt_path, RUNS, run_name))
    landing = os.path.join(main, RUNS, run_name)
    state = load_state(landing)

    def restore(name, original):
        public = load(os.path.join(landing, name))
        raws = landing_raws(public, original, wt_path)
        return merge_private(merge_private(public, raws), load(os.path.join(landing, LOCAL, name)))

    for tid in state.get("tasks", {}):
        state["tasks"][tid] = restore("tasks/" + tid + ".json", child.get("tasks", {}).get(tid, {}))
    state = {**restore("state.json", child), "tasks": state["tasks"]}
    plan = restore("plan.json", load_plan(os.path.join(wt_path, RUNS, run_name)))
    save_state(landing, state, plan=plan)
    failed = []
    for r in all_runs(main):
        st = load_state(r)
        if st.get("status") != "complete":
            continue
        for task in all_tasks(load_plan(r), st):
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
        st = load_state(landing)
        st["landed"] = {**stamp(), "commit": landed}
        save_state(landing, st)
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


def reader_checks(plan, state, task):
    """What a task whose role reads the contract (a quibble added as a task of its own) is told of the checks: not its own —
    it has none, by what it is — but the checks of the open builds closing the same sections, labelled as planned, or that
    none is named yet. guin-site run-20261015-054352-a0ec: cache-quibble was sent its own `checks: []` under `stage:
    build`, and 4 of its 8 findings were "unchecked: checks가 []라서 …" — about the request, not the contract."""
    closes = set(task.get("closes") or [])
    planned = [(t["id"], t["checks"]) for t in all_tasks(plan, state) if t.get("id") != task.get("id") and t.get("checks") and closes & set(t.get("closes") or [])
               and (state.get("tasks", {}).get(t["id"]) or {}).get("status") not in ("dropped", "skipped")]
    if planned:
        return {"checks": [c for _, cs in planned for c in cs],
                "checks-are": "planned: the checks of %s, the build(s) closing the same sections — not this task's; it reads the contract before the work"
                              % ", ".join(tid for tid, _ in planned)}
    return {"checks-are": "not named yet: this task reads the contract before the work, and no build closing these sections has been added — "
                          "no list of checks exists to hold a sentence against; say what a check must decide, not that the list is empty"}


def contract_fingerprint(target, d, tid):
    """The text a `before` role answered: the task's brief and checks and the plan sections it closes, hashed."""
    import hashlib
    plan = load_plan(d); state = load_state(d)
    task = next((t for t in all_tasks(plan, state) if t["id"] == tid), {})
    text = json.dumps({"brief": task.get("brief"), "checks": task.get("checks"), "tests": task.get("tests")}, sort_keys=True)
    if plan.get("from") and os.path.exists(os.path.join(target, plan["from"])):
        sections = contract_sections(target, plan, task)[0]
        for qid in task.get("closes", []):
            text += "\n" + sections.get(qid, "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def contract_sections(target, plan, task):
    """({Q-id: the `## Q-id` section's text}, [the closed ids with no section]) — what a request carries as the contract:
    the sections of the run's plan document (`init --from`, or a plan run's `from`) that the task closes."""
    sections = {}
    doc = os.path.join(target, plan.get("from") or "")
    body = io.open(doc, encoding="utf-8").read() if plan.get("from") and os.path.isfile(doc) else None
    for qid in task.get("closes") or []:
        m = re.search(r"^## +%s\b.*?(?=^## |\Z)" % re.escape(qid), body, re.M | re.S) if body is not None else None
        if m:
            sections[qid] = m.group(0).strip()
    return sections, [q for q in task.get("closes") or [] if q not in sections]


CONTRACT_READERS = ("quibble", "verifier")   # the roles whose whole job is reading the contract: sent nothing, they answer about nothing


def contract_gap(target, plan, task):
    """Why the contract a task closes cannot be sent — the run has no plan document, it is gone, or it has no section for a
    closed id — or None when every section is there (or the task closes nothing)."""
    missing = contract_sections(target, plan, task)[1]
    if not missing:
        return None
    if not plan.get("from"):
        return "this run has no contract document (it was started without `--from`), so %s reach%s no one" % (", ".join(missing), "es" if len(missing) == 1 else "")
    if not os.path.isfile(os.path.join(target, plan["from"])):
        return "its contract document %s does not exist" % plan["from"]
    return "%s has no `## %s` section" % (plan["from"], "`, `## ".join(missing))


def empty_contract_stop(target, plan, task, reader):
    """A quibbler or verifier is not sent a request whose contract is missing what the task closes. guin-site, 2026-10-12: a
    session run started without `--from`; `add --closes Q-cleanup` was accepted, and the quibble got `contract: {}` and
    answered "the contract and checks are empty" — a round paid for nothing, and the run started over. Returns the stop's
    exit code, or None when the contract is whole."""
    gap = contract_gap(target, plan, task)
    if gap is None:
        return None
    if plan.get("from") and os.path.isfile(os.path.join(target, plan["from"])):
        fix = "add the section to %s, then `chongdae run`" % plan["from"]
    elif plan.get("kind") == "session":
        fix = ("close this run and start the next with `chongdae init --session --from PLAN` (the plan document holding the sections), "
               "then add the task there — or put the section's text in the brief and add the task again without --closes "
               "(`chongdae drop %s --why WHY`, then `chongdae add`)" % task["id"])
    else:
        fix = "the plan's `from` names the document holding the sections: give it (a new run with the plan fixed), or take --closes off the task"
    fix = fix[0].upper() + fix[1:]
    return stop("session agent: %s closes %s, but %s — %s would be sent an empty contract and answer about nothing; not sent. %s."
                % (task["id"], ", ".join(task.get("closes") or []), gap, reader, fix))


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
    if pid <= 0:
        return False   # zero/negative ids mean process groups to kill/waitpid, never a worker
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


_COMPLETION_ACK_QUEUE = {}


def completion_token(pending):
    return (pending.get("launch") or {}).get("token") or pending.get("completion-token")


def completed_payload(pending, kind):
    """A completed outcome belongs to one launch, even while its caller has not saved the task yet."""
    completed = pending.get("completed") or {}
    if completed.get("kind") == kind and completed.get("token") and completed["token"] == completion_token(pending):
        return completed.get("payload")
    return None


def retain_completion(d, tid, path, pending, kind, payload, code=0):
    """Keep the ended worker's answer until the task transaction acknowledges applying it.

    A crash before that transaction replays this payload. A crash after it only
    leaves cleanup to repeat; neither boundary launches the completed worker again.
    """
    import uuid
    if not completion_token(pending):
        pending["completion-token"] = uuid.uuid4().hex   # legacy/native dispatches have no launcher token
    token = completion_token(pending)
    completed = {"token": token, "kind": kind, "payload": payload, "code": code}
    if pending.get("completed") != completed:
        pending["completed"] = completed
        save(path, pending)
    key = os.path.realpath(d)
    _COMPLETION_ACK_QUEUE.setdefault(key, {})[os.path.basename(path)] = (tid, token)


def prepare_completion_acks(d, state):
    """Called before save_state writes its transaction: the outcome and its acknowledgement commit together."""
    for name, (tid, token) in _COMPLETION_ACK_QUEUE.get(os.path.realpath(d), {}).items():
        ts = state.get("tasks", {}).get(tid)
        if ts is not None:
            ts.setdefault("completion-acks", {})[name] = token


def cleanup_completion_acks(d, state):
    """Only a durable task acknowledgement authorizes deleting its completed launch record."""
    queued = _COMPLETION_ACK_QUEUE.get(os.path.realpath(d), {})
    for tid, ts in state.get("tasks", {}).items():
        for name, token in ts.get("completion-acks", {}).items():
            if os.path.basename(name) != name or not name.endswith(".pending.json"):
                continue
            path = work_path(d, name)
            pending = load(path)
            completed = pending.get("completed") or {}
            if completed.get("token") == token and completion_token(pending) == token:
                if completed.get("kind") == "checks":
                    result = path[:-len(".pending.json")] + ".result.json"
                    if os.path.exists(result):
                        os.remove(result)
                if os.path.exists(path):
                    os.remove(path)
            if queued.get(name) == (tid, token):
                queued.pop(name, None)
    if not queued:
        _COMPLETION_ACK_QUEUE.pop(os.path.realpath(d), None)


def retire_check_completion(pending, result):
    """A missing or stale check result is explicitly discarded, never acknowledged as a pass."""
    for path in (result, pending):
        if os.path.exists(path):
            os.remove(path)


def launch_pending(path, argv, target, log_path, **metadata):
    """Publish intent before creating a process. A launcher registers its own pid before exec, so a dying caller cannot
    leave an undiscoverable provider. Recovery repeats the same launch token, never the provider command directly."""
    import time
    import uuid
    pending = {**metadata, "argv": argv, "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "launch": {"token": uuid.uuid4().hex, "cwd": os.path.abspath(target), "log": os.path.abspath(log_path)}, "launch-state": "launching"}
    save(path, pending)
    resume_launch(path, pending)
    return pending


def resume_launch(path, pending):
    """An intent may survive before Popen or while its launcher starts. Several recovery launchers are harmless: the
    per-intent OS lock and registered token allow only one to exec. There is no post-Popen parent bookkeeping window."""
    import subprocess
    launch = pending.get("launch") or {}
    if pending.get("launch-state") != "launching" or not launch.get("token"):
        return
    with io.open(launch["log"], "a", encoding="utf-8") as log:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "_launch", os.path.abspath(path), launch["token"]],
                         cwd=launch["cwd"], stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)


def pending_alive(path, pending):
    """Refresh child registration while waiting; a launching intent without a pid is pending, never pid 0."""
    if pending.get("launch"):
        current = load(path)
        if (current.get("launch") or {}).get("token") == pending["launch"].get("token"):
            pending.update(current)
        if (pending.get("completed") or {}).get("token") == completion_token(pending):
            return False
        if pending.get("launch-state") == "launching":
            return True
    return pid_alive(pending.get("pid"))


def launch_worker(path, token):
    """Internal launcher: claim one durable intent, register this pid, then replace this process with its worker."""
    with CommandLock(None, path=path + ".launch.lock") as lock:
        if not lock.acquired:
            return 0   # another launcher/worker holds this intent
        pending = load(path)
        if (pending.get("launch") or {}).get("token") != token or pending.get("launch-state") != "launching":
            return 0   # consumed, superseded, or already registered, even if that worker has since finished
        pending.update({"pid": os.getpid(), "launch-state": "running"})
        save(path, pending)   # same pid will execute the worker; never spawn the worker before its identity is durable
        os.set_inheritable(lock.file.fileno(), True)
        try:
            os.chdir(pending["launch"]["cwd"])
            worker_env = dict(os.environ, CHONGDAE_LAUNCH_TOKEN=token)
            os.execvpe(pending["argv"][0], pending["argv"], worker_env)
        except OSError as err:
            pending.update({"launch-state": "failed", "launch-error": str(err)})
            save(path, pending)
            print("worker could not start: %s" % err, file=sys.stderr)
            return 1


REQUIRES = ("network", "loopback")   # what a task may require of the sandbox its hands run in


def stage_tag(tid, stage, attempts=()):
    """The name a call's work files go under: the task's id for its build, `<id>.<stage>[.<attempt>]` for the roles around it."""
    return tid + ("" if stage == "build" else "." + stage + (".%d" % (len(attempts) + 1) if attempts else ""))


def spawn(target, run, task, provider, plan, attempts=(), stage="build", extra=None):
    """Run a provider command with a request file; read its response file. The provider is argv with {request} and {response}.

    The request carries the contract: the task, the plan sections it closes, the checks that will decide it. Nothing else —
    the provider is a fresh process and must not need this session's context.

    The launch intent is recorded before creating a process; its launcher records its own pid before exec. The provider
    is detached (its own session, output to <tag>.provider.log). A session that exits kills `run` — but not the provider; the next
    `chongdae run` finds the pending record and resumes waiting (or consumes the response that landed meanwhile) instead
    of paying for the work twice. Returns (returncode, response, start_snapshot).
    """
    import subprocess
    import time
    tag = stage_tag(task["id"], stage, attempts)
    req_path = work_path(run, tag + ".request.json")
    res_path = work_path(run, tag + ".response.json")
    pend_path = work_path(run, tag + ".pending.json")
    log_path = work_path(run, tag + ".provider.log")
    os.makedirs(os.path.join(run, LOCAL), exist_ok=True)
    cleanup_completion_acks(run, load_state(run))
    pending = load(pend_path)
    completed = completed_payload(pending, "provider")
    if completed is not None:
        retain_completion(run, task["id"], pend_path, pending, "provider", completed, pending["completed"]["code"])
        return pending["completed"]["code"], completed, pending.get("start")
    native = native_argv(target, provider)
    if native and os.path.exists(res_path):   # the session wrote the subagent's answer: consume it like any provider's
        pending = pending or {"start": dirty(target)}
    elif not pending:
        # A registered worker that ended without a response is still a consumed launch. Resume records no-response;
        # it must not repeat the worker's effects merely because the caller died before retaining that outcome.
        sections = contract_sections(target, plan, task)[0]
        reader = stage == "build" and task.get("role") in CONTRACT_READERS
        req = {"artifact-type": "chongdae/request@1", "stage": task["role"] if reader else stage, "run": os.path.basename(run), "task": task["id"],
               "role": task["role"] if stage == "build" else ("verifier" if stage == "verify" else stage),
               "target": os.path.abspath(target).replace(os.sep, "/"), "goal": plan["goal"], "brief": task.get("brief", ""),
               "closes": task.get("closes", []), "contract": sections,
               **(reader_checks(plan, load_state(run), task) if reader else
                  {"checks": task.get("checks", []) or checks_for_tests(all_tasks(plan, load_state(run)), task), "tests": task.get("tests", [])}),
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
        gone = deleted_by_contract(target, plan, load_state(run), task)
        if gone:
            # the contract deleted these: not tests to keep, nor to be red before the build (hacheong keeps them absent)
            req["tests"] = [t for t in req.get("tests") or [] if t not in gone]
            req["deleted-tests"] = sorted(gone)
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
        pending = launch_pending(pend_path, argv, target, log_path, start=dirty(target))
    else:
        resume_launch(pend_path, pending)   # the same durable intent, even if a previous caller died before registration
    # wait for the provider to END, not for its file to appear: a worker may write the response path more than once (a host's
    # raw last message first, its own whole answer after), and half an answer is not an answer
    if native and not os.path.exists(res_path):   # asked again before the session answered: the same instruction
        return DISPATCH, {"status": "dispatch", "prompt_argv": pending.get("native"), "request": req_path, "response": res_path}, None
    global _CALL_DEADLINE
    if _CALL_DEADLINE is None:
        _CALL_DEADLINE = time.time() + WAIT_BUDGET
    deadline = _CALL_DEADLINE
    while pending_alive(pend_path, pending):
        if time.time() > deadline:
            # still working: hand back to the session instead of outliving its tool call. The provider is detached and its pending
            # record stands; the next `run` resumes waiting for the same work. A session that backgrounds `run` to wait longer
            # ends up orphaning the provider — this is the loop that replaces that.
            since = pending.get("since") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return WAITING, {"status": "waiting", "pid": pending.get("pid") or "launching", "since": since, "log": log_path}, pending.get("start")
        time.sleep(2)   # pending_alive reaps our ended child as it refreshes the durable registration
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
    retain_completion(run, task["id"], pend_path, pending, "provider", response, code)
    return code, response, start


def waiting_text(what, d):
    if d.get("checks"):
        return ("%s: chongdae's own run of its checks is still going (pid %s, since %s; its log: %s) — the call's budget (CHONGDAE_WAIT) is spent; "
                "`chongdae run` again keeps waiting for the same run and reads what it found; do not background `run`"
                % (what, d.get("pid"), d.get("since"), d.get("log")))
    return ("%s: the provider is still working (pid %s, since %s; its output so far: %s) — `chongdae run` again keeps waiting for the same work; "
            "keep `run` in the foreground and resume its pending record after an interruption"
            % (what, d.get("pid"), d.get("since"), d.get("log")))


def waiting_stop(what, d):
    """The call's budget is spent and work is still going: said as `still working:` — the line's first words, not `decision:`,
    and exit WAITING, not DECISION. guin-site, 10-15: a backgrounded `run` said "the provider is still working … do not
    background `run`" on a `decision:` line, and the wrapper around it (`| tail`) exited 0; whoever read the code took it
    as done."""
    print("still working: " + waiting_text(what, d))
    return WAITING


def dispatch_text(what, d):
    return ("session agent: dispatch %s to this host's own subagent — get the prompt with `%s`, give it to a FRESH subagent of this host "
            "(Claude Code: the Agent tool, general-purpose, with that prompt as its task; Codex: spawn_agent), write its final JSON answer VERBATIM to %s "
            "(no edits, no additions), then `chongdae run`. The request is %s."
            % (what, " ".join('"%s"' % a if " " in a else a for a in d.get("prompt_argv") or []), d.get("response"), d.get("request")))


# ---------------------------------------------------------------- leases: who holds which key now — coordination, not the record

# `settings.chongdae.lease` (hunsu.json, hunsu.local.json on top): absent — `claim` as before, written in the record; "local"
# — a file per key, created only if absent, under this machine's git common dir (several sessions on one machine); "git" —
# a ref per key on the remote (`refs/chongdae/claims/<run>/<task>`, a parentless commit whose message is the lease), taken
# with `git push --force-with-lease=<ref>:` and swapped against the value read; an argv — a service's command (README: the
# backend contract). A lease is who holds a key for a while; it enters no branch. The task's result carries the generation
# it was made under, and only the current generation's result is accepted.

LEASE_TTL = 30 * 60        # a hold lapses this long after its last progress (settings.chongdae.lease-ttl, seconds)
LEASE_CEILING = 4 * 3600   # a hold older than this is shown as long-held (settings.chongdae.lease-ceiling, seconds)

_LEASE_CALL = None   # one `run` call's leases: the backend, this session as a holder, what it holds


class LeaseError(Exception):
    """The lease store cannot be reached or answered nonsense. A machine that cannot reach it cannot take: chongdae says so
    and starts nothing untaken."""


def clock():
    """Now, in seconds. A lease's end is the machines' clocks (the git backend has no server clock); tests move it."""
    import time
    return time.time()


def iso(t):
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def epoch(at):
    t = as_utc(at)
    return t.timestamp() if t else 0.0


def ref_part(s):
    """One ref-name component (and file name) for a run, a task or a path: `/` and what git refuses in a ref, percent-encoded."""
    from urllib.parse import quote
    s = quote(str(s), safe="").replace("~", "%7E").replace("..", "%2E%2E")
    if s.startswith("."):
        s = "%2E" + s[1:]
    if s.endswith(".lock"):
        s = s[:-5] + "%2Elock"
    if s.endswith("."):
        s = s[:-1] + "%2E"
    return s or "%2E"


def task_key(run_name, tid):
    return "%s/%s" % (ref_part(run_name), ref_part(tid))


def scope_key(path):
    return "scope/" + ref_part(path or ".")


def scopes_overlap(a, b):
    """Two scope entries overlap when one holds the other (the project root holds everything)."""
    a, b = (a or "").strip("/"), (b or "").strip("/")
    return a == b or not a or not b or a.startswith(b + "/") or b.startswith(a + "/")


def this_session():
    """The host's id for this session (CHONGDAE_SESSION, else the host's own), or None."""
    return os.environ.get("CHONGDAE_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID") or None


def other_session(ts):
    """A known local owner differs from this session, including a caller whose identity is unknown.
    Old records without an owner remain usable; an absent caller id is never authority over a known owner's work."""
    return bool(ts.get("added-in") and ts["added-in"] != this_session())


def local_owner_blocks(target, d, tid, ts, leases=None):
    """Keep added-in authoritative until an actual lease has superseded it. Merely configuring a lease backend
    cannot let the next run claim another session's task. An explicit hold, including one later released/lapsed,
    establishes lease authority; its normal lifecycle decides who can proceed. A known owner requires caller identity."""
    if not other_session(ts):
        return False
    if not this_session() or not leases:
        return True
    established = ts.get("lease-established") or ts.get("lease-held") or ts.get("lease") or ts.get("gen")
    return not (established or leases.current(task_key(os.path.basename(d), tid)))


def mutation_owner_refusal(target, d, tid, ts):
    """The authority to advance a task also applies to judgments and edits of its record. A signature (`--by`) is
    evidence of who decided, never an ownership transfer. Only take/claim have their explicit transfer rules."""
    leases = lease_backend(target)
    try:
        cur = leases.current(task_key(os.path.basename(d), tid)) if leases else None
        if cur and not same_holder(cur.get("holder"), lease_holder(target)):
            return "%s is held by another session — claim it after release or expiry, or explicitly `claim --break %s --why WHY`; nothing changed" % (tid, tid)
        if other_session(ts) and not (this_session() and cur and same_holder(cur.get("holder"), lease_holder(target))):
            return "%s belongs to another session (or this call has no session identity) — its owner must act, or use `chongdae take %s --why WHY` for an idle task's handover (including interrupted operation recovery); nothing changed" % (tid, tid)
        if not leases and ts.get("claimed_by") and claim_owner(ts["claimed_by"]) != me(target):
            return "%s is claimed by %s — its owner must release it before this command can change it; nothing changed" % (tid, signer_text(ts["claimed_by"]))
    except LeaseError as err:
        return "the lease store cannot be reached (%s) — ownership of %s cannot be established; nothing changed" % (err, tid)
    return None


def task_mutation_guard(args):
    """Preflight task-changing commands before checks, operations, response rotation, or state writes."""
    if args.cmd not in ("retry", "accept", "confirm", "unstage", "adopt", "did", "dispute", "drop", "add", "take", "claim"):
        return None
    if args.cmd == "add" and not args.check:
        return None
    d = run_dir(args.target)
    if not d:
        return None   # the command retains its own missing-run/task diagnostics
    state = load_state(d)
    tid = args.id if args.cmd == "add" else args.task
    ts = state.get("tasks", {}).get(tid)
    if not ts:
        return None
    refused = mutation_owner_refusal(args.target, d, tid, ts) if args.cmd not in ("take", "claim") else None
    if refused:
        return refused
    pending_operation = operation_pending(d, tid)
    release_idle_claim = (args.cmd == "claim" and (args.release or args.by == "") and pending_operation
                          and not pid_alive(pending_operation.get("operation-pid")) and not task_in_flight(d, tid))
    if args.cmd not in ("did", "take") and pending_operation and not release_idle_claim:
        return "%s has an unresolved did operation — resume or reconcile it with `chongdae did` before changing this task; nothing changed" % tid
    return None


def task_in_flight(d, tid):
    """Work a task still has running, including a host-native dispatch awaiting its answer. Match the request's task,
    not a filename prefix: tasks `a` and `a.b` must not hold each other. Completed subprocesses can be resumed elsewhere."""
    active = []
    for path in glob.glob(work_path(d, "*.pending.json")):
        tag = os.path.basename(path)[:-len(".pending.json")]
        if tag != tid + ".checks" and load(work_path(d, tag + ".request.json")).get("task") != tid:
            continue
        pending = load(path)
        if pending_alive(path, pending) or (pending.get("native") and not os.path.exists(work_path(d, tag + ".response.json"))):
            active.append(tag)
    return sorted(active)


def lease_holder(target, by=None):
    """This session as a holder: the machine (CHONGDAE_MACHINE, else the host name), the host's session id (CHONGDAE_SESSION,
    else the host's own), and the agent signing. Two holders are the same when machine and session are."""
    import socket
    h = {"machine": os.environ.get("CHONGDAE_MACHINE") or socket.gethostname() or "unknown",
         "session": this_session() or "-",
         "agent": agent_signer(target)["agent"]}
    if by:
        h["by"] = by
    return h


def same_holder(a, b):
    return isinstance(a, dict) and isinstance(b, dict) and a.get("machine") == b.get("machine") and a.get("session") == b.get("session")


def holder_text(h):
    if not isinstance(h, dict):
        return "?"
    s = h.get("session") or "-"
    return "%s/%s%s" % (h.get("machine") or "?", s if len(s) <= 13 else s[:8] + "…", " (by %s)" % h["by"] if h.get("by") else "")


def lapsed(lease, now=None):
    """No progress for its ttl: the hold is over, and another session may take the key (recorded as taken over from a lapsed hold)."""
    return epoch(lease.get("last-progress") or lease.get("taken")) + float(lease.get("ttl") or LEASE_TTL) < (clock() if now is None else now)


def long_held(lease, ceiling, now=None):
    return (clock() if now is None else now) - epoch(lease.get("taken")) > ceiling


def lease_age(lease, now=None):
    now = clock() if now is None else now
    return "held %s, last progress %s ago" % (seconds_text(int(max(0, now - epoch(lease.get("taken"))))),
                                              seconds_text(int(max(0, now - epoch(lease.get("last-progress") or lease.get("taken"))))))


def lease_from_text(frm):
    if not isinstance(frm, dict):
        return ""
    if frm.get("broken") is not None:
        return "broken from %s (gen %s): %s" % (holder_text(frm.get("holder")), frm.get("gen"), frm.get("broken"))
    return "taken over from a lapsed hold of %s (gen %s, last progress %s)" % (holder_text(frm.get("holder")), frm.get("gen"), when(frm.get("last-progress")))


class CasLeases:
    """take / renew / release / list over a store that offers create-if-absent and compare-and-swap per key (a local file, a
    ref on a remote). The judging is here; the store judges nothing."""

    def __init__(self, store, ttl):
        self.store, self.ttl = store, ttl

    def take(self, key, holder, gen_floor=0, over=None, why=None, extra=None):
        cur, ver = self.store.read(key)
        now = clock()
        if cur is not None and cur.get("released"):
            # a released key keeps its generation: the next take counts on from it, whoever's record it has not reached
            if over is not None:
                return {"ok": False, "lease": None}
            new = {"key": key, "holder": holder, "gen": max(int(gen_floor or 0), int(cur.get("gen") or 0)) + 1,
                   "taken": iso(now), "renewed": iso(now), "last-progress": iso(now), "ttl": self.ttl, **(extra or {})}
            if not self.store.swap(key, new, ver):
                return {"ok": False, "lease": self.current(key)}
            return {"ok": True, "lease": new}
        new = {"key": key, "holder": holder, "gen": max(int(gen_floor or 0), int((cur or {}).get("gen") or 0)) + 1,
               "taken": iso(now), "renewed": iso(now), "last-progress": iso(now), "ttl": self.ttl, **(extra or {})}
        if cur is None:
            if over is not None:
                return {"ok": False, "lease": None}
            ok = self.store.create(key, new)
        elif over is not None:
            if int(cur.get("gen") or 0) != int(over):
                return {"ok": False, "lease": cur}
            new["from"] = {"holder": cur.get("holder"), "gen": cur.get("gen"), "broken": why or "", "last-progress": cur.get("last-progress"), "lapsed": lapsed(cur, now)}
            ok = self.store.swap(key, new, ver)
        elif same_holder(cur.get("holder"), holder):
            return {"ok": True, "lease": cur, "had": True}
        elif lapsed(cur, now):
            new["from"] = {"holder": cur.get("holder"), "gen": cur.get("gen"), "lapsed": True, "last-progress": cur.get("last-progress")}
            ok = self.store.swap(key, new, ver)
        else:
            return {"ok": False, "lease": cur}
        if not ok:
            return {"ok": False, "lease": self.current(key)}
        return {"ok": True, "lease": new}

    def renew(self, key, holder, gen):
        cur, ver = self.store.read(key)
        if not cur or cur.get("released") or int(cur.get("gen") or 0) != int(gen) or not same_holder(cur.get("holder"), holder):
            return {"ok": False, "lease": None if (cur or {}).get("released") else cur}
        new = dict(cur, renewed=iso(clock()))
        new["last-progress"] = new["renewed"]
        if not self.store.swap(key, new, ver):
            return {"ok": False, "lease": self.current(key)}
        return {"ok": True, "lease": new}

    def release(self, key, gen, by=None):
        """Not a delete: the key becomes a released marker that keeps its generation (`{key, released, gen, by}`), so the next
        take counts on from it even on a machine whose record never saw this one. `claim --list --prune` removes old markers."""
        cur, ver = self.store.read(key)
        if not cur or cur.get("released") or int(cur.get("gen") or 0) != int(gen):
            return {"ok": False, "lease": None if (cur or {}).get("released") else cur}
        marker = {"key": key, "released": iso(clock()), "gen": int(gen), "by": by or holder_text(cur.get("holder"))}
        return {"ok": bool(self.store.swap(key, marker, ver)), "lease": None}

    def list(self, prefix=""):
        return [l for l, _ in self.store.all() if str(l.get("key", "")).startswith(prefix) and not l.get("released")]

    def current(self, key):
        cur = self.store.read(key)[0]
        return None if cur is None or cur.get("released") else cur

    def prune(self, age, prefix=""):
        """Delete released markers older than `age` seconds; a take after that counts from the record's generation."""
        now, out = clock(), []
        for l, ver in self.store.all():
            if l.get("released") and str(l.get("key", "")).startswith(prefix) and now - epoch(l["released"]) > age and self.store.delete(l["key"], ver):
                out.append(l["key"])
        return out


class LocalStore:
    """One file per key under this machine's git common dir (`chongdae-claims/`; shared by its worktrees), else under
    `.chongdae/local/claims/`. Created with O_CREAT|O_EXCL; swapped (renewed, broken, released to a marker that keeps the
    generation) and pruned under a per-key lock file. Atomic on one machine."""

    def __init__(self, target):
        import subprocess
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=target, capture_output=True, text=True)
        out = common.stdout.strip()
        self.dir = os.path.join(target, out, "chongdae-claims") if common.returncode == 0 and out else os.path.join(target, RUNS, LOCAL, "claims")
        os.makedirs(self.dir, exist_ok=True)

    def path(self, key):
        return os.path.join(self.dir, ref_part(key) + ".json")

    def _read_path(self, path):
        import hashlib
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except FileNotFoundError:
            return None, None
        try:
            return json.loads(raw.decode("utf-8")), hashlib.sha1(raw).hexdigest()
        except ValueError:
            return None, hashlib.sha1(raw).hexdigest()   # a torn write: nobody's lease; a swap may replace it

    def read(self, key):
        return self._read_path(self.path(key))

    def _lock(self, key):
        import time
        lock = self.path(key) + ".lock"
        for _ in range(500):
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return lock
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(lock) > 10:
                        os.remove(lock)   # a holder of the lock died between two lines
                        continue
                except OSError:
                    pass
                time.sleep(0.01)
        raise LeaseError("the lock on %s stayed taken" % key)

    def create(self, key, lease):
        try:
            fd = os.open(self.path(key), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(lease, fh, ensure_ascii=False)
        return True

    def swap(self, key, lease, version):
        lock = self._lock(key)
        try:
            if self.read(key)[1] != version:
                return False
            tmp = self.path(key) + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as fh:
                json.dump(lease, fh, ensure_ascii=False)
            os.replace(tmp, self.path(key))
            return True
        finally:
            os.remove(lock)

    def delete(self, key, version):
        lock = self._lock(key)
        try:
            if self.read(key)[1] != version:
                return False
            os.remove(self.path(key))
            return True
        finally:
            os.remove(lock)

    def all(self):
        out = []
        for name in sorted(os.listdir(self.dir)):
            if name.endswith(".json"):
                lease, ver = self._read_path(os.path.join(self.dir, name))
                if lease:
                    out.append((lease, ver))
        return out


class GitStore:
    """One ref per key on the remote: `refs/chongdae/claims/<key>` -> a parentless commit with the empty tree whose message is
    the lease. Created with `--force-with-lease=<ref>:` (only if absent), swapped with `--force-with-lease=<ref>:<sha read>` —
    a release too: the ref then points at a released marker that keeps the generation; only `claim --list --prune` deletes a
    ref. Read by fetching the claims into `refs/chongdae/seen/` (pruned). Nothing enters a branch."""

    NS = "refs/chongdae/claims/"
    SEEN = "refs/chongdae/seen/"
    ID = {"GIT_AUTHOR_NAME": "chongdae", "GIT_AUTHOR_EMAIL": "chongdae@lease", "GIT_COMMITTER_NAME": "chongdae", "GIT_COMMITTER_EMAIL": "chongdae@lease"}

    def __init__(self, target, remote):
        self.target, self.remote = target, remote
        self._fresh = False

    def git(self, *a, stdin=None, env=None):
        import subprocess
        return subprocess.run(["git", *a], cwd=self.target, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              input=stdin, env=dict(os.environ, **(env or {})))

    def refresh(self):
        done = self.git("fetch", "-q", "--prune", "--no-tags", self.remote, "+%s*:%s*" % (self.NS, self.SEEN))
        if done.returncode:
            raise LeaseError("cannot reach the lease remote %r: %s" % (self.remote, (done.stderr or done.stdout).strip().split("\n")[-1][:200]))

    def _lease_of(self, sha):
        body = self.git("cat-file", "commit", sha).stdout
        msg = body.split("\n\n", 1)[1] if "\n\n" in body else ""
        try:
            return json.loads(msg)
        except ValueError:
            return None

    def read(self, key):
        self.refresh()
        sha = self.git("rev-parse", "-q", "--verify", self.SEEN + key).stdout.strip()
        return (self._lease_of(sha), sha) if sha else (None, None)

    def _commit(self, lease):
        tree = self.git("mktree", stdin="").stdout.strip()
        made = self.git("commit-tree", tree, "-m", json.dumps(lease, ensure_ascii=False, sort_keys=True), env=self.ID)
        if made.returncode or not made.stdout.strip():
            raise LeaseError("cannot write a lease object: %s" % made.stderr.strip()[-200:])
        return made.stdout.strip()

    def _push(self, ref, expect, src):
        done = self.git("push", "-q", "--no-verify", "--force-with-lease=%s:%s" % (ref, expect or ""), self.remote, "%s:%s" % (src, ref))
        if done.returncode == 0:
            return True
        said = (done.stderr or done.stdout)
        if "stale info" in said or "rejected" in said or "already exists" in said or "fetch first" in said:
            return False
        raise LeaseError("the lease remote %r refused the push: %s" % (self.remote, said.strip().split("\n")[-1][:200]))

    def create(self, key, lease):
        return self._push(self.NS + key, "", self._commit(lease))

    def swap(self, key, lease, version):
        return self._push(self.NS + key, version, self._commit(lease))

    def delete(self, key, version):
        return self._push(self.NS + key, version, "")

    def all(self):
        self.refresh()
        out = []
        for line in self.git("for-each-ref", "--format=%(objectname)", self.SEEN).stdout.split("\n"):
            if line.strip():
                lease = self._lease_of(line.strip())
                if lease:
                    out.append((lease, line.strip()))
        return out


class ArgvLeases:
    """A service backend: `<argv> take|renew|release|list|prune KEY [--holder H] [--ttl S] [--gen N] [--task T] [--scope P]
    [--over G] [--why W] [--by B] [--age S]`, one JSON object on stdout (README: the contract). A non-zero exit or no JSON:
    the store could not be reached."""

    def __init__(self, target, argv, ttl):
        self.target, self.argv, self.ttl = target, [str(a) for a in argv], ttl

    def call(self, *a):
        import subprocess
        try:
            done = subprocess.run(self.argv + [str(x) for x in a], cwd=self.target, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise LeaseError("the lease command %s did not answer: %s" % (self.argv[0], err))
        if done.returncode:
            raise LeaseError("the lease command exited %d: %s" % (done.returncode, (done.stderr or done.stdout).strip()[-200:]))
        try:
            return json.loads(done.stdout.strip().split("\n")[-1])
        except (ValueError, IndexError):
            raise LeaseError("the lease command answered no JSON: %r" % done.stdout[-200:])

    def take(self, key, holder, gen_floor=0, over=None, why=None, extra=None):
        a = ["take", key, "--holder", json.dumps(holder, ensure_ascii=False), "--ttl", self.ttl, "--gen", int(gen_floor or 0) + 1]
        for k in ("task", "scope"):
            if (extra or {}).get(k) is not None:
                a += ["--" + k, extra[k]]
        if over is not None:
            a += ["--over", over, "--why", why or ""]
        r = self.call(*a)
        return {"ok": bool(r.get("ok")), "lease": r.get("lease")}

    def renew(self, key, holder, gen):
        r = self.call("renew", key, "--holder", json.dumps(holder, ensure_ascii=False), "--gen", gen)
        return {"ok": bool(r.get("ok")), "lease": r.get("lease")}

    def release(self, key, gen, by=None):
        r = self.call("release", key, "--gen", gen, *(["--by", by] if by else []))
        return {"ok": bool(r.get("ok")), "lease": r.get("lease")}

    def list(self, prefix=""):
        return [l for l in (self.call("list", prefix).get("leases") or []) if isinstance(l, dict) and not l.get("released")]

    def prune(self, age, prefix=""):
        return list(self.call("prune", prefix, "--age", int(age)).get("pruned") or [])

    def current(self, key):
        return next((l for l in self.list(key) if l.get("key") == key), None)


def lease_backend(target):
    """The project's lease backend, or None (no `lease` setting: `claim` is written in the record, as before)."""
    s = settings(target)
    kind = s.get("lease")
    if not kind:
        return None
    ttl = int(s.get("lease-ttl") or LEASE_TTL)
    if kind == "local":
        backend = CasLeases(LocalStore(target), ttl)
    elif kind == "git":
        backend = CasLeases(GitStore(target, s.get("lease-remote") or "origin"), ttl)
    elif isinstance(kind, list) and kind and all(isinstance(a, str) for a in kind):
        backend = ArgvLeases(target, kind, ttl)
    else:
        raise SystemExit("settings.chongdae.lease %r: leave it out, or \"local\", \"git\", or a command as an argv list" % (kind,))
    backend.ceiling = int(s.get("lease-ceiling") or LEASE_CEILING)
    backend.max = int(s.get("lease-max") or 1)
    backend.kind = kind if isinstance(kind, str) else "command"
    return backend


def live_holds(leases, holder):
    """The task keys this session holds now (scope keys ride with their task)."""
    return [l for l in leases.list() if not str(l.get("key", "")).startswith("scope/") and same_holder(l.get("holder"), holder) and not lapsed(l)]


def take_task(leases, run_name, task, ts, holder, over=None, why=None):
    """Take a task's key, then one key per scope path; a scope that overlaps one another session holds live gives every key
    back. {"ok", "lease", "conflict"?}. On success the machine-local overlay keeps what this session holds (`lease-held`)."""
    key = task_key(run_name, task["id"])
    floor = max(int(ts.get("gen") or 0), int((ts.get("lease") or {}).get("gen") or 0), int((ts.get("lease-held") or {}).get("gen") or 0))
    r = leases.take(key, holder, floor, over=over, why=why, extra={"task": "%s/%s" % (run_name, task["id"])})
    if not r["ok"]:
        return r
    lease, got, conflict = r["lease"], [], None
    scopes = task.get("scope") or []
    for p in scopes:
        sk = scope_key(p)
        s = leases.take(sk, holder, 0, extra={"task": "%s/%s" % (run_name, task["id"]), "scope": p})
        if not s["ok"] and s.get("lease") and (s["lease"].get("task") == "%s/%s" % (run_name, task["id"])) and over is not None:
            s = leases.take(sk, holder, 0, over=s["lease"].get("gen"), why=why, extra={"task": "%s/%s" % (run_name, task["id"]), "scope": p})   # the broken hold's scopes go with it
        if not s["ok"]:
            conflict = s.get("lease") or {"key": sk}
            break
        got.append(s["lease"])
    if conflict is None and scopes:
        conflict = next((l for l in leases.list("scope/") if not same_holder(l.get("holder"), holder) and not lapsed(l)
                         and any(scopes_overlap(l.get("scope"), p) for p in scopes)), None)
    if conflict is not None:
        for s in got:
            leases.release(s["key"], s["gen"])
        if not r.get("had"):
            leases.release(key, lease["gen"])
        return {"ok": False, "lease": conflict, "conflict": "scope"}
    ts["lease-held"] = {"gen": lease["gen"], "holder": holder, "scopes": [[s["key"], s["gen"]] for s in got]}
    ts["lease-established"] = True   # an explicit/actual lease supersedes the local added-in hint even after release
    return {"ok": True, "lease": lease, "had": r.get("had")}


def release_task(leases, run_name, tid, ts):
    """Give back a task's key and its scope keys (done, dropped, closed). What this session held leaves the overlay."""
    held = ts.pop("lease-held", None)
    if not held or leases is None:
        return
    try:
        by = holder_text(held.get("holder"))
        for k, g in held.get("scopes") or []:
            leases.release(k, g, by)
        leases.release(task_key(run_name, tid), held["gen"], by)
    except LeaseError as err:
        print("  (%s: its hold could not be given back — %s; it lapses on its own)" % (tid, err))


def lease_into_record(ts, lease):
    """The result carries the generation it was made under, and how the hold began (taken over from a lapsed or broken one)."""
    if not lease:
        return
    ts["gen"] = lease["gen"]
    ts["lease"] = {"gen": lease["gen"], "holder": lease.get("holder"), "taken": lease.get("taken"), **({"from": lease["from"]} if lease.get("from") else {})}


def lost_text(tid, held, cur):
    """This session's hold on a task is gone: who has it now, and why."""
    if not cur:
        return "%s: this session's hold (gen %s) is gone from the lease store" % (tid, held.get("gen"))
    frm = cur.get("from") or {}
    how = ("broke it: %s" % frm.get("broken")) if frm.get("broken") is not None else "took it after it lapsed (no progress for %s)" % seconds_text(int(cur.get("ttl") or LEASE_TTL))
    return "%s: this session's hold (gen %s) was taken — %s holds it now (gen %s) and %s" % (tid, held.get("gen"), holder_text(cur.get("holder")), cur.get("gen"), how)


def lease_step(ctx, task, ts):
    """Under a lease, `run` advances only the tasks this session holds, and takes a ready unheld one when it holds fewer than
    `lease-max`. None: go on with the task; "skip": not this session's; an int: the stop's exit code."""
    call, d = _LEASE_CALL, ctx["d"]
    leases, holder, run_name, tid = call["leases"], call["holder"], os.path.basename(d), task["id"]
    key = task_key(run_name, tid)
    try:
        cur = leases.current(key)
        held = ts.get("lease-held")
        if held and same_holder(held.get("holder"), holder) and (cur is None or int(cur.get("gen") or 0) != int(held["gen"])) \
                and not (cur and same_holder(cur.get("holder"), holder)):
            if cur is not None:
                ts.pop("lease-held", None)
                save_state(d, ctx["state"])
                return stop("%s — this session stops on it; its work stays in this tree (or its branch) for the holder to use, and a result made "
                            "under gen %s will not be accepted" % (lost_text(tid, held, cur), held["gen"]))
            ts.pop("lease-held", None)   # released or pruned while nobody took it: take it again below, as a new generation
        if cur and same_holder(cur.get("holder"), holder):
            if not ts.get("lease-held") or int(ts["lease-held"].get("gen") or 0) != int(cur["gen"]):
                r = take_task(leases, run_name, task, ts, holder)   # held here, unknown to this tree's overlay (another worktree): adopt it, scopes too
                if not r["ok"]:
                    print("  %s: its scope is held elsewhere (%s) — not this session's to advance yet" % (tid, holder_text((r.get("lease") or {}).get("holder"))))
                    return "skip"
                save_state(d, ctx["state"])
            call["held"][tid] = cur
            return None
        if cur and not lapsed(cur):
            print("  %s is held by %s (gen %s, %s) — not this session's to advance" % (tid, holder_text(cur.get("holder")), cur.get("gen"), lease_age(cur)))
            return "skip"
        mine = live_holds(leases, holder)
        if len(mine) >= leases.max:
            print("  %s is ready, but this session holds %s already (settings.chongdae.lease-max: %d)" % (tid, ", ".join(l.get("task") or l["key"] for l in mine), leases.max))
            return "skip"
        r = take_task(leases, run_name, task, ts, holder)
    except LeaseError as err:
        return stop("%s: the lease store cannot be reached (%s) — this machine cannot take or renew a hold, and starts nothing untaken; "
                    "reach it and `chongdae run` again" % (tid, err))
    if not r["ok"]:
        who = (r.get("lease") or {})
        print("  %s: %s — trying the next ready task" % (tid, "its scope %s overlaps one %s holds for %s" % (", ".join(task.get("scope") or []), holder_text(who.get("holder")), who.get("task"))
                                                        if r.get("conflict") == "scope" else "%s took it first (gen %s)" % (holder_text(who.get("holder")), who.get("gen"))))
        return "skip"
    save_state(d, ctx["state"])
    lease = r["lease"]
    call["held"][tid] = lease
    print("  claimed %s (gen %s)%s" % (tid, lease["gen"], " — " + lease_from_text(lease.get("from")) if lease.get("from") else ""))
    return None


def work_mark(target, ts):
    """What progress is measured by: the task's record and the tree's changes. A `run` that sees either move renews the hold;
    a run that sees nothing new does not (a hold is never renewed by time alone)."""
    import hashlib
    pub = split_private(ts)[0]
    return hashlib.sha1(json.dumps([pub, dirty(target)], sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def lease_progress(target, call):
    """After a `run` pass: renew what this session holds where the task or the tree moved; a refused renewal is said."""
    d = run_dir(target)
    if not d:
        return None
    state = load_state(d)
    leases, holder, run_name, code = call["leases"], call["holder"], os.path.basename(d), None
    for tid in call["held"]:
        ts = state["tasks"].get(tid)
        if not ts or ts.get("status") in CLOSED or not ts.get("lease-held"):
            continue
        mark = work_mark(target, ts)
        if mark == ts.get("lease-work"):
            continue
        held = ts["lease-held"]
        try:
            r = leases.renew(task_key(run_name, tid), holder, held["gen"])
            for k, g in held.get("scopes") or []:
                leases.renew(k, holder, g)
        except LeaseError as err:
            print("  (%s: its hold could not be renewed — %s)" % (tid, err))
            continue
        if not r["ok"]:
            print("decision: %s — this session stops on it" % lost_text(tid, held, r.get("lease")))
            ts.pop("lease-held", None)
            code = DECISION
        else:
            if ts.get("status") == "produced" and ts.get("gen") != held["gen"]:
                lease_into_record(ts, r["lease"])   # the result waiting at its gate carries the generation it was made under
            ts["lease-work"] = work_mark(target, ts)
    save_state(d, state)
    return code


def parent_progress(target, call):
    """A child run holds its parent's task: a `run` that saw the child's record or the tree move renews that hold. Refused —
    someone took the parent's task after it lapsed, or broke it — the child stops (its branch stays for the new holder)."""
    import hashlib
    d = run_dir(target)
    state = load_state(d) if d else {}
    link = state.get("parent") or {}
    if not link.get("gen"):
        return None
    note = load(work_path(d, "parent-lease.json"))
    mark = hashlib.sha1(json.dumps([{t: split_private(ts)[0] for t, ts in state["tasks"].items()}, dirty(target)], sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    if mark == note.get("mark"):
        return None
    try:
        r = call["leases"].renew(task_key(link["run"], link["task"]), call["holder"], link["gen"])
        for k, g in note.get("scopes") or []:
            call["leases"].renew(k, call["holder"], g)
    except LeaseError as err:
        print("  (the hold on %s/%s could not be renewed — %s)" % (link["run"], link["task"], err))
        return None
    if not r["ok"]:
        print("decision: %s — this child run stops; its branch stays for the new holder" % lost_text("%s/%s" % (link["run"], link["task"]), link, r.get("lease")))
        return DECISION
    save(work_path(d, "parent-lease.json"), dict(note, mark=mark))
    return None


def parent_refusal(target, state):
    """A child run lands only while its parent's task is still held at the generation it started under (C8)."""
    link = state.get("parent") or {}
    if not link.get("gen"):
        return None
    try:
        leases = lease_backend(target)
        cur = leases.current(task_key(link["run"], link["task"])) if leases else None
    except LeaseError as err:
        return "the lease store cannot be reached (%s): whether %s/%s is still this run's cannot be told" % (err, link["run"], link["task"])
    if cur and int(cur.get("gen") or 0) != int(link["gen"]):
        return "%s/%s is held by %s at gen %s; this run started under gen %s — its result is not the current holder's, and it does not land (its branch stays for the holder to use)" % (
            link["run"], link["task"], holder_text(cur.get("holder")), cur.get("gen"), link["gen"])
    return None


def result_gen_refusal(target, d, tid, ts):
    """C8: a result made under a generation that is no longer the task's is not accepted. None, or why not."""
    leases = lease_backend(target)
    if not leases or not ts.get("gen"):
        return None
    try:
        cur = leases.current(task_key(os.path.basename(d), tid))
    except LeaseError as err:
        return "the lease store cannot be reached (%s): whether this result is the current holder's cannot be told" % err
    if cur and int(cur.get("gen") or 0) != int(ts["gen"]):
        return "this result was made under gen %s; %s holds the task at gen %s — only the current holder's result is accepted" % (ts["gen"], holder_text(cur.get("holder")), cur.get("gen"))
    return None


def release_result(target, d, tid, ts, only_mine=False):
    """A task left the open set (done, dropped, its run closed): its key goes back. The holder's machine gives back its scope
    keys too; a person's confirm elsewhere gives back the task's key by the result's generation (its scope keys lapse)."""
    try:
        leases = lease_backend(target)
    except SystemExit:
        return
    if not leases:
        return
    held = ts.get("lease-held")
    if held and only_mine and not same_holder(held.get("holder"), lease_holder(target)):
        return   # another session on this machine holds it: its hold is not this run's close to give back
    if held and ts.get("status") in CLOSED:
        if not ts.get("gen") and ts.get("status") != "dropped":
            ts["gen"] = held["gen"]
        if ts.get("status") == "dropped" and not ts.get("lease"):
            lease_into_record(ts, {"gen": held["gen"], "holder": held.get("holder")})
    if held:
        release_task(leases, os.path.basename(d), tid, ts)
    elif ts.get("gen"):
        try:
            leases.release(task_key(os.path.basename(d), tid), ts["gen"])
        except LeaseError as err:
            print("  (%s: its hold could not be given back — %s; it lapses on its own)" % (tid, err))


# ---------------------------------------------------------------- the remote: absent, "sync", "shared"

class RemoteStop(Exception):
    """Under `remote: "shared"` the remote is the one truth: a push that still fails after fetch-and-reconcile stops the command."""


def remote_mode(target):
    m = settings(target).get("remote")
    if m not in (None, "", "sync", "shared"):
        raise SystemExit("settings.chongdae.remote %r: leave it out, or \"sync\" or \"shared\"" % (m,))
    return m or None


def record_remote(target):
    """(remote, branch) the record travels to: the branch's own remote (else `lease-remote`, else origin), the current branch."""
    import subprocess
    git = lambda *a: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    branch = git("symbolic-ref", "-q", "--short", "HEAD")
    remote = (git("config", "branch.%s.remote" % branch) if branch else "") or settings(target).get("lease-remote") or "origin"
    return remote, branch


def reconcile(target, remote, branch):
    """Fetch the branch and take what the remote has: a fast-forward, or a merge (each machine writes its own task files, so the
    record merges). (ok, what went wrong)."""
    import subprocess
    git = lambda *a: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
    f = git("fetch", "-q", remote, branch)
    if f.returncode:
        if "couldn't find remote ref" in (f.stderr or ""):
            return True, ""   # the remote has no such branch yet: nothing to take
        return False, "fetch from %s failed: %s" % (remote, (f.stderr or f.stdout).strip().split("\n")[-1][:200])
    theirs = git("rev-parse", "FETCH_HEAD").stdout.strip()
    if not theirs or git("merge-base", "--is-ancestor", theirs, "HEAD").returncode == 0:
        return True, ""
    m = git("merge", "-q", "--no-edit", theirs)
    if m.returncode:
        git("merge", "--abort")
        return False, "merging %s/%s does not go cleanly: %s" % (remote, branch, (m.stderr or m.stdout).strip().split("\n")[-1][:200])
    return True, ""


def remote_before(target, what):
    """`shared`: fetch before a claim or a step, and take what the remote has. A stop (exit 2) when that fails."""
    if remote_mode(target) != "shared":
        return None
    remote, branch = record_remote(target)
    if not branch:
        return stop("settings.chongdae.remote is shared, but HEAD is on no branch — check one out before %s" % what)
    ok, why = reconcile(target, remote, branch)
    if not ok:
        return stop("settings.chongdae.remote is shared and the remote is the one truth: %s — reconcile it by hand (`git pull %s %s`), then %s again" % (why, remote, branch, what))
    return None


def push_record(target):
    """After a judgment's record commit: `sync` pushes and goes on when it cannot (saying what is behind; the next judgment
    pushes again); `shared` pushes, and on a refusal fetches, reconciles and pushes again — and stops when that fails too.
    Declaring either in hunsu.json is the project's consent to chongdae pushing its records; absent, nothing is pushed."""
    import subprocess
    mode = remote_mode(target)
    if not mode:
        return
    git = lambda *a: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
    remote, branch = record_remote(target)
    if not branch:
        print("  (record not pushed: HEAD is on no branch)")
        return
    push = lambda: git("push", "-q", remote, "HEAD:refs/heads/" + branch)
    done = push()
    if done.returncode == 0:
        return
    why = (done.stderr or done.stdout).strip().split("\n")[-1][:200]
    if mode == "sync":
        ahead = git("rev-list", "--count", "%s/%s..HEAD" % (remote, branch))
        n = ahead.stdout.strip() if ahead.returncode == 0 else "?"
        print("  (record not pushed to %s/%s: %s — %s commit(s) of this branch are not there; the next judgment pushes again)" % (remote, branch, why, n))
        return
    ok, rwhy = reconcile(target, remote, branch)
    if ok and push().returncode == 0:
        print("  (the remote had moved: fetched, reconciled and pushed the record to %s/%s)" % (remote, branch))
        return
    raise RemoteStop("the record is committed here, but %s/%s did not take it (%s%s) — under settings.chongdae.remote \"shared\" the remote is the one truth: "
                     "fetch, reconcile (`git pull %s %s`) and push (`git push %s HEAD:%s`), then go on" % (remote, branch, why, "; " + rwhy if rwhy else "", remote, branch, remote, branch))


def upstream_line(target):
    """Where this branch stands against its upstream, in one line — read from the local remote-tracking refs only, never a
    fetch (a session start or a close does not wait on the network): `main: no upstream` when the repository has a remote
    and the branch tracks nothing; `main: N commits not on origin/main (as of the last fetch)` (and, if any, how many of
    origin/main's are not here). None when level, detached, outside git, or with no remote at all. Said whatever
    settings.chongdae.remote is: that decides what chongdae pushes, not whether anyone is told. guin-site 2026-10-15: 213
    commits sat unpushed for 10 days, main had no upstream, and nothing said so."""
    import subprocess
    git = lambda *a: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        branch = git("symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
        if not branch or not git("remote").stdout.strip():
            return None
        up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if up.returncode:
            if git("config", "branch.%s.merge" % branch).stdout.strip():
                return "%s: its upstream has not been fetched yet (no remote-tracking ref)" % branch
            return "%s: no upstream" % branch
        counts = git("rev-list", "--left-right", "--count", "HEAD...@{u}").stdout.split()
    except OSError:
        return None   # no git here: nothing to say
    if len(counts) != 2 or not all(c.isdigit() for c in counts):
        return None
    ahead, behind = int(counts[0]), int(counts[1])
    if not ahead and not behind:
        return None
    where = up.stdout.strip()
    said = [x for x in ("%d commit%s not on %s" % (ahead, "" if ahead == 1 else "s", where) if ahead else "",
                        "%d of %s's not here" % (behind, where) if behind else "") if x]
    return "%s: %s (as of the last fetch)" % (branch, "; ".join(said))


# ---------------------------------------------------------------- parents and children: a child run says which task of which run it does

def child_runs(target, run_name):
    """The runs whose `parent` names this run — computed from the children's own records, never kept in the parent's state:
    runs in this tree, in its worktrees, and on its branches and remote-tracking branches (a child on another machine pushed
    its branch). [(run id, parent link, status, {task status: n}, where)]."""
    import subprocess
    found = {}

    def tally(statuses):
        out = {}
        for s in statuses:
            out[s] = out.get(s, 0) + 1
        return out

    places = [(target, "here")] + [(w, "worktree %s" % os.path.basename(w)) for w in sorted(glob.glob(os.path.join(target, RUNS, "wt", "*")))]
    for root, where in places:
        for r in all_runs(root):
            st = load_state(r)
            link = st.get("parent") or {}
            if link.get("run") == run_name and os.path.basename(r) not in found:
                found[os.path.basename(r)] = (link, st.get("status", "?"), tally(ts.get("status", "?") for ts in st["tasks"].values()), where)
    git = lambda *a, **k: subprocess.run(["git", *a], cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace", **k)
    refs = [x for x in git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").stdout.split("\n") if x.strip() and not x.endswith("/HEAD")]
    for ref in refs:
        names = [p for p in git("ls-tree", "-r", "--name-only", ref, "--", RUNS + "/").stdout.split("\n")
                 if re.fullmatch(re.escape(RUNS) + r"/run-[^/]+/(state\.json|tasks/[^/]+\.json)", p)]
        runs = sorted({p.split("/")[1] for p in names if p.endswith("/state.json")} - set(found))
        if not runs:
            continue
        batch = git("cat-file", "--batch", input="".join("%s:%s/%s/state.json\n" % (ref, RUNS, r) for r in runs)).stdout
        states = parse_batch(batch)
        for r, st in zip(runs, states):
            link = (st or {}).get("parent") or {}
            if link.get("run") != run_name:
                continue
            tasks = [p for p in names if p.startswith("%s/%s/tasks/" % (RUNS, r))]
            got = parse_batch(git("cat-file", "--batch", input="".join("%s:%s\n" % (ref, p) for p in tasks)).stdout) if tasks else []
            statuses = [t.get("status", "?") for t in got if t] + [ts.get("status", "?") for ts in ((st or {}).get("tasks") or {}).values()]
            found[r] = (link, st.get("status", "?"), tally(statuses), ref.replace("refs/heads/", "branch ").replace("refs/remotes/", "remote branch "))
    return [(r,) + v for r, v in sorted(found.items())]


def parse_batch(out):
    """`git cat-file --batch` output -> [parsed JSON or None], in order."""
    res, i = [], 0
    raw = out.encode("utf-8")
    while i < len(raw):
        nl = raw.index(b"\n", i)
        head = raw[i:nl].decode("utf-8").split()
        i = nl + 1
        if len(head) < 3 or head[1] == "missing":
            res.append(None)
            continue
        size = int(head[2])
        body = raw[i:i + size]
        i += size + 1
        try:
            res.append(json.loads(body.decode("utf-8")))
        except ValueError:
            res.append(None)
    return res


# ---------------------------------------------------------------- the run

def stop(msg, *lines):
    for line in lines:
        print("  " + line)
    print("decision: " + msg)
    return DECISION


def cmd_run(args):
    """Advance the run one step: every task whose needs are met, in order — hire its hands, decide it by its checks, place
    the eyes, run the people hired after it, stop at its gate — until the loop stops for someone (exit 2) or the run
    completes. The phases are functions below; each returns None to go on, or the exit code of the stop it printed.
    Under `remote: "shared"` the remote is fetched and taken first; under a `lease`, the pass advances only what this
    session holds (taking a ready unheld task when it holds fewer than `lease-max`), and renews a hold where it saw progress."""
    global _LEASE_CALL
    if getattr(args, "continuing", False):
        return run_pass(args)
    code = remote_before(args.target, "`chongdae run`")
    if code is not None:
        return code
    leases = lease_backend(args.target)
    _LEASE_CALL = {"leases": leases, "holder": lease_holder(args.target), "held": {}} if leases else None
    try:
        code = run_pass(args)
    finally:
        call, _LEASE_CALL = _LEASE_CALL, None
    if call:
        lost = lease_progress(args.target, call) if call["held"] else None
        lost = parent_progress(args.target, call) or lost
        if lost is not None and not code:
            code = lost
    return code


def run_pass(args):
    global _CALL_DEADLINE
    if not getattr(args, "continuing", False):
        import time
        _CALL_DEADLINE = time.time() + WAIT_BUDGET   # a fresh budget for this call, from its start — an automatic resend continues the same call, and its budget
    target = args.target
    d = run_dir(target)
    if not d:
        raise SystemExit("no run — `chongdae init --goal ...`")
    plan, state = load_plan(d), load_state(d)
    if state["status"] != "running":
        print("run %s is %s" % (os.path.basename(d), state["status"]))
        return 0
    ctx = {"args": args, "target": target, "d": d, "plan": plan, "state": state, "providers": providers(target, plan),
           "me": me(target), "claimed_now": set(), "waited": False,   # claimed_now: files the tasks completed in this call recorded as theirs
           "named": set(getattr(args, "tasks", None) or []), "held": [], "theirs": [], "blocked": [], "subagents": []}
    unknown = sorted(ctx["named"] - set(state["tasks"]))
    if unknown:
        raise SystemExit("run: no task %s in %s" % (", ".join(unknown), os.path.basename(d)))
    for task in all_tasks(plan, state):
        ts = state["tasks"][task["id"]]
        if ts["status"] in ("done", "skipped", "dropped"):
            if operation_pending(d, task["id"]):
                ctx["blocked"].append("%s has an interrupted operation — `chongdae did %s` must recover its result before this run can finish" % (task["id"], task["id"]))
            continue
        # A task list selects work; it is not permission to finish every other task whose tree happens to have moved.
        # Keep ownership ahead of checks/providers too: another session's partial work is not ours to judge complete.
        try:
            owned_elsewhere = local_owner_blocks(target, d, task["id"], ts, _LEASE_CALL["leases"] if _LEASE_CALL else None)
        except LeaseError as err:
            return stop("the lease store cannot be reached (%s) — ownership cannot be established; nothing advanced" % err)
        if owned_elsewhere:
            ctx["theirs"].append(task["id"])
            if task["id"] in ctx["named"]:
                ctx["blocked"].append("%s belongs to another session — `chongdae take %s --why WHY` records an explicit handover" % (task["id"], task["id"]))
            continue
        if ctx["named"] and task["id"] not in ctx["named"]:
            continue
        pending_operation = operation_pending(d, task["id"])
        if pending_operation:
            ctx["blocked"].append("%s has interrupted operation %s — `chongdae did %s` recovers observed results without repeating commands; reconcile any unknown outcome before advancing" %
                                  (task["id"], pending_operation["id"], task["id"]))
            continue
        needs = [n for n in task.get("needs", []) if state["tasks"][n]["status"] != "done"]
        if needs:
            if task["id"] in ctx["named"]:
                ctx["blocked"].append("%s waits for %s — finish its dependencies first; this call does not select them automatically" % (task["id"], ", ".join(needs)))
            continue
        if ts.get("claimed_by") and claim_owner(ts["claimed_by"]) != ctx["me"]:
            print("  %s is claimed by %s — not this machine's to advance" % (task["id"], signer_text(ts["claimed_by"])))
            if task["id"] in ctx["named"]:
                ctx["blocked"].append("%s is claimed by another owner" % task["id"])
            continue
        who = "session" if ts.get("taken") else hire(ctx["providers"], task)[1]
        if who == "subagent" and ts["status"] == "todo" and task["id"] not in ctx["named"]:
            # The host's Agent call runs independently. Files and even green checks may be only its partial work;
            # only its parent can say its answer has arrived and select it for verification/completion.
            ctx["subagents"].append(task["id"])
            continue
        if _LEASE_CALL and not state.get("parent"):   # a child run's tasks are this session's by the hold on its parent's task
            code = lease_step(ctx, task, ts)
            if code == "skip":
                if task["id"] in ctx["named"]:
                    ctx["blocked"].append("%s could not acquire its lease — no selected work was taken from another holder" % task["id"])
                continue
            if code is not None:
                return code
        if ts.get("rebaseline"):
            # this build's tests were disputed: it waits for the task amending them, then takes the amended files as its
            # contract — the next judgment keeps the fix instead of restoring what the dispute was about
            amenders = amending_tasks(plan, state, task, ts["rebaseline"])
            if amenders:
                ctx["waited"] = True
                print("  %s waits for %s to amend %s" % (task["id"], ", ".join(amenders), ", ".join(ts["rebaseline"])))
                continue
            rebaseline(target, d, task, ts, plan, state)
            save_state(d, state)
        # a task the session took over (`take`) is the session's from then on, whoever the lock hired for its role
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
            gone = deleted_by_contract(target, plan, state, task)
            absent = [t for t in task.get("tests") or [] if not os.path.isfile(os.path.join(target, t)) and t not in gone]
            new = {t: w for t, w in gone.items() if t not in (ts.get("deleted-tests") or {})}
            if new:
                ts["deleted-tests"] = gone   # said once: `add` said it already when the deletion was in the tree then
                print("  %s: %s" % (task["id"], deleted_note(new)))
            if absent and task.get("checks"):
                return stop("%s: its protected tests do not exist (%s) — the guard would watch nothing; the task that writes them runs first, "
                            "or fix the paths (`chongdae drop` and `add` again)" % (task["id"], ", ".join(absent)))
            ts["start"] = dirty(target, keep=record_scope(target, task))   # what the tree already differed in: `touched` is measured from here, not from HEAD
            ts["start-head"] = head_sha(target)   # and the commit under it: a commit made during the task is still the task's work
            ts["start-heads"] = nested_heads(target)   # and each nested repository's
            keep_contract_tests(target, d, task)
            save_state(d, state)
        if ts["status"] == "todo":
            # People hired before the work: each answers with findings about the contract; a finding is a plan question, so the
            # task waits until a human accepts them (having written the answers into the plan) — the hands do not move on an open question.
            code = run_stage(target, d, task, ts, state, plan, ctx["providers"], "before", {"tests": task.get("tests", [])})
            if code is not None:
                return code
        if ts["status"] == "todo" and who not in SESSION_HANDS:
            # A command provider: a fresh process gets a request file and must leave a response file. chongdae reads only the response.
            code = run_hands(ctx, task, ts, who)
            if code is not None:
                return code
        if ts["status"] == "todo":
            code = decide_task(ctx, task, ts, who, path)
            if code == HELD:
                continue
            if code is not None:
                return code
        if ts["status"] == "produced":
            code = produced_freshness(ctx, task, ts)
            if code is not None:
                return code
        if ts["status"] == "produced" and gate_of(task).get("human"):
            return stop("human: review %s (%s) — then `chongdae confirm %s --by <name>` or `--delegated \"<why the human handed this off>\"`"
                        % (task.get("produces", "task %s (checks passed: %s)" % (task["id"], "; ".join(" ".join(c) for c in task.get("checks", [])))), path or task.get("closes", ""), task["id"]))
        if _LEASE_CALL and ts.get("lease-held") and not state.get("parent"):
            refused = result_gen_refusal(target, d, task["id"], ts) if ts.get("gen") and ts["gen"] != ts["lease-held"]["gen"] else None
            if refused:
                return stop("%s: %s" % (task["id"], refused))
            lease_into_record(ts, _LEASE_CALL["held"].get(task["id"]) or {"gen": ts["lease-held"]["gen"], "holder": ts["lease-held"].get("holder")})
        ts["status"] = "done"
        ts["done"] = stamp()   # when it became done: `show` tells a run's durations from it
        if _LEASE_CALL:
            release_task(_LEASE_CALL["leases"], os.path.basename(d), task["id"], ts)   # done: the key goes back, and the next ready task can be taken
        save_state(d, state)
        # done is a judgment — the checks', the verifier's, the agent's word — and is notarized when it is made: guin-site
        # run-20261015-054352-a0ec's contract, quibble, decide, tests and decide-2 became done in `run` calls that committed
        # nothing, and landed in a commit titled "accept decisions on cache-build (delegated)", 12 files
        commit_record(target, os.path.basename(d), "done %s%s" % (task["id"], " — " + cut(task["brief"], 100) if task.get("brief") else ""))
        print("  done %s" % task["id"])
        offer = check_offer(target, task, ts.get("touched") or []) if hire(ctx["providers"], task)[1] in SESSION_HANDS else None
        if offer:
            print("    note: %s was done on your word: %s — next time, before `run`" % (task["id"], offer))
        mine = {f: [task["id"]] for f, tids in uncommitted_work(target, plan, state).items() if task["id"] in tids}
        if mine and not state.get("worktree"):
            # its work is the session's to commit, in the form the log tells from chongdae's own (`close` stops on it otherwise)
            for line in work_commit_lines(os.path.basename(d), plan, state, mine, target):
                print("    " + line)
    if ctx["waited"] and not any(state["tasks"][t["id"]].get("rebaseline") and state["tasks"][t["id"]]["status"] == "todo"
                                 and amending_tasks(plan, state, t, state["tasks"][t["id"]]["rebaseline"]) for t in all_tasks(plan, state)):
        # a build passed over while its tests were amended by a task later in the order: the amendment is done now
        setattr(args, "continuing", True)
        return cmd_run(args)
    if ctx["theirs"]:
        print("  open, added by another session of this run — theirs to finish, not this call's: %s" % ", ".join(ctx["theirs"]))
    if ctx["blocked"]:
        return stop("selected tasks stay open", *ctx["blocked"])
    if ctx["subagents"]:
        return stop("session agent: wait for the sub-agent's answer, then select its task with `chongdae run TASK`; "
                    "partial edits do not finish a sub-agent's task", "open sub-agent tasks: %s" % ", ".join(ctx["subagents"]))
    if ctx["held"]:
        ids = list(dict.fromkeys(h.split(" ", 1)[0].rstrip(":") for h in ctx["held"]))   # a task's offer line is its own, not another task
        one = ids[0] if len(ids) == 1 else "TASK"
        return stop("session agent: %s %s open — no check decides %s, and this `run` did not name %s. Do the work, then `chongdae run`; "
                    "an operation outside the repository first goes through `chongdae did %s --why WHY -- COMMAND`; work that leaves nothing "
                    "in the tree is finished by naming it, `chongdae run %s` (your word that it is done); `chongdae drop %s --why` if it will not be done"
                    % (", ".join(ids), "stays" if len(ids) == 1 else "stay", "it" if len(ids) == 1 else "them", "it" if len(ids) == 1 else "them", one, one, one),
                    *ctx["held"])
    return end_of_pass(ctx)


def run_hands(ctx, task, ts, who):
    """A command provider: a fresh process gets a request file and must leave a response file. chongdae reads only the
    response — and routes what it says: a dispute over the contract's tests back to their writer, a refusal of the report
    over a check's spelling against chongdae's own run of the checks, a `blocked` or unfinished answer to a person,
    decisions beyond the contract to a person's `accept`."""
    args, target, d, state, plan = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"]
    if not ts.get("response"):
        if task.get("role") in CONTRACT_READERS:
            code = empty_contract_stop(target, plan, task, task["role"])
            if code is not None:
                return code
        code, response, before = spawn(target, d, task, who, plan, ts.get("attempts", []),
                                       extra={"amending": ts["amending"]} if ts.get("amending") else None)
        if code == DISPATCH:
            return stop(dispatch_text(task["id"], response))
        if code == WAITING:
            return waiting_stop(task["id"], response)
        ts["response"] = response
        ts["answered"] = stamp()   # when the hands' answer came back: the attempt's end, for `show`
        # a resent build finds its first attempt's work in the tree and may change nothing more: the files the provider changed
        # are every attempt's, not this one's alone. guin-site run-20261015-054352-a0ec: after the resend, cache-build's verify
        # request said `touched: []`, with the builder's index.ts and read.ts under `touched_since` — "not the builder's". An
        # earlier attempt's file counts while it still differs from the task's start (a tree reset before a retry undoes it)
        now = touched_files(target, before)
        prior = set(ts.get("touched_by_provider") or [])
        if prior and isinstance(ts.get("start"), dict):
            now = sorted(set(now or []) | (prior & set(touched_files(target, ts["start"], ts.get("start-head"), heads=ts.get("start-heads")) or [])))
        ts["touched_by_provider"] = now
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
        # it is not a decision the contract lacks: the lock's alternate that can, or (decided at setup) the session
        return hiring_stop(ctx, task, ts, response, lacked if lacked is not None else list(task.get("requires") or []),
                           unattempted + [n for n in response.get("non-claims", []) if str(n).startswith("sandbox lacked:")])
    if response.get("status") in ("blocked", "failed") and response.get("disputed-tests"):
        # `failed` too: a validator that refuses the rest of the report (a check spelled otherwise than it ran) turns a
        # blocked build into a failed one, and the dispute is still the builder's word about the tests — resending the build
        # for its evidence dropped it (guin-site write-bsky-build, three answers each disputing the same three tests). The
        # build goes out again after the amendment anyway; its evidence is judged then.
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
        code, failed = own_checks(ctx, task, ts) if task.get("checks") else (None, ["no checks"])
        if code is not None:
            return code
        if not failed:
            ts["checks-ran-overruled"] = {"refused": [str(n)[:300] for n in refused], **stamp()}
            ts.setdefault("non-claims", []).append("%s: the validator refused the report for naming a check it did not see run (%s); chongdae ran the task's checks itself and they passed, so the report stands as the worker's word" % (task["id"], str(refused[0])[:160]))
            save_state(d, state)
            print("  %s: the report's check was not recognized by the validator; the checks pass here — going on, recorded" % task["id"])
        elif (setattr(args, "continuing", True) or True) and auto_resend(target, d, state, task["id"], "the report named a check the session did not run: " + refused[0][:160]):
            return cmd_run(args)
    if response.get("status") != "done" and not ts.get("checks-ran-overruled"):
        return stop("%s: provider %r did not finish (%s) — see %s; fix what stopped it (or nothing, if it ran out of budget), %s%s"
                    % (task["id"], who, response.get("status"), work_path(d, task["id"] + ".response.json"), again,
                       "; it disputes the contract's tests: `chongdae dispute %s --tests FILE... --why WHY` routes them to the task that wrote them" % task["id"]
                       if response.get("disputed-tests") else ""))
    if response.get("decisions") and not ts.get("accepted"):
        # The provider settled something the contract did not. That is a plan change: a human writes it into the plan and accepts, or rejects the work.
        return stop("%s: the provider made %d decision(s) the contract did not — write each into the plan, then `chongdae accept %s --by NAME | "
                    "--delegated WHY` and re-run; or reject the work: reset the tree, say why in the plan or brief, then `chongdae retry %s --by NAME | --delegated WHY`"
                    % (task["id"], len(response["decisions"]), task["id"], task["id"]),
                    *("%s: chose %r (alternatives: %s)" % (x["what"], x["chosen"], ", ".join(x["alternatives"]) or "-") for x in response["decisions"]))
    if not ts.get("reported"):
        ts["non-claims"] = merge_provider_non_claims(ts.get("non-claims", []), ["(provider) %s" % n for n in response.get("non-claims", [])])
        ts["reported"] = True
        save_state(d, state)
    return None


QUOTED = re.compile(r'"([^"]{6,})"|“([^”]{6,})”')


def leading_quote(n):
    """The contract sentence a provider's non-claim leads with (`(provider) "확인하지 않는 것: …" — no test writes …`), or None.
    Only the lead, and only a sentence: a file name or flag quoted (`"tests/run.py" was run without --all`) is not what
    two lines are about."""
    m = QUOTED.match(re.sub(r"^\(provider\) ", "", str(n)).lstrip())
    q = "".join(m.groups(default="")).strip() if m else ""
    return q if re.search(r"\s", q) else None


def restates(a, b):
    """b says again what a said: the same text, or the contract sentence a leads with, quoted again in b (a provider's
    non-claim leads with the sentence it could not decide — `"확인하지 않는 것: 실제 guin-pds에 쓰기" — no test writes …`)."""
    qa = leading_quote(a)
    return str(a) == str(b) or (qa is not None and qa in {"".join(m).strip() for m in QUOTED.findall(str(b))})


def merge_provider_non_claims(old, new):
    """The task's non-claims after a provider answered again without a resend — a writer reopened to amend its tests keeps
    its earlier attempt's list (still about the tests it wrote), and its new answer restated half of it in other words: the
    reviewer read both, and guin-site's review held six such pairs. A provider non-claim the new answer restates gives way —
    one for one: a new line replaces at most one old line, so a list of distinct reasons is not wiped by one restatement."""
    gone, used = set(), set()
    for i, n in enumerate(old):
        if not str(n).startswith("(provider) "):
            continue
        j = next((j for j, m in enumerate(new) if j not in used and restates(n, m)), None)
        if j is not None:
            gone.add(i)
            used.add(j)
    kept = [n for i, n in enumerate(old) if i not in gone]
    return kept + [m for m in new if m not in kept]


def one_command(c, flag):
    """A command line given as one string, as argv — refused when it is a shell line: run without a shell, `echo ok && false`
    would run `echo` with three words and pass."""
    lex = shlex.shlex(c, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        toks = list(lex)
    except ValueError as e:
        raise SystemExit("%s: `%s` does not parse (%s)" % (flag, c, e))
    shell_words(toks, flag, c)
    return shlex.split(c)


def shell_words(toks, flag, c):
    shell = [t for t in toks if t and set(t) <= set("();<>|&")] + (toks[:1] if toks and re.match(r"^\w+=", toks[0]) else [])
    if shell:
        raise SystemExit("%s runs one command, not a shell line: `%s` has %s — give each command its own %s; "
                         "a command that needs a shell is a script in the project" % (flag, c, ", ".join("`%s`" % t for t in shell), flag))


def run_argv(target, argv):
    """One command, run in the project without a shell and with no input: (exit, output, ran). A missing command is exit 127 and
    a timeout (CHONGDAE_CHECK_TIMEOUT, default 30 min) exit 124 — `ran` False for both: nothing was observed to answer."""
    import subprocess
    timeout = float(os.environ.get("CHONGDAE_CHECK_TIMEOUT") or 1800)
    argv = resolve_argv(target, list(argv))
    if argv and argv[0] in ("python", "python3") and not shutil.which(argv[0]):
        argv = [next((x for x in ("python3", "python") if shutil.which(x)), None) or sys.executable] + argv[1:]
    try:
        done = subprocess.run(argv, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout)
        return done.returncode, (done.stdout + done.stderr), True
    except subprocess.TimeoutExpired:
        return 124, "timed out after %ds (CHONGDAE_CHECK_TIMEOUT)" % timeout, False
    except OSError as e:
        return 127, str(e), False


def run_checked(target, commands, red=()):
    """`--checked`: commands chongdae runs itself, in the project, now — evidence it observed, where a worker's `verified` is the
    worker's word. guin-site write-bsky-build (2026-10-10): the session took the task, ran `tests/run.py --all` itself (exit 0),
    and had nowhere to put it; the verifier rejected the builder's old claim three times over. `--checked-red`: a tests task's
    expected red run — a non-zero exit is recorded as red as expected, a zero exit as passed before the build (both recorded;
    `--checked` recorded only a pass, so the red run a tests task exists for had nowhere to go). Returns the records; the tree
    they ran on is kept so the verifier is told what changed after."""
    runs = [(c, one_command(c, "--checked"), None) for c in commands or []] + [(c, one_command(c, "--checked-red"), "fail") for c in red or []]
    out, refused = [], []
    for c, argv, expect in runs:
        code, said, ran = run_argv(target, argv)
        rec = {"command": c, "exit": code, "tail": kept_tail(said), **stamp()}
        if expect:
            rec["expect"] = expect
            rec["outcome"] = "red as expected" if code else "passed before the build"
        out.append(rec)
        if (code and not expect) or not ran:
            refused.append(rec)
    if refused:
        raise SystemExit("--checked: %s — nothing recorded; %s"
                         % ("; ".join("`%s` -> exit %d (%s)" % (r["command"], r["exit"], " / ".join(r["tail"][-2:])) for r in refused),
                            "a check that fails is not evidence, and a command that did not run is not a red run"))
    return {"ran": out, "checked-tree": dirty(target) or {}}


def checked_text(checked):
    """What `--checked`/`--checked-red` recorded, for the line `take`/`retry` print."""
    return ", ".join("`%s` %s" % (r["command"], "exit 0" if not r.get("expect") else "exit %d — %s" % (r["exit"], r["outcome"])) for r in checked["ran"])


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


def capability_decisions(target):
    """The project's one-time decision about sandbox capabilities: hunsu.json `capabilities` (`{"loopback": "session" |
    "alternates", "network": ...}`, written by hunsu at setup), with this machine's overlay (hunsu.local.json) on top — read
    where it is written, as chongdae reads its settings."""
    out = dict(load(os.path.join(target, "hunsu.json")).get("capabilities") or {})
    out.update(load(os.path.join(target, "hunsu.local.json")).get("capabilities") or {})
    return out


def argv_flag(argv, flag):
    """The value after `flag` in a provider's argv (a list, or {"native": [...]}), or None."""
    argv = argv.get("native") if isinstance(argv, dict) else argv
    if isinstance(argv, list) and flag in argv[:-1]:
        return str(argv[argv.index(flag) + 1])
    return None


def hiring_stop(ctx, task, ts, response, caps, lines):
    """A member could not do the task here because of its sandbox. Resending to the same member changes nothing. When the
    lock has the `<role>@<cap>` alternate that can, the task says what it requires and goes there — the lock is the
    project's hiring, already decided. When it has none, no person is asked mid-run: what a project does about a capability
    its members' hosts lack is decided once, at setup (hunsu.json `capabilities`), and a run must go on without stopping
    for a person — the session takes the task, recorded as taken for lack with the reason, and `run` stops only for the
    session to do the work. guin-site, 2026-10-02: twice the stop listed the ways on and waited, and the session took the
    task itself each time; `report` now counts those tasks so a review sees them."""
    args, d, state, plan = ctx["args"], ctx["d"], ctx["state"], ctx["plan"]
    tid, role, prov = task["id"], task["role"], ctx["providers"]
    have = list(task.get("requires") or [])
    known = [c for c in caps if c in REQUIRES]
    want = have + [c for c in known if c not in have]
    used = (ts.get("performed_by") or {}).get("as") or role
    alt = hire(prov, {"role": role, "requires": want})[0] if want else role
    lacks = ", ".join(caps) or "a capability it did not name"
    if alt != role and alt != used:
        # the lock already holds the hire that can: no person is needed to use it
        why = "its sandbox lacked %s; the lock's %s can" % (lacks, alt)
        task["requires"] = want
        if "def" in ts:
            ts["def"]["requires"] = want
        else:
            entry = next((t for t in plan.get("tasks", []) if t.get("id") == tid), None)
            if entry is not None:
                entry["requires"] = want
                save_state(d, state, plan=plan)
        n = resend(ctx["target"], d, state, tid, {"by": "chongdae", "auto": why, "requires": want}, "hire %s for %s: %s" % (alt, tid, why))
        print("  %s: %s — it requires %s now and goes to %s (attempt %d kept)" % (tid, why, ", ".join(want), alt, n))
        setattr(args, "continuing", True)
        return cmd_run(args)
    decided = capability_decisions(ctx["target"])
    named = caps or ["a capability it did not name"]
    said = {c: (decided.get(c) if decided.get(c) in ("session", "alternates") else "undecided") for c in named}
    said = {c: ("alternates, but the lock has none" if v == "alternates" else v) for c, v in said.items()}
    member = argv_flag(prov.get(used), "--member") or used
    host = argv_flag(prov.get(used), "--host") or "its host"
    why = "%s on %s lacked %s; no %s@%s in the lock (hunsu.json capabilities: %s)" % (
        member, host, lacks, role, "+".join(want) or "CAP", ", ".join("%s: %s" % (c, v) for c, v in said.items()))
    take_over(ctx["target"], d, state, task, ts, why, "chongdae",
              {"auto": True, "for-lack": {"role": role, "lacked": named, "capabilities": said, "member": member, "host": host}})
    if used != role:
        lines = list(lines) + ["the lock's %s was hired for it and its sandbox lacked %s too" % (used, lacks)]
    return stop("session agent: %s: %s (%s) — taken by the session: %s. Do its work, then `chongdae run` (its checks, the verifier and the gate decide it as for any task)"
                % (tid, response.get("summary") or "the member cannot do this task here", used, why), *(list(lines) + ([task["brief"]] if task.get("brief") else [])))


def own_checks(ctx, task, ts):
    """(code, failed): the task's checks as chongdae runs them, inside the call's budget (budget_checks). Passed on this very
    tree already — an earlier call of this attempt ran them, and the call handed back before the verifier answered — they
    are not run again: the next call resumes from the stage it stopped at. What passed is kept (`checks-passed`) and goes to
    the verifier as evidence chongdae saw. code: WAITING's stop when they are still running past the budget, else None."""
    target, d, state = ctx["target"], ctx["d"], ctx["state"]
    commands = [shlex.join(str(a) for a in c) for c in task.get("checks") or []]
    passed = ts.get("checks-passed")
    if (isinstance(passed, dict) and [r.get("command") for r in passed.get("ran") or []] == commands
            and "checks-source" in ts and ts["checks-source"] == source_tree(target, record_scope(target, task))):
        return None, []
    witness = {}
    code, failed, ran = budget_checks(target, d, task, result_source=witness)
    if code is not None:
        return waiting_stop("%s (its checks)" % task["id"], failed), None
    if failed:
        ts.pop("checks-passed", None)
        ts.pop("checks-tree", None)
        ts.pop("checks-source", None)
    else:
        ts["checks-passed"] = {"ran": ran, **stamp()}
        ts["checks-tree"] = dirty(target) or {}
        ts["checks-source"] = witness.get("source")
    save_state(d, state)
    return None, failed


def decide_task(ctx, task, ts, who, path):
    """What makes a task done: its checks passing (a code task), its artifact passing its shape check (a bootstrap task), or
    — with no check — the agent's word, which must at least be the task's own. Then the eyes, then the people hired after,
    then the record of what it touched and who did it; the task is `produced` and waits at its gate, if it has one."""
    args, target, d, state, plan, prov = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"], ctx["providers"]
    scoped = {"notes": [], "held": {"settled": set(), "ties": {}}}

    def own_measure():
        # what this task changed — with what open tasks' scopes say is whose (`add --scope`)
        files, scoped["notes"], scoped["held"] = scoped_measure(target, plan, state, task["id"], ts, prov)
        return files

    if task.get("checks"):
        # Code tasks: done means the checks pass. Not started and failing look the same — both are "not yet".
        code, failed = own_checks(ctx, task, ts)
        if code is not None:
            return code
        if failed:
            return stop("session agent: %s — make these checks pass, then `chongdae run`" % task["id"], task.get("brief", ""), *failed)
        touched = own_measure() or []
        gone = ts.get("deleted-tests") or {}
        recreated = [t for t in task.get("tests", []) if t in gone and os.path.lexists(os.path.join(target, t))]
        broken = [t for t in task.get("tests", []) if t in touched and t not in gone]
        if broken or recreated:
            # The contract owns its checks. A build that edits them decided its own verdict — that is a reject, whoever built.
            # A test the contract deleted is the contract's too: brought back, it is a test the build wrote for itself
            ts["rejected"] = {"by": "contract", "why": "; ".join(x for x in ("changed protected tests: %s" % ", ".join(broken) if broken else "",
                                                                             "recreated tests the contract deleted: %s" % ", ".join(recreated) if recreated else "") if x)}
            back = restore_contract_tests(target, d, task, broken)
            if back:
                ts["rejected"]["restored"] = back
            removed = []
            for t in recreated:
                try:
                    os.remove(os.path.join(target, t))
                    removed.append(t)
                except OSError:
                    pass
            if removed:
                ts["rejected"]["removed"] = removed
            save_state(d, state)
            left = [t for t in broken if t not in back] + [t for t in recreated if t not in removed]
            said = []
            if broken:
                said.append("the build changed the contract's tests (%s)" % ", ".join(broken))
            if recreated:
                said.append("the build recreated tests the contract deleted (%s — %s deleted them)" % (", ".join(recreated), ", ".join(sorted({gone[t] for t in recreated}))))
            return stop("%s: %s — %s (the contract decides, not the builder), "
                        "then `chongdae retry %s --by NAME | --delegated WHY`" % (
                            task["id"], "; ".join(said),
                            ("restored as they were when the task started" + (", the recreated ones removed again" if removed else "")) if not left
                            else "put back %s as the contract has them" % ", ".join(left), task["id"]))
        # Independent eyes before the gate: not the hands, and their verdict goes here, not back to the builder.
        code = place_eyes(ctx, task, ts, who, touched)
        if code is not None:
            return code
    elif not task.get("path"):
        if who in SESSION_HANDS and ts.get("amending"):
            # reopened by a dispute over the tests it wrote: done is the amendment, measured against the tests as the
            # disputing build protected them — not this task's word that it looked
            files = sorted({str(x.get("test", "")).split("::")[0].split(" ")[0] for x in ts["amending"] if isinstance(x, dict)})
            if files and not set(files) & set(own_measure() or []):
                return stop("session agent: %s — its tests were disputed; amend %s as the dispute says, then `chongdae run` (the build that protects "
                            "them takes the amended files as its contract once this task is done)" % (task["id"], ", ".join(files)),
                            *["%s: %s" % (x.get("test"), x.get("why")) for x in ts["amending"] if isinstance(x, dict)])
        # a session task with no check: done is the agent's word (a non-claim since `add`). It still has to be the
        # task's own word: a task added ahead of its work would otherwise be done here with the files the task before
        # it changed — a false claim a done task cannot take back. And a task with nothing of its own — no change in the
        # tree, no `did` — is not done by a `run` that did not name it: guin-site run-20261015-054352-a0ec, the `run` for
        # cache-comment also made cache-ops done (06:36:15, touched [], no did) — its deploy, push and Done line came at
        # 06:37–06:39. It stays open, the pass goes on, and the call ends saying how to finish it
        if who in SESSION_HANDS and not ts.get("did") and not gate_of(task).get("human") and not own_measure():   # a gated task's done is a person's confirm
            if task["id"] not in ctx["named"]:
                # when what changed is records, say that, not "nothing": they count only inside the task's own scope
                theirs = {f for t2 in all_tasks(plan, state) if t2["id"] != task["id"] for f in list(state["tasks"].get(t2["id"], {}).get("touched") or []) + list(record_scope(target, t2))}
                recs = [f for f in record_changes(target) if not in_entries(f, theirs) and not f.startswith(".claude/")]
                why = (" — what changed is records (%s), never a task's work unless its own `--scope` names them: "
                       "`chongdae adopt %s %s --why WHY` gives them to it —" % (", ".join(recs), task["id"], " ".join(recs))) if recs else ""
                ctx["held"].append("%s has changed nothing of its own%s%s and has no `did` record: %s" % (
                    task["id"], " — %s were the task before it" % ", ".join(sorted(ctx["claimed_now"])) if ctx["claimed_now"] else "", why, cut(task.get("brief", ""), 200)))
                offer = check_offer(target, task)
                if offer:
                    ctx["held"].append("%s: %s" % (task["id"], offer))
                return HELD
            said = "%s: done on the session's word by name (`run %s`), with nothing of its own in the tree and no `did`" % (task["id"], task["id"])
            if said not in ts.setdefault("non-claims", []):
                ts["non-claims"].append(said)
    else:
        if not (path and os.path.exists(path)):
            return stop("session agent: produce %s at %s, then `chongdae run`" % (task["produces"], path), task["brief"])
        problems = CHECKS[task["produces"]](path, state)
        if problems:
            return stop("%s does not pass its shape check — fix it, then `chongdae run`" % task["produces"], *problems)
    # People hired after the work: they see the result (touched files, the builder's report) and answer with findings for
    # the record — not a verdict; the gate stands as declared, and the reviewer's report carries what they found.
    built = {k: (ts.get("response") or {}).get(k) for k in ("summary", "verified", "non-claims")} if ts.get("response") else None
    if "after-source" not in ts:
        ts["after-source"] = source_tree(target, record_scope(target, task))
        save_state(d, state)
    code = run_stage(target, d, task, ts, state, plan, prov, "after", {"touched": own_measure() or [], "tests": task.get("tests", []), "built": built})
    if code is not None:
        return code
    current = source_tree(target, record_scope(target, task))
    if any(ts[key] != current for key in ("checks-source", "review-source", "after-source") if key in ts):
        return invalidate_review(ctx, task, ts, current, reason="source changed before the after stage finished")
    ts["status"] = "produced"
    ts["checks"] = task.get("checks", [])
    ts["touched"] = own_measure()   # what this task changed: the reviewer joins runs to files with it
    for line in scoped["notes"]:
        print("  note: " + line)
    earlier = [f for a in ts.get("attempts", []) if a.get("reopened") for f in a.get("touched") or []]
    if earlier and ts["touched"] is not None:
        ts["touched"] = sorted(set(ts["touched"]) | set(earlier))   # reopened to amend: what it wrote before is still its own
    ctx["claimed_now"].update(ts["touched"] or [])
    # a file this task measured that another open session task names, and that changed after that task was added (or was
    # already changed when it was): whose work it is the tree cannot say. It is said, not guessed — and not pinned away from
    # the other task, which keeps measuring it until a judgment (`adopt`) settles it
    shared = {f: ids for f, ids in contested(target, plan, state, task["id"], ts["touched"] or []).items() if f not in scoped["held"]["settled"]}
    if shared:
        ts["shared"] = {f: [o for o, _ in ids] for f, ids in shared.items()}
        for line in contested_lines(task["id"], shared, plan, state):
            print("  " + line)
    else:
        ts.pop("shared", None)
    for f, owners in scoped["held"]["ties"].items():   # in another open task's scope as narrowly as in this one's: said, and left to both
        sh = ts.setdefault("shared", {})
        sh[f] = sorted(set(sh.get(f, [])) | set(owners))
    # the rest are this task's now: a session task still open measures its own changes from here, not from its `add`
    now = dirty(target) or {}
    for t2 in all_tasks(plan, state):
        other = state["tasks"][t2["id"]]
        if other is not ts and other.get("status") == "todo" and isinstance(other.get("start"), dict) and session_tree(prov, t2, other):
            for f in ts["touched"] or []:
                if t2["id"] in (ts.get("shared") or {}).get(f, []):
                    continue
                h = now.get(f) or file_hash(target, f)   # pinned: committed since, it may be clean at a newer HEAD
                if other["start"].get(f) != h:
                    other["start"][f] = h
                    other.setdefault("pinned", {})[f] = task["id"]   # whose finish put it there: `adopt` and `retry` can say so
    if "performed_by" not in ts:
        ts["performed_by"] = against_run(performer(who, target=target), state)   # the session did the work: record which host/model/session, like a commit author
        if who == "subagent":
            ts.setdefault("non-claims", []).append("%s: done by the session's sub-agent — chongdae saw the session and the tree, not the sub-agent; its model is the session's unless the session dispatched it with another" % task["id"])
    if who in SESSION_HANDS and not ts.get("response"):
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


def produced_freshness(ctx, task, ts):
    """A confirmation judges the produced, checked artifact, not later edits."""
    if not task.get("checks") and not ts.get("review"):
        return None
    current = source_tree(ctx["target"], record_scope(ctx["target"], task))
    missing = (task.get("checks") and "checks-source" not in ts) or (ts.get("review") and "review-source" not in ts)
    if not missing and all(ts[key] == current for key in ("checks-source", "review-source", "after-source") if key in ts):
        return None
    ts["status"] = "todo"
    ts.pop("confirmed", None)
    ts.pop("done", None)
    return invalidate_review(ctx, task, ts, current, reason="source changed after this task was produced",
                             result=DECISION)


def invalidate_review(ctx, task, ts, current, verdict=None, reason="source changed while the verifier was reviewing it", result=WAITING):
    """A verdict on older input is not a verdict on the current source. Yield once.

    Called only after the pending reviewer ended (or for an already kept review),
    so its old response can safely be retired before the next call asks fresh eyes.
    """
    before = ts.get("review-source", ts.get("checks-source", ts.get("after-source")))
    changed = sorted(p for p in set(before or {}) | set(current or {}) if (before or {}).get(p) != (current or {}).get(p))
    invalidated = {"why": reason, "changed": changed, "verdict": (verdict or ts.get("review") or {}).get("verdict"), **stamp()}
    ts.setdefault("invalidated-reviews", []).append(invalidated)
    tag = stage_tag(task["id"], "verify", ts.get("attempts", []))
    for suffix in (".response.json", ".pending.json"):
        path = work_path(ctx["d"], tag + suffix)
        if os.path.exists(path):
            os.remove(path)
    waiting_after = False
    for role in stage_roles(ctx["plan"], task, "after"):
        tag = stage_tag(task["id"], role, ts.get("attempts", []))
        pending_path = work_path(ctx["d"], tag + ".pending.json")
        response_path = work_path(ctx["d"], tag + ".response.json")
        pending = load(pending_path)
        if pending and (pending_alive(pending_path, pending) or (pending.get("native") and not os.path.exists(response_path))):
            # A previous call yielded while this observer worked. Drain its
            # answer normally; after-source still witnesses its older input.
            waiting_after = True
            continue
        rec = (ts.get("stages") or {}).get(role)
        if rec and rec.get("when") == "after":
            invalidated.setdefault("after", {})[role] = ts["stages"].pop(role)
        for path in (pending_path, response_path):
            if os.path.exists(path):
                os.remove(path)
    if not waiting_after:
        ts.pop("after-source", None)
    for key in ("review", "review-source", "reviewed_tree", "verdict-given", "verified_by", "overruled", "checks-passed", "checks-tree", "checks-source"):
        ts.pop(key, None)
    save_state(ctx["d"], ctx["state"])
    print("%s %s: source changed while its checks or reviewers were deciding it (%s); the old result does not complete this task. "
          "Wait for the writers, then `chongdae run %s` reruns the checks and asks fresh eyes%s." %
          ("decision: session agent:" if result == DECISION else "still working:", task["id"],
           ", ".join(changed[:8]) or "unwitnessed input", task["id"],
           "; confirm the newly produced result afterward" if result == DECISION else ""))
    return result


def place_eyes(ctx, task, ts, who, touched):
    """Independent eyes before the gate: not the hands, and their verdict goes here, not back to the builder. A reject goes
    back to the hands on its own (twice) — unless the hands are the session reading the stop."""
    args, target, d, state, plan, prov = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"], ctx["providers"]
    if not prov.get("verifier"):
        return None
    current = source_tree(target, record_scope(target, task))
    if ts.get("review") and ("review-source" not in ts or ts["review-source"] != current):
        return invalidate_review(ctx, task, ts, current)
    if not ts.get("review") and "review-source" not in ts and "checks-source" in ts and ts["checks-source"] != current:
        for key in ("checks-passed", "checks-tree", "checks-source"):
            ts.pop(key, None)
        save_state(d, state)
        print("still working: %s: source changed after its checks passed; `chongdae run %s` reruns them before asking the verifier." % (task["id"], task["id"]))
        return WAITING
    if not ts.get("review"):
        built = {k: (ts.get("response") or {}).get(k) for k in ("summary", "verified", "non-claims")} if ts.get("response") else None
        by_provider = ts.get("touched_by_provider")
        extra = {"touched": by_provider if by_provider is not None else touched, "tests": task.get("tests", []), "built": built,
                 "excluded": {"record-paths": [p for p in record_changes(target) if p not in (touched or [])]}}
        # how `touched` was attributed, when not by the measure alone: files a judgment gave this task, files another task's
        # finish pinned into its start, files its own word names that were already changed when it was added. A verifier that
        # saw only `touched: []` beside a tree holding the work rejected guin-site's escape-build on every retry
        attribution = {k: v for k, v in (("adopted", sorted(adopted_files(ts))), ("pinned-at-finish-of", ts.get("pinned") or {}),
                                         ("held-at-start", held_at_start(target, task, ts) if isinstance(ts.get("start"), dict) else [])) if v}
        if attribution:
            extra["attribution"] = attribution
        if by_provider is not None:
            extra["touched_since"] = sorted(set(touched) - set(by_provider))   # changed after the builder answered: a person's plan edits, say — not the builder's
        if ts.get("start-head") or ts.get("start-heads"):
            # the commits the work is measured from, the project's (".") and each nested repository's: a diff from there holds
            # work committed during the task, which `git diff HEAD` shows as nothing (sagoforce 10-26: every task committed)
            extra["since"] = {**({".": ts["start-head"]} if ts.get("start-head") else {}), **(ts.get("start-heads") or {})}
        writers = test_writers(plan, state, task)
        said = {w: [n[len("(provider) "):] for n in state["tasks"][w].get("non-claims", []) if str(n).startswith("(provider) ")] for w in writers}
        if any(said.values()):
            extra["tests_non_claims"] = {w: ns for w, ns in said.items() if ns}   # what the tests' writer says its tests do not decide: the verifier reads the code there
        # what chongdae itself ran on the tree and saw: the session's `--checked`, and the task's own checks it ran just now to
        # decide the task. guin-site run-20261015-054352-a0ec: chongdae had run the suite green before the verifier, the
        # request said nothing of it, and the verifier rejected the build's "the full check passes" as unverified
        checked = [{**r, "source": "--checked", "changed_since": touched_files(target, ts["checked"].get("checked-tree") or {}) or []}
                   for r in (ts.get("checked") or {}).get("ran") or []]
        checked += [{**r, "source": "the task's checks, run by chongdae to decide it", "changed_since": touched_files(target, ts.get("checks-tree") or {}) or []}
                    for r in (ts.get("checks-passed") or {}).get("ran") or []]
        if checked:
            extra["checked"] = checked
        last = next((a for a in reversed(ts.get("attempts", [])) if (a.get("review") or {}).get("verdict") == "reject" and isinstance(a.get("reviewed_tree"), dict)), None)
        if last:
            # a re-verification: what the last reject found, and what changed since that verdict. Re-reading the whole slice
            # each round cost the verifier its full time again and found a new edge each time — the rounds did not converge.
            # A finding chongdae overruled is not asked about again
            gone = [o.get("finding") for o in (last.get("overruled") or {}).get("findings") or []]
            extra["recheck"] = {"findings": [f for f in last["review"].get("findings", []) if f not in gone], "changed_since": touched_files(target, last["reviewed_tree"]) or []}
        code = empty_contract_stop(target, plan, task, "the verifier")
        if code is not None:
            return code
        if "review-source" not in ts:
            tag = stage_tag(task["id"], "verify", ts.get("attempts", []))
            old = any(os.path.exists(work_path(d, tag + suffix)) for suffix in (".pending.json", ".response.json"))
            # Older pending requests have no witnessed input. Consume their
            # process normally, but require a fresh review before completing.
            ts["review-source"] = {"": "unwitnessed"} if old else current
            save_state(d, state)
        code, review, _ = spawn(target, d, task, prov["verifier"], plan, ts.get("attempts", []), stage="verify", extra=extra)
        if code == DISPATCH:
            return stop(dispatch_text(task["id"] + " (verify)", review))
        if code == WAITING:
            return waiting_stop(task["id"] + " (verify)", review)
        current = source_tree(target, record_scope(target, task))
        if ts.get("review-source") != current:
            return invalidate_review(ctx, task, ts, current, review)
        ts["review"] = review
        ts["verdict-given"] = stamp()   # when the eyes answered: the verification's end, for `show`
        ts["reviewed_tree"] = dirty(target)   # the tree this verdict was about: the next round is measured from here
        if review.get("verdict") == "reject":
            # a finding stands on its quotes: one whose record quote is not where it says, or that calls unverified a check
            # chongdae itself saw pass, is no ground to resend the work — said and kept, like a refusal the checks overruled
            asked = load(work_path(d, stage_tag(task["id"], "verify", ts.get("attempts", [])) + ".request.json"))
            out = [{"finding": f, "why": why} for f in review.get("findings") or [] for why in [unfounded(f, asked)] if why]
            if out:
                ts["overruled"] = {"findings": out, **stamp()}
                for o in out:
                    ts.setdefault("non-claims", []).append("%s: chongdae overruled the verifier's %s finding at %s — %s" % (task["id"], o["finding"].get("kind"), o["finding"].get("where"), o["why"]))
        # what the eyes say they did not do — dwitbuk's `read` gate: "accepted without reading the tree: …", "the eyes read the
        # diff only …", "what the eyes read is not on record". Stored in the review and read by nobody, an accept without
        # reading looked like any accept: printed here, kept on the task, an observation in `report`
        for n in review.get("non-claims") or []:
            if isinstance(n, str) and n.strip():
                said = "(verifier) " + n.strip()
                print("  %s: the verifier's non-claim: %s" % (task["id"], n.strip()))
                if said not in ts.setdefault("non-claims", []):
                    ts["non-claims"].append(said)
        for n in review.get("unfounded") or []:
            # what the verifier's own runner dropped as unfounded (dwitbuk 1.14.0 weighs its eyes' answer): kept in the review, said here
            if isinstance(n, dict):
                print("  %s: the verifier dropped an unfounded finding: %s — %s" % (task["id"], finding_line(n), n.get("unfounded")))
        ts["verified_by"] = against_run(with_trace(performer(prov["verifier"], argv=prov["verifier"] if isinstance(prov["verifier"], list) else [prov["verifier"]], response=review, target=target), review, d, target), state)
        if review.get("verdict") == "accept" and not native_argv(target, prov["verifier"]):
            # (not when the session wrote the verdict for a native subagent: chongdae did not observe what was read)
            # the providers' own non-claims went to the verifier with the work (`built`, `tests_non_claims`) and it accepted:
            # read by the eyes placed for exactly that, they are information now, not charges a person disposes again
            # (guin-site, 10-07 → 10-10: 175 of 281 review charges were these, disposed in bulk in 68 seconds)
            for tid in [task["id"]] + test_writers(plan, state, task):
                other = state["tasks"][tid]
                seen = [n for n in other.get("non-claims", []) if str(n).startswith("(provider) ")]
                if seen:
                    other["seen-non-claims"] = {"by": "verifier of %s" % task["id"], "texts": seen, **stamp()}
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
        gone = [o["finding"] for o in (ts.get("overruled") or {}).get("findings") or []]
        standing = [f for f in review.get("findings", []) if f not in gone]
        for o in (ts.get("overruled") or {}).get("findings") or []:
            print("  %s: the verifier's finding is unfounded, overruled (recorded): %s — %s" % (task["id"], finding_line(o["finding"]), o["why"]))
        if gone and not standing:
            # nothing the verifier found stands: the slice goes on as accepted — the reject, and why it was overruled, stay on record
            print("  %s: nothing the verifier found stands — going on as accepted" % task["id"])
            return None
        ts["rejected"] = {"by": "verifier", "why": "%d finding(s)" % len(standing) + (", %d overruled" % len(gone) if gone else "")}
        save_state(d, state)
        lines = [finding_line(f) for f in standing]
        # back to the hands on its own — unless the hands are the session reading this stop: resending to it would
        # only run the verifier again on the same tree. What goes back is said here, whole: guin-site 10-15 printed only
        # "the verifier rejected: 1 finding(s)", and the session dug the finding out of attempts[0].review
        if who not in SESSION_HANDS and auto_resends_left(ts):
            print("  %s: the verifier rejected the slice:" % task["id"])
            for line in lines:
                print("    " + line)
            setattr(args, "continuing", True)
            auto_resend(target, d, state, task["id"], "the verifier rejected: %d finding(s)" % len(standing))
            return cmd_run(args)
        return stop("%s: the verifier rejected the slice — fix the tree (or the contract, and re-plan), then `chongdae retry %s --by NAME | --delegated WHY`" % (task["id"], task["id"]), *lines)
    return None


def finding_line(f):
    """A verifier's finding, whole, on one line: kind, where, why, and both quotes."""
    return "%s @ %s: %s — record: “%s” — tree: “%s”" % (f.get("kind"), f.get("where"), f.get("why"), f.get("record_quote"), f.get("tree_quote"))


def verdict_of(rec):
    """The verdict a task (or an attempt) stands on: the verifier's, except a reject every finding of which chongdae overruled
    (`overruled`) — that slice went on as accepted."""
    rv = rec.get("review") or {}
    if rv.get("verdict") == "reject" and rv.get("findings"):
        gone = [o.get("finding") for o in (rec.get("overruled") or {}).get("findings") or []]
        if all(f in gone for f in rv["findings"]):
            return "accept"
    return rv.get("verdict")


REQUEST_FIELD = re.compile(r"(?<![\w/.-])([A-Za-z_][\w-]*)((?:\.[\w-]+|\[\d+\])*)(?![\w/-])")


def request_field(request, head, rest):
    """(path, value): what `head` + `rest` (`.key`, `[n]`) names in the request — as deep as it resolves."""
    value, path = request[head], head
    for m in re.finditer(r"\.([\w-]+)|\[(\d+)\]", rest):
        key, idx = m.group(1), m.group(2)
        if key is not None and isinstance(value, dict) and key in value:
            value, path = value[key], path + "." + key
        elif idx is not None and isinstance(value, list) and int(idx) < len(value):
            value, path = value[int(idx)], path + "[%s]" % idx
        else:
            break
    return path, value


def texts_in(value, path):
    """[(path, text)] — every string (and number) under value, with where it is."""
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in texts_in(v, "%s.%s" % (path, k))]
    if isinstance(value, list):
        return [x for i, v in enumerate(value) for x in texts_in(v, "%s[%d]" % (path, i))]
    return [(path, str(value))] if value is not None and not isinstance(value, bool) else []


def quote_norm(s):
    return " ".join(str(s).split()).strip(" .,;:\"'“”‘’").casefold()


OTHER_HANDS = ("tests_non_claims", "checked")   # in a build's verify request, words that are not the builder's

NOT_RECORD = ("artifact-type", "written_by", "stage", "run", "task", "role", "target", "response")   # a request's addressing, not its record


def unfounded(f, request):
    """Why a verifier's finding is no ground for a reject, or None when it stands (or cannot be checked here). Two cases:
    its `where` names a field of the request and its record quote — each `quoted` span, or the whole when it quotes nothing —
    is not in the request's own words (the contract, the brief, the builder's report; a file `where` names or the slice
    touched), or is only in another hand's (`tests_non_claims`, `checked`) that `where` does not name — the tests writer's
    words are not the build's report. And a `claim-unverified`
    about a check chongdae itself ran on this tree and saw pass (`checked`, nothing changed since), unless it quotes the
    contract sentence the check is said not to decide — whether a check ran and passed is what chongdae observed; whether it
    decides a sentence stays the verifier's. guin-site run-20261015-054352-a0ec: the verifier rejected cache-build, quoting
    "`built.non-claims` says: `I did not run the whole suite.`" — a sentence only tests_non_claims.cache-tests[8] held —
    after chongdae had run that suite green itself; the build was resent for it. dwitbuk weighs its own answers the same
    way (`unfounded` in its response); this is the second line."""
    if not isinstance(request, dict) or not request:
        return None
    rq = str(f.get("record_quote") or "")
    named = []
    for m in REQUEST_FIELD.finditer(str(f.get("where") or "")):
        if m.group(1) in request and m.group(1) not in NOT_RECORD:
            named.append(request_field(request, m.group(1), m.group(2)))
    spans = [s for s in re.findall(r"`([^`]+)`", rq)
             if not (REQUEST_FIELD.fullmatch(s.strip()) and re.split(r"[.\[]", s.strip())[0] in request)]   # `built.non-claims` names a field, it quotes nothing
    if not spans and "`" not in rq:
        spans = [p for p in re.split(r"…|\.\.\.", rq) if len(quote_norm(p)) >= 8]
    if f.get("kind") == "claim-unverified":
        contract = [quote_norm(t) for _, t in texts_in(request.get("contract"), "contract")]
        about_contract = any(quote_norm(s) and quote_norm(s) in t for s in spans for t in contract)
        said = quote_norm(" ".join(str(f.get(k) or "") for k in ("where", "record_quote")))
        for r in request.get("checked") or []:
            cmd = quote_norm(" ".join(r["command"]) if isinstance(r.get("command"), list) else r.get("command") or "") if isinstance(r, dict) else ""
            if cmd and r.get("exit") == 0 and not r.get("expect") and not r.get("changed_since") and cmd in said and not about_contract:
                return "it calls `%s` unverified, and chongdae itself ran it on this tree and saw exit 0 (%s), nothing changed since" % (
                    r["command"], r.get("source") or "checked")
    if not named or not rq.strip():
        return None   # the tree, a file, a section by its title: nothing in the request to hold the quote against
    heads = {p.split(".")[0].split("[")[0] for p, _ in named}
    # the request's own words — the contract, the brief, the builder's report, a `where` one key off — but another hand's
    # (the tests writer's non-claims, what chongdae checked) only when `where` names it
    pool = [t for k, v in request.items() if k not in NOT_RECORD and (k not in OTHER_HANDS or k in heads) for _, t in texts_in(v, k)]
    root = str(request.get("target") or ".")
    for rel in list(request.get("touched") or []) + list(request.get("tests") or []) + re.findall(r"[\w.-]+(?:/[\w.-]+)*\.\w+", str(f.get("where") or "")):
        path = os.path.join(root, str(rel))
        inside = os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)
        if inside and os.path.isfile(path) and os.path.getsize(path) < 200000:
            pool.append(io.open(path, encoding="utf-8", errors="replace").read())
    pool = [quote_norm(t) for t in pool]
    for s in spans:
        q = quote_norm(s)
        if len(q) < 4 or any(q in t for t in pool):
            continue
        elsewhere = [p for k, v in request.items() if k not in NOT_RECORD for p, t in texts_in(v, k) if q in quote_norm(t)]
        where = ", ".join(p for p, _ in named)
        if elsewhere:
            whose = " — the tests writer's words, not the build's report" if elsewhere[0].startswith("tests_non_claims") else ""
            return "its record quote `%s` is not in %s; the request has it only at %s%s" % (s, where, elsewhere[0], whose)
        return "its record quote `%s` is not in %s, nor anywhere in the request" % (s, where)
    return None


def end_of_pass(ctx):
    """Every task this machine could advance was advanced. A session run waits for the next `add` or `close`; a plan run
    with open tasks claimed elsewhere says so; a plan run with nothing open is complete — the reviewer is placed and the
    record committed."""
    args, target, d, state, plan = ctx["args"], ctx["target"], ctx["d"], ctx["state"], ctx["plan"]
    if plan.get("kind") == "session":
        open_ = open_tasks(plan, state)
        print("session run %s: %d task(s), %d open (%s) — `chongdae add` for the next piece, `chongdae close` at the end" % (os.path.basename(d), len(state["tasks"]), len(open_), ", ".join(open_) or "-"))
        return 0
    if any(state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped") for t in all_tasks(plan, state)):
        if ctx["named"]:
            print("selected tasks advanced; run %s still has open tasks: %s" % (os.path.basename(d), ", ".join(open_tasks(plan, state))))
            return 0
        return stop("nothing this machine can advance — the open tasks are claimed elsewhere (or blocked on them); pull and `chongdae run` again")
    state["status"] = "complete"
    state["ended"] = stamp()   # when the run ended: `show` gives its duration from `created` to here
    save_state(d, state)
    wrote = place_reviewer(target, d, state, plan)
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "complete — %s" % plan.get("goal", ""), also=wrote)
    said = said_last_run(target, d, state)
    print("run %s complete. non-claims: %s" % (os.path.basename(d), [n for n in non_claims(state) if n not in said] or "none"))
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
        if when == "before" or role in CONTRACT_READERS:   # a role hired before the work reads the contract, nothing else
            code = empty_contract_stop(target, plan, task, role)
            if code is not None:
                return code
        code, response, _ = spawn(target, d, task, provider, plan, ts.get("attempts", []), stage=role, extra=extra)
        if code == DISPATCH:
            return stop(dispatch_text("%s (%s)" % (task["id"], role), response))
        if code == WAITING:
            return waiting_stop("%s (%s)" % (task["id"], role), response)
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


def uncommitted_work(target, plan, state):
    """{file: [task ids]} — the files a finished task of this run counts as its work (`touched`, and anything under its
    `--scope`) that are not committed. A dropped task's window is not work that stands; an open task's is work in flight,
    left open with it."""
    now = dirty(target, records_too=True) or {}   # a record file is work when a task's `touched` or its own record scope says so
    if not now:
        return {}
    rp, out = record_paths(target), {}
    for t in all_tasks(plan, state):
        ts = state["tasks"].get(t["id"], {})
        if ts.get("status") not in ("done", "produced"):
            continue
        own = record_scope(target, t)
        mine = set(ts.get("touched") or []) | {f for f in now if scope_depth(f, t.get("scope")) is not None and (not f.startswith(rp) or in_entries(f, own))}
        for f in sorted(mine):
            if f in now:
                out.setdefault(f, []).append(t["id"])
    return out


def work_commit_lines(run_name, plan, state, loose, target=None):
    """The commands that commit a run's work, a commit per task: `git add -- FILE…`, then `git commit -m "<run>/<task>
    (session): <brief>" -- FILE…` (only those paths, whatever else is staged). The session's commits of a task's work read
    `run-<id>/<task> (session): …`; chongdae's own record commits keep `run-<id>: …`. guin-site 10-15: with no form given, the
    agent copied the engine's `run-<id>:` (737db95, bf90cdf) or made up `run:` (33b5bda), and `git log` could not tell the
    engine's commits from the agent's. A file in a nested repository is committed there (`git -C engine …`, its own path):
    sagoforce 10-26, with no lines printed, a subject named a run that did not exist."""
    briefs = {t["id"]: t.get("brief") or "" for t in all_tasks(plan, state)}
    nested = nested_repos(target) if target else []
    groups = {}
    for f in sorted(loose):
        repo, inner = repo_of(target, f, nested) if nested else ("", f)
        groups.setdefault((tuple(loose[f]), repo), []).append(inner)
    out = []
    for (tids, repo), files in groups.items():
        paths = " ".join(shlex.quote(f) for f in files)
        git = "git -C %s" % shlex.quote(repo) if repo else "git"
        subject = "%s/%s (session): %s" % (run_name, "+".join(tids), cut(briefs.get(tids[0]) or "the work of " + ", ".join(tids), 72))
        out += ["%s add -- %s" % (git, paths), "%s commit -m %s -- %s" % (git, shlex.quote(subject), paths)]
    return out


# What mentions an operation outside the repository in a task's brief or role — a report hint only, never evidence of
# execution or missing work. sagoforce 10-27: `check-publish-ready`, `deploy.yml` and “미배포” described edits, yet six
# tasks stopped close as operations with no `did`. Wording cannot establish what ran. Keep the list small: the
# English verbs (not their participles: "the deployed version" is not one), and the Korean nouns not used as a modifier
# ("배포 버전", "배포한 템플릿", "삭제된 글"). guin-site run-20261015-054352-a0ec: cache-ops ("npm run deploy와 push, 배포 뒤
# …") was done with no `did`; the deploy ran as plain Bash piped through grep, the push as `git push | tail -1`, and the
# push survives only as prose in ATPROTO.md
OPS_WORDS = re.compile(r"(?<![A-Za-z])(deploy|push|publish|migrate|delete)(?![A-Za-z])|(배포|푸시|삭제|마이그레이션)(?!\s*버전|된|한\s|본)", re.I)


# A Bash command that is an operation outside the repository: the PreToolUse hook (hooks/pre_bash.py) says, while a run is
# running, that it goes through `did` — a line of context, never a refusal. Regular expressions searched in the command;
# hunsu.json `settings.chongdae.ops-patterns` (a list) replaces them, `[]` silences the hook. guin-site 10-15: `npm run
# deploy … | grep …; git push 2>&1 | tail -1`, both exit codes lost, the push written as prose in ATPROTO.md
OPS_PATTERNS = [r"\bgit\s+push\b", r"\bnpm\s+run\s+deploy\b", r"\bnpm\s+publish\b", r"\bwrangler\s+(deploy|publish|delete)\b",
                r"\bwrangler\s+\S+(\s+\S+)?\s+delete\b", r"\bterraform\s+(apply|destroy)\b", r"\bkubectl\s+(apply|delete)\b",
                r"\bgh\s+release\s+create\b", r"\b(fly|vercel|netlify|firebase)\s+deploy\b"]


def ops_patterns(target):
    declared = settings(target).get("ops-patterns")
    return [str(p) for p in declared] if isinstance(declared, list) else OPS_PATTERNS


# the engine on a command line: by its name, or by the variable a session keeps it in (`C=…/chongdae.py; python3 $C did …`) —
# sagoforce 10-26: `python3 $C did publish-root -- git push -u origin main` was told "record it", and four pushes after
# `$C close` on the same line were told the same instead of "after close"
_ENGINE_ON_LINE = r"(?:\S*chongdae(?:\.py)?|\$\{?\w+\}?)"


def command_segments(command):
    """A Bash line cut into its commands (at `;`, `&&`, `||`, `|` and newlines), quotes respected: an argument holding a `;`
    is not a command boundary."""
    out = []
    for line in str(command or "").split("\n"):
        try:
            lx = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lx.whitespace_split = True
            toks = list(lx)
        except ValueError:
            out.append(line)
            continue
        cur = []
        for tok in toks:
            if tok and set(tok) <= set(";&|"):
                out.append(" ".join(cur))
                cur = []
            else:
                cur.append(tok)
        out.append(" ".join(cur))
    return [s for s in out if s.strip()]


def bash_operation(target, command):
    """The part of a Bash command that reads as an operation outside the repository, or None. `chongdae.py did …` itself
    is the record, not something to record — the operation it runs is its argument."""
    for seg in command_segments(command):
        if re.search(r"(?:^|\s)%s\s+did\b" % _ENGINE_ON_LINE, seg):
            continue
        for p in ops_patterns(target):
            try:
                m = re.search(p, seg)
            except re.error:
                continue   # a pattern that does not compile matches nothing: a hook never fails a command over its own settings
            if m:
                return m.group(0)
    return None


def after_close(target, command):
    """Does the operation in this Bash command come after a `chongdae … close` on the same line? Then it runs once the run is
    closed, outside any run, and `did` can no longer record it. guin-site 10-15: `…run; git commit; close; git push` — the hook
    said "record it: did …", and the push ran after the run had closed."""
    closed = False
    for seg in command_segments(command):
        if closed and bash_operation(target, seg):
            return True
        if re.search(r"(?:^|\s)%s\s+(?:--?\S+(?:\s+[^-\s]\S*)?\s+)*close\b" % _ENGINE_ON_LINE, seg):
            closed = True
    return False


def reads_as_operation(task):
    """A lexical hint for the report, not a claim that an operation was intended or ran. A task its checks decide is a
    build, whatever its brief says about deploys."""
    if task.get("checks"):
        return None
    m = OPS_WORDS.search("%s %s" % (task.get("brief") or "", task.get("role") or ""))
    return m.group(0) if m else None


# the kinds of a reviewer's charge the tree can answer now, by the session, before the run closes: a question the model
# answers no longer (mangsang's cq-failed, cq-drifted, invariant-failed), a relation gone stale or broken, a record that
# contradicts the tree or the plan. A non-claim, a delegation, a carried charge are a person's to dispose — never a stop.
FIXABLE = ("cq-failed", "cq-drifted", "invariant-failed", "stale", "broken", "contradiction", "record-vs-tree", "plan-vs-code", "anomaly")


def review_kind(f):
    """The kind of charge a reviewer's finding makes: a carry (`undisposed`) makes the charge it carries — as dwitbuk counts."""
    return f["carries"][0] if f.get("kind") == "undisposed" and f.get("carries") else f.get("kind")


REVIEW_BEARING = r"\[x\d+\]|\[(?:tasks? [^\]]*|in \d+ runs: [^\]]*)\]"   # dwitbuk's BEARING: the words that say which tasks and runs bear a charge


def review_charge(f):
    """The charge a reviewer's finding makes, as dwitbuk tells one (`charge`/`identity`): a carry's is what it carries; any
    other's is its kind, where, and its text with the numbers that change between reviews struck."""
    if f.get("kind") == "undisposed" and f.get("carries"):
        return tuple(f["carries"])
    text = re.sub(REVIEW_BEARING + r"|\b\d+ file\(s\)|since [0-9a-f]{7,}|\(first seen [^)]*\)", "", f.get("text", "")).strip()
    return (f.get("kind"), f.get("where"), text)


def review_distinct(findings):
    """One per charge: two copies of one charge are one thing owed (dwitbuk `distinct`)."""
    seen, out = set(), []
    for f in findings:
        if review_charge(f) not in seen:
            seen.add(review_charge(f))
            out.append(f)
    return out


def review_count(findings):
    """Open charges counted as the reviewer counts them (dwitbuk `count_text`, word for word): each distinct charge once,
    under the kind of the charge it makes, kinds sorted, then how many of those are carried, said as included —
    `cq-failed 2, non-claim 10; 3 of them carried, already in the count`. guin-site review a3c2 read "non-claim 7,
    undisposed 3" at close and "non-claim 10" at the next session start: two counts of the same twelve; and a bare
    "; 3 carried" can be read as three more."""
    findings = review_distinct(findings)
    counts = {}
    for f in findings:
        counts[review_kind(f) or "?"] = counts.get(review_kind(f) or "?", 0) + 1
    carried = sum(1 for f in findings if f.get("kind") == "undisposed")
    return (", ".join("%s %d" % kv for kv in sorted(counts.items())) or "none") + ("; %d of them carried, already in the count" % carried if carried else "")


def fixable_findings(target, wrote):
    """The open objections in what the reviewer wrote (a `findings` list of the finding type: kind, where, text, layer) whose
    kind the tree can answer (FIXABLE) — raised now, not carried, not disposed."""
    out = []
    for p in wrote or []:
        try:
            doc = load(os.path.join(target, p))
        except (OSError, ValueError):
            continue
        for f in (doc.get("findings") if isinstance(doc, dict) else None) or []:
            if (isinstance(f, dict) and f.get("kind") in FIXABLE and f.get("layer", "objection") == "objection"
                    and not f.get("disposition")):
                out.append(f)
    return out


def take_back_review(target, wrote, before):
    """Undo what the reviewer wrote for a close that stopped: a review written for a close that did not happen would be the
    next review's base, and every charge fixed in between would come back carried as undisposed. A file it created is
    removed, one it changed is put back to HEAD; one that was already changed before it ran is left (said by the caller)."""
    import subprocess
    took = False
    for p in wrote or []:
        if p in before:
            continue
        full = os.path.join(target, p)
        if subprocess.run(["git", "cat-file", "-e", "HEAD:./%s" % p], cwd=target, capture_output=True).returncode == 0:
            took = subprocess.run(["git", "checkout", "-q", "HEAD", "--", p], cwd=target, capture_output=True).returncode == 0 or took
        elif os.path.isfile(full):
            os.remove(full)
            took = True
    return took


AUTO_RESENDS = 2   # per task: a verifier's reject or a refused report goes back to the hands this many times before a person is asked

def resend(target, d, state, task_id, retried, message=None, checked=None):
    """Send a stopped task out again, keeping the stopped attempt (its response, review, stages) in the record under its
    number — the next call receives it. `retried` says who sent it: a person (`by`), a delegation, or chongdae itself."""
    ts = state["tasks"][task_id]
    response = ts.pop("response", None)
    attempt = {**(response or {"status": "session"}), "retried": {**retried, **stamp()}}
    if response:
        with_trace(attempt, response, d, target)   # what this attempt's worker did stays with the attempt
    # the attempt keeps its verdict and its times — and what a verifier read of it (`seen-non-claims`), what chongdae ran
    # on it (`checked`, `checks-passed`) and which findings it overruled: a later attempt's report hid a non-claim no verifier
    # accepted for that attempt, and its verifier got old evidence
    for key in ("review", "review-source", "after-source", "rejected", "reviewed_tree", "answered", "verdict-given", "seen-non-claims", "checked", "checks-passed", "checks-tree", "checks-source", "overruled"):
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
    if checked:
        ts["checked"] = checked   # run for the next attempt
    ts.pop("reported", None)
    # what the provider said it did not claim was about the work this attempt did; the attempt keeps it (its response), the
    # task's own list keeps only what is still true — every attempt's copies piled up as near-duplicate findings
    if "non-claims" in ts:
        ts["non-claims"] = [n for n in ts["non-claims"] if not str(n).startswith(("(provider) ", "(verifier) "))]   # the verifier's: its review went with the attempt
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


def deleted_by_contract(target, plan, state, task):
    """{test path: the task that deleted it} — the task's tests the contract deleted: absent from the tree, and in the
    `touched` of the task that wrote this build's tests (a done or produced task that writes tests sharing any with it), or,
    for a tests task itself, in what its own earlier attempt changed. Kept on the task (`deleted-tests`) once said, so a
    build that recreates one is still told from one that never saw it. guin-site, 2026-10-12: the tests writer deleted four
    retired test files that were also in the build's --tests; the build was refused because its protected tests did not
    exist, and the session dropped it and added it again without them."""
    ts = state.get("tasks", {}).get(task.get("id"), {})
    out = dict(ts.get("deleted-tests") or {})
    tests = task.get("tests") or []
    for t in tests:
        if t in out or os.path.lexists(os.path.join(target, t)):
            continue
        if writes_tests(task):
            if t in set(ts.get("touched_by_provider") or []) | set(ts.get("touched") or []):
                out[t] = task["id"]
            continue
        for w in reversed(all_tasks(plan, state)):
            wts = state.get("tasks", {}).get(w.get("id"), {})
            if (w.get("id") != task.get("id") and writes_tests(w) and wts.get("status") in ("done", "produced")
                    and set(w.get("tests") or []) & set(tests) and t in (wts.get("touched") or [])):
                out[t] = w["id"]
                break
    return out


def deleted_note(gone):
    """The one line that says which of a task's tests the contract deleted, and what follows from it."""
    return ("note: %s deleted by the contract (%s) — left out of the tests its hands are sent and sent as `deleted-tests`; "
            "nothing restores or demands them, and a build that recreates one is refused"
            % (", ".join(sorted(gone)), "; ".join("%s by %s" % (w, ", ".join(sorted(t for t, x in gone.items() if x == w))) for w in sorted(set(gone.values())))))


def test_writers(plan, state, task):
    """The done tasks that wrote this build's protected tests, in plan order."""
    found = []
    for f in task.get("tests") or [] if not writes_tests(task) else []:
        w = tests_writer(plan, state, task, [f])
        if w and w["id"] not in found:
            found.append(w["id"])
    return found


def amending_tasks(plan, state, task, files):
    """The open tasks amending these tests for a dispute: the build that disputed them waits for them."""
    return [t["id"] for t in all_tasks(plan, state) if t.get("id") != task["id"] and state["tasks"].get(t["id"], {}).get("amending")
            and state["tasks"][t["id"]]["status"] not in ("done", "skipped", "dropped") and set(t.get("tests") or []) & set(files)]


def rebaseline(target, d, task, ts, plan, state):
    """The tests this build disputed were amended by the task that owns them; they are the contract again — in the build's
    start (so the amendment is not read as the build changing them) and in its kept copies (so a judgment that restores
    the contract's tests restores the amended ones, not what the dispute was about). The amendment is every file of the
    build's tests the writer changed since it was reopened, not only the ones the dispute named: a fix lands where the
    cause is (guin-site write-post-tests fixed a shared `write_support.py` for a dispute naming two test files, and the
    build's next judgment restored it as "changed protected tests")."""
    now = dirty(target) or {}
    files = ts.pop("rebaseline")
    writer = tests_writer(plan, state, task, files)
    wts = state["tasks"].get(writer["id"], {}) if writer else {}
    if wts.get("amending") is not None and wts.get("start") is not None:
        amended = touched_files(target, wts["start"], wts.get("start-head"), heads=wts.get("start-heads")) or []
        files = sorted(set(files) | (set(amended) & set(task.get("tests") or [])))
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
    if writer:
        refused = mutation_owner_refusal(target, d, writer["id"], state["tasks"][writer["id"]])
        if refused:
            if judgment is not None:
                raise SystemExit(refused)
            print("  tests dispute cannot reopen its writer: " + refused)
            return None
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
                   **{k: wts.pop(k) for k in ("answered", "done", "touched", "seen-non-claims", "checked", "review",
                       "review-source", "after-source", "reviewed_tree", "verdict-given", "checks-passed", "checks-tree", "checks-source") if k in wts}}
        # The amendment is new work: result witnesses and after observers belong to the old attempt.
        after = {role: rec for role, rec in wts.get("stages", {}).items() if rec.get("when") == "after"}
        if after:
            attempt["stages"] = after
            wts["stages"] = {role: rec for role, rec in wts["stages"].items() if role not in after}
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
    wts["start"], wts["start-head"] = dirty(target, keep=record_scope(target, wts.get("def"))) or {}, head_sha(target)
    wts["start-heads"] = nested_heads(target)
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
             "the session" if wts.get("taken") or writer.get("role") == "session" else "the session's sub-agent" if writer.get("role") == "subagent" else writer.get("role")))
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
                           "added": now_utc(), **({"added-in": this_session()} if this_session() else {}),
                           "non-claims": ["no check decides this task; done means the agent said so"]}
    return tdef


def auto_resends_left(ts):
    """Has this task an automatic resend left (AUTO_RESENDS)?"""
    return sum(1 for a in ts.get("attempts", []) if (a.get("retried") or {}).get("auto")) < AUTO_RESENDS


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
    if run_dir(target) and load_state(run_dir(target)).get("status") == "running" and not (
            getattr(args, "parent", None) and os.path.basename(run_dir(target)) == str(args.parent).partition("/")[0]):
        # sagoforce 10-26: another live session's run; told "finish it or remove it", the session did an audit of 41 sub-agents
        # and a production read with no run at all. A run holds many sessions' tasks — the way in is `add`, not a second run
        import time
        d = run_dir(target)
        try:
            idle = int((time.time() - os.path.getmtime(os.path.join(d, "state.json"))) // 60)
        except OSError:
            idle = None
        raise SystemExit("a run is already in progress: %s (%s; last written %s) — add this work to it as its own task "
                         "(`chongdae add TASK --brief … --scope PATH…`: a run holds any session's tasks, the scopes keep them apart), "
                         "or wait for its `close`; remove it only if nobody works in it any more"
                         % (d, cut(load_plan(d).get("goal") or "-", 80),
                            "%d min ago" % idle if idle is not None else "at an unknown time"))
    parent = parent_link(args) if getattr(args, "parent", None) else None   # a child of the running run may start beside it
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
    state = {"status": "running", "tasks": {t["id"]: {"status": "todo"} for t in plan["tasks"]}, "non-claims": list(plan.get("non-claims", []))}
    state["created"] = {**stamp(), "based_on": head_sha(target), **({"nested": nested_heads(target)} if nested_repos(target) else {})}   # the commit this run starts from: its place in history is ancestry, not its id's timestamp
    locked = locked_versions(target)
    if locked:
        state["environment"] = {"locked": locked}   # the lock every call in this run ran under, once; a task says `locked` only when it differs
    if getattr(args, "worktree", False):
        state["worktree"] = {"main": os.path.abspath(args.target).replace(os.sep, "/"), "branch": "run/" + run_name}
    if parent:
        scopes = parent.pop("_scopes", None)
        state["parent"] = parent   # the parent's `show` finds its children by this link; nothing is written into the parent
        if scopes:
            save(work_path(d, "parent-lease.json"), {"scopes": scopes})
    save_state(d, state, plan=plan)
    commit_record(target, run_name, "init (%s) — %s" % (plan.get("kind", "?"), plan.get("goal", "")))
    print("run %s: goal %r — %s plan (%s). Now %s."
          % (os.path.basename(d), plan["goal"], plan.get("kind", "?"), " -> ".join(t["id"] for t in plan["tasks"]) or "no tasks yet",
             "`chongdae add <id> ...` for each piece of work, `chongdae run` to record it, `chongdae close` at the end" if args.session else "`chongdae run`"))
    if parent:
        print("child of %s / task %s%s" % (parent["run"], parent["task"], " (held at gen %s)" % parent["gen"] if parent.get("gen") else ""))
    if getattr(args, "worktree", False):
        print("this run lives in its worktree — every command from here on: --target %s" % target.replace(os.sep, "/"))
    return 0


def parent_link(args):
    """`init --parent RUN/TASK`: the run this one does a task of. The parent must be in this tree's record; under a lease the
    task is taken for this session now (held by someone else: refused), and the link carries the generation, so the child's
    merge back is refused if the hold has moved on (C8)."""
    run, _, tid = str(args.parent).partition("/")
    if not run or not tid or "/" in tid:
        raise SystemExit("--parent RUN/TASK: the parent run's id and the task of it this run does (run-20261012-101500-ab12/T1)")
    pd = os.path.join(args.target, RUNS, run)
    if not os.path.isdir(pd):
        raise SystemExit("--parent %s: no run %s in this tree's record (pull it first)" % (args.parent, run))
    plan, state = load_plan(pd), load_state(pd)
    task = next((t for t in all_tasks(plan, state) if t.get("id") == tid), None)
    if not task:
        raise SystemExit("--parent %s: %s has no task %s" % (args.parent, run, tid))
    link = {"run": run, "task": tid}
    leases = lease_backend(args.target)
    if leases:
        holder = lease_holder(args.target)
        ts = state["tasks"].setdefault(tid, {"status": "todo"})
        try:
            r = take_task(leases, run, task, ts, holder)
        except LeaseError as err:
            raise SystemExit("--parent %s: the lease store cannot be reached (%s) — a child run starts on a held task, and this one cannot be taken" % (args.parent, err))
        if not r["ok"]:
            raise SystemExit("--parent %s: %s is held by %s (gen %s) — `chongdae claim --list`, and take a ready one" % (args.parent, tid, holder_text((r.get("lease") or {}).get("holder")), (r.get("lease") or {}).get("gen")))
        save_state(pd, state)
        link["gen"] = r["lease"]["gen"]
        link["_scopes"] = ts["lease-held"].get("scopes") or []
    return link


def cmd_add(args):
    """A task in a session run, defined when the work starts. Its start snapshot is taken now, so `touched` is this task's own."""
    d = run_dir(args.target)
    if not d:
        raise SystemExit("no run in progress — `chongdae init --session`")
    plan, state = load_plan(d), load_state(d)
    if state.get("status") != "running":
        raise SystemExit("no run in progress — `chongdae init --session`")
    if plan.get("kind") != "session":
        raise SystemExit("tasks are added to session runs only; a plan run's tasks are the plan's")
    if remote_mode(args.target) == "shared":
        # the remote is the one truth: a task another machine added there is seen before this one is named
        r = remote_before(args.target, "`add`")
        if r is not None:
            return r
        plan, state = load_plan(d), load_state(d)
    checks = [portable_argv(shlex.split(c)) for c in args.check or []]
    if args.id in state["tasks"] and checks:
        return add_checks(args, d, plan, state, checks)
    if args.id in state["tasks"] or any(t.get("id") == args.id for t in plan.get("tasks", [])):
        raise SystemExit("task %s exists" % args.id)
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
        own = {"instead-of": due, "why": args.why, "by": signer(args), **stamp()}
    scope = []
    for x in args.scope or []:
        c = clean_path(x)
        if c.startswith("/") or ":" in c or ".." in c.split("/"):
            raise SystemExit("--scope %s: a scope is project-relative (a file or a directory in this project)" % x)
        scope.append(c)
    task = {"id": args.id, "role": role, "brief": args.brief or "", "closes": args.closes or [], "needs": [], "checks": checks,
            "tests": args.tests or [], "gate": "human" if args.gate == "human" else None, **({"domain": args.domain} if args.domain else {}),
            **({"requires": args.requires} if args.requires else {}), **({"scope": sorted(set(scope))} if args.scope else {})}
    hands = hire(declared, task)[1]
    for when in ("before", "after"):
        if getattr(args, when) is not None:
            task[when] = getattr(args, when)
    problems = [x for x in plan_problems({"artifact-type": "chongdae/plan@1", "goal": "x", "tasks": [task]}) if "needs `path`" not in x]
    # a session build takes its start snapshot now: protected tests it names must exist already, or writing them would read
    # as the build changing its own contract (a provider's build takes its snapshot when spawned, after the tests' task ran)
    gone = deleted_by_contract(args.target, plan, state, task) if task["tests"] else {}
    if hands in SESSION_HANDS and task["checks"]:
        problems += ["--tests %s: does not exist yet — a session build's start is taken at `add`, so writing its tests after "
                     "would read as the build changing them; write the tests in their own task first (`add`, work, `run`), "
                     "then add this one" % f for f in task["tests"] if not os.path.exists(os.path.join(args.target, f)) and f not in gone]
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
    if gone:
        ts["deleted-tests"] = gone   # said here, once: `run` says only a deletion made after this
    instead = due if task["role"] == "subagent" and due and hire(declared, {"role": due, "requires": args.requires})[1] != "subagent" else None
    if task["role"] == "subagent" and (instead or args.why):
        # the session's sub-agent stands where the lock declared someone else: declared hands, not the session's own — but
        # the record says whose place it took, and who said so. Its `--why` is kept with no role due too: sagoforce 10-26,
        # eight fix batches said why they went to sub-agents in parallel, and the record kept none of it
        ts["dispatched"] = {"to": "subagent", **({"instead-of": instead} if instead else {}), "by": signer(args), **({"why": args.why} if args.why else {}), **stamp()}
    if hands in SESSION_HANDS:
        ts["start"] = dirty(args.target, keep=record_scope(args.target, task))   # the session works between `add` and `run`: what changed is measured from now
        ts["start-head"] = head_sha(args.target)
        ts["start-heads"] = nested_heads(args.target)
        keep_contract_tests(args.target, d, task)
    # a provider's task starts when `run` spawns it (`start` is taken then): a build added alongside its test task must not see the test-writer's file as its own change
    if not task["checks"]:
        ts["non-claims"] = ["no check decides this task; done means the agent said so"]
    if this_session():
        ts["added-in"] = this_session()   # whose task this is, including hired hands that may still be out after this call
    state["tasks"][args.id] = ts
    save_state(d, state)
    if hands == "subagent":
        print("added %s to %s — the session's sub-agent does it (%s)%s. Dispatch it, then `chongdae run` decides it from the tree."
              % (args.id, os.path.basename(d), "as asked" if task["role"] == "subagent" else "the lock's %s" % hire(declared, task)[0],
                 " — instead of the lock's %s: recorded" % ts["dispatched"]["instead-of"] if (ts.get("dispatched") or {}).get("instead-of") else ""))
    elif hands == "session":
        # a day's repair run added every task with no check, and the lock's implementer was never sent one (sagoforce, 10-26)
        builder = not task["checks"] and args.role is None and hire(declared, {"role": "implementer", "requires": args.requires})[1] is not None
        print("added %s to %s%s%s. Work, then `chongdae run`." % (args.id, os.path.basename(d), " (no checks — done will be a claim, recorded as such%s)"
                                                                  % ("; the lock's implementer takes a task a check decides: `--check C` sends it this one" if builder else "") if not task["checks"] else "",
                                                                  " — the session does it itself, instead of the lock's %s: recorded" % own["instead-of"] if own else ""))
    else:
        key = hire(declared, task)[0]
        print("added %s to %s — %s does it (%s). `chongdae run` sends it out." % (args.id, os.path.basename(d), key,
              ("the lock's alternate for %s" % ", ".join(task["requires"])) if key != task["role"] else "the lock's provider" if args.role is None else "as asked"))
    gap = contract_gap(args.target, plan, task) if task["closes"] else None
    if gap:
        # said now, not found by the quibbler: guin-site's run without `--from` sent Q-cleanup's quibble `contract: {}`
        print("  note: --closes %s: %s — its hands get the brief alone, and `run` sends no quibbler or verifier this task's request "
              "until the section can be read (%s)" % (", ".join(task["closes"]), gap,
              "add it to %s" % plan["from"] if plan.get("from") and os.path.isfile(os.path.join(args.target, plan["from"]))
              else "a run started with `chongdae init --session --from PLAN` sends the sections"))
    if task.get("scope") and hands not in SESSION_HANDS:
        print("  --scope: %s — its hands are a worker measured by its own call; the scope is kept on the task and holds files against the session's open tasks" % ", ".join(c or "." for c in task["scope"]))
    elif task.get("scope"):
        same = [t2["id"] for t2 in all_tasks(plan, state) if t2["id"] != args.id and state["tasks"].get(t2["id"], {}).get("status") == "todo"
                and set(t2.get("scope") or []) & set(task["scope"])]
        print("  --scope: %s — while scoped tasks are open, a changed file is the open task's whose scope holds it most narrowly, not the first to finish's%s"
              % (", ".join(c or "." for c in task["scope"]), "; note: %s %s the same scope entry — a file there is said at the finish, with the `adopt` that settles it"
                 % (", ".join(same), "has" if len(same) == 1 else "have") if same else ""))
    offer = check_offer(args.target, task) if hands in SESSION_HANDS else None
    if offer:
        print("  note: " + offer)
    if task.get("scope") and record_scope(args.target, task):
        recs = record_scope(args.target, task)
        print("  --scope: %s record path%s %s (another product's files) — that is fine: inside this task's own scope a record file is its work "
              "(counted in `touched`, its commit lines printed, not held as changing nothing); outside every task's scope a record stays nobody's"
              % ("names only" if len(recs) == len(task["scope"]) else "names", "" if len(recs) == 1 else "s", ", ".join(recs)))
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
        if gone:
            print("  " + deleted_note(gone))
    if remote_mode(args.target):
        # under `sync` or `shared` a task travels when it is named: another machine cannot take a task its record has not got
        # (two clones on GitHub, 2026-10-13: `add` left tasks/ uncommitted and the other machine answered "no task T1")
        commit_record(args.target, os.path.basename(d), "add %s — %s" % (args.id, (task.get("brief") or "")[:120]))
    return 0


def add_checks(args, d, plan, state, checks):
    """`add TASK --check C` on an open session task that has no check: the check is attached, and decides it from now on — the
    line `add` and `run` offer when the project declares a check for the task's scope (`settings.chongdae.checks-for`). Only
    the check: a task's brief, scope and tests are what it was added with."""
    ts = state["tasks"][args.id]
    refused = mutation_owner_refusal(args.target, d, args.id, ts)
    if refused:
        raise SystemExit(refused)   # add may have refreshed the shared record after the command preflight
    task = ts.get("def")
    other = [o for o in ("brief", "closes", "tests", "scope", "gate", "before", "after", "domain", "requires") if getattr(args, o, None) not in (None, [])]
    declared = providers(args.target, plan)
    if not task or ts.get("status") != "todo" or task.get("checks") or other or hire(declared, task)[1] not in SESSION_HANDS:
        raise SystemExit("task %s exists — `add %s --check C` attaches a check only to an open session task that has none, with nothing else given%s"
                         % (args.id, args.id, " (given: %s)" % ", ".join("--" + o for o in other) if other else ""))
    due = hire(declared, {"role": "implementer", "requires": task.get("requires")})[1] is not None and task["role"] == "session"
    if due and not ts.get("self-performed"):
        if not args.why:
            raise SystemExit("add %s --check: the lock declares an implementer for a task a check decides — say why the session does it itself (--why)" % args.id)
        ts["self-performed"] = {"instead-of": "implementer", "why": args.why, "by": signer(args), **stamp()}
    task["checks"] = checks
    ts["non-claims"] = [n for n in ts.get("non-claims") or [] if n != "no check decides this task; done means the agent said so"]
    if not ts["non-claims"]:
        ts.pop("non-claims")
    ts.setdefault("checks-added", []).append({"checks": checks, "by": signer(args), **stamp()})
    save_state(d, state)
    print("%s: check attached — %s; `chongdae run` decides it by the check" % (args.id, "; ".join("`%s`" % shlex.join(c) for c in checks)))
    if remote_mode(args.target):
        commit_record(args.target, os.path.basename(d), "add %s --check" % args.id)
    return 0


def take_operation_recovery(args, d, state, task, ts, journal):
    """An abandoned operation needs a new owner to inspect its effects. Transfer only that ownership: do not run
    checks, rotate responses, reopen a done task, clear the journal, or infer the interrupted operation's outcome."""
    if args.checked or args.checked_red:
        raise SystemExit("take: interrupted operation recovery transfers ownership only — omit --checked and --checked-red; nothing executed")
    if not this_session():
        raise SystemExit("take: this call has no session identity — identify this session before taking interrupted operation recovery; no ownership changed")
    if pid_alive(journal.get("operation-pid")):
        return stop("session agent: %s's operation %s still has a running process — wait for it to stop before taking recovery; no ownership changed" % (args.task, journal["id"]))
    active = task_in_flight(d, args.task)
    if active:
        return stop("session agent: %s still has work in flight (%s) — wait for its answer before taking operation recovery; no ownership changed" % (args.task, ", ".join(active)))
    leases = lease_backend(args.target)
    try:
        cur = leases.current(task_key(os.path.basename(d), args.task)) if leases else None
        holder = lease_holder(args.target)
        foreign_lease = cur and not same_holder(cur.get("holder"), holder)
        foreign_claim = not leases and ts.get("claimed_by") and claim_owner(ts["claimed_by"]) != me(args.target)
        # Plan tasks need not carry added-in: the actual lease/claim still identifies a different owner.
        if not (other_session(ts) or foreign_lease or foreign_claim):
            return stop("session agent: this session already owns %s's interrupted operation — resume or reconcile it with `chongdae did`; no ownership changed" % args.task)
        if foreign_lease:
            if not lapsed(cur):
                return stop("session agent: %s is held by another session — wait for its lease to expire before taking interrupted operation recovery; no ownership changed" % args.task)
            # Expiry permits a new hold, not silent use of the previous holder's generation.
            result = take_task(leases, os.path.basename(d), task, ts, holder)
            if not result["ok"]:
                return stop("session agent: %s's hold changed or its scope is held elsewhere — retry taking recovery after the holder finishes; no ownership changed" % args.task)
        if foreign_claim:
            return stop("session agent: %s is claimed by %s — its owner must release the claim before recovery can be handed over; no ownership changed" % (args.task, signer_text(ts["claimed_by"])))
    except LeaseError as err:
        return stop("session agent: the lease store cannot be reached (%s) — no recovery ownership changed" % err)
    ts["added-in"] = this_session()
    ts.setdefault("handoffs", []).append({"why": args.why, "by": signer(args), "purpose": "operation-recovery", "operation": journal["id"], **stamp()})
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "take %s for interrupted operation recovery: %s" % (args.task, args.why))
    print("took %s for interrupted operation recovery only — its task status and unknown outcome stay unchanged; inspect the external effects, "
          "then `chongdae did %s --reconcile %s --why WHY`. Nothing executed." % (args.task, args.task, journal["id"]))
    return 0


def cmd_take(args):
    """The session finishes a task its hired hands could not: the work is in the tree (a sandbox stopped the worker, a guard
    judged the tree the session was also writing), and `drop` would record it as not done — three of guin-site's drops were
    done work (2026-09-30). The task becomes the session's: self-performed instead of its role, with the reason; the stopped
    attempt stays in `attempts`; `run` then decides it like any session task — its checks, the verifier, the gate."""
    d = run_dir(args.target)
    plan, state = (load_plan(d), load_state(d)) if d else ({}, {})
    if state.get("status") != "running":
        raise SystemExit("no session run in progress — `take` is for a session run's own tasks")
    ts = state["tasks"].get(args.task)
    if not ts:
        raise SystemExit("no task %s" % args.task)
    journal = operation_pending(d, args.task)
    if journal:
        task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), {"id": args.task})
        return take_operation_recovery(args, d, state, task, ts, journal)
    if plan.get("kind") != "session":
        raise SystemExit("no session run in progress — `take` is for a session run's own tasks")
    if ts["status"] != "todo":
        raise SystemExit("%s is %s — only an open task can be taken" % (args.task, ts["status"]))
    task = ts["def"]
    hands = providers(args.target, plan).get(task["role"])
    handover = other_session(ts)
    if handover and not this_session():
        raise SystemExit("take: this call has no session identity — set CHONGDAE_SESSION (or the host's session id) before taking another session's task; no ownership changed")
    if (ts.get("taken") or hands == "session" or task["role"] == "session") and not handover:
        raise SystemExit("%s is already the session's" % args.task)
    active = task_in_flight(d, args.task)
    if active:
        raise SystemExit("%s still has work in flight (%s) — wait for its answer before taking it; no ownership changed" % (args.task, ", ".join(active)))
    leases = lease_backend(args.target)
    if leases:
        try:
            cur = leases.current(task_key(os.path.basename(d), args.task))
        except LeaseError as err:
            raise SystemExit("take: the lease store cannot be reached (%s) — no ownership changed" % err)
        if cur and not lapsed(cur) and not same_holder(cur.get("holder"), lease_holder(args.target)):
            raise SystemExit("%s is held by another session — `claim --break %s --why WHY` is required before taking it" % (args.task, args.task))
    who = signer(args)
    checked = run_checked(args.target, args.checked, args.checked_red) if (args.checked or args.checked_red) else None   # before anything is recorded: a failing one refuses the take
    if handover:
        ts["added-in"] = this_session()
        ts.setdefault("handoffs", []).append({"why": args.why, "by": who, **stamp()})
        if ts.get("taken") or hands in SESSION_HANDS or task["role"] in SESSION_HANDS:
            if checked:
                ts["checked"] = checked
            save_state(d, state)
            commit_record(args.target, os.path.basename(d), "take %s from another session: %s" % (args.task, args.why))
            print("took %s from another session — its hands and evidence stay the same; `chongdae run %s` advances it" % (args.task, args.task))
            return 0
    msg = take_over(args.target, d, state, task, ts, args.why, who, checked=checked)
    print(msg)
    if checked:
        print("  checked by chongdae: %s — the verifier gets them as evidence chongdae saw, with what changed after" % checked_text(checked))
    else:
        # the session that takes a task usually ran something itself; guin-site's cleanup-tests take said so in prose
        print("  evidence chongdae saw: `take %s --why WHY --checked \"COMMAND\"` runs a command now and records its pass; "
              "`--checked-red \"COMMAND\"` records a tests task's expected red run (a pass is recorded as passed before the build)" % args.task)
    return 0


def operation_pending(d, tid):
    """The interrupted operation journal for this task; it is never permission to replay the command."""
    return load(work_path(d, tid + ".did.pending.json")) if d else {}


def operation_merge(d, state, tid, journal):
    """Publish completed items exactly once, including after a crash during the state transaction."""
    records = state["tasks"][tid].setdefault("did", [])
    offset = journal["record-start"]
    for item in journal["items"]:
        rec = item.get("result")
        if rec is None:
            break
        if len(records) > offset:
            if records[offset] != rec:
                raise SystemExit("did recovery: the task's operation history changed at item %d; nothing was replayed" % (offset + 1))
        else:
            if len(records) != offset:
                raise SystemExit("did recovery: the task's earlier operation history is missing; nothing was replayed")
            records.append(rec)
        offset += 1
    save_state(d, state)


def operation_argv(target, argv, journal_path, journal):
    """The operation may have effects even when its caller dies. Register its pid where possible, and leave the
    pre-execution intent unresolved on interruption; never infer 'not run' from an absent result."""
    import subprocess
    command = resolve_argv(target, list(argv))
    if command and command[0] in ("python", "python3") and not shutil.which(command[0]):
        command[0] = next((x for x in ("python3", "python") if shutil.which(x)), None) or sys.executable
    timeout = float(os.environ.get("CHONGDAE_CHECK_TIMEOUT") or 1800)
    try:
        proc = subprocess.Popen(command, cwd=target, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as err:
        return 127, str(err), False
    journal["operation-pid"] = proc.pid
    save(journal_path, journal)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out + err, True
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proc.kill()
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            # A descendant may have deliberately escaped the process group while retaining the pipes.
            # Keep the unknown intent, rather than hang or publish a settled result for a still-active operation.
            raise SystemExit("did: the timed-out operation still has open output pipes; its outcome stays unknown. Inspect and stop surviving processes before reconciliation")
        return 124, out + err + "\ntimed out after %ds; external effects may already have occurred" % timeout, True


def recover_operation(args, d, state, journal):
    """Restore observed results without executing anything. An unknown effect needs a reasoned reconciliation,
    not a fabricated successful exit or an automatic retry; items never started are left unexecuted."""
    path = work_path(d, args.task + ".did.pending.json")
    reconcile = getattr(args, "reconcile", None)
    if reconcile:
        if reconcile != journal["id"]:
            raise SystemExit("did: pending operation is %s, not %s; nothing executed" % (journal["id"], reconcile))
        if not args.why or not args.why.strip():
            raise SystemExit("did --reconcile needs --why: what external state you checked and why it is safe to proceed")
        if args.command or args.each or args.approved_in:
            raise SystemExit("did --reconcile records a judgment only; give no command, --each, or --approved-in")
    operation_merge(d, state, args.task, journal)
    unknown = [i for i, item in enumerate(journal["items"]) if item.get("status") == "started" and "result" not in item]
    if unknown:
        if pid_alive(journal.get("operation-pid")):
            return stop("session agent: operation %s still has a running process (pid %s); wait for it to stop and inspect its external effects. Nothing was repeated."
                        % (journal["id"], journal["operation-pid"]))
        if not reconcile:
            return stop("session agent: operation %s was interrupted; item %d has no observed outcome. Earlier results were recovered; nothing was repeated. "
                        "Inspect the external state and stop any surviving operation before `chongdae did %s --reconcile %s --why WHY`. "
                        "Reconciliation executes nothing; only then deliberately issue any remaining command."
                        % (journal["id"], unknown[0] + 1, args.task, journal["id"]))
        why = mask_secrets(args.why)[0]
        for i in unknown:
            intent = journal["items"][i]["intent"]
            journal["items"][i]["result"] = {**intent, "exit": None, "tail": [], "outcome": "unknown",
                "why": (intent.get("why", "") + "; interrupted outcome unknown; reconciliation: " + why).lstrip("; "),
                "reconciled": {"why": why, "by": signer(args), **stamp()}}
        journal["status"] = "reconciled"
        save(path, journal)
        operation_merge(d, state, args.task, journal)
    never_started = [i + 1 for i, item in enumerate(journal["items"]) if item.get("status") == "planned"]
    commit_record(args.target, os.path.basename(d), "did %s: recover %s%s" % (args.task, journal["id"], " (outcome unknown, reconciled)" if unknown else ""))
    journal["status"] = "reconciled" if reconcile else "recovered"
    save(work_path(d, args.task + ".did." + journal["id"] + ".json"), journal)
    os.remove(path)
    print("recovered operation %s for %s; no command executed%s" % (journal["id"], args.task,
          "; items never started: " + ", ".join(map(str, never_started)) if never_started else ""))
    if unknown:
        print("  its actual exit remains unknown; the reconciliation is the session's judgment, not an observed successful execution")
    return 0 if reconcile else DECISION   # supplied commands were not executed; a caller must not mistake recovery for their success


def cmd_did(args):
    """An operation outside the repository — a deploy, a secret deleted, a remote database changed — run through chongdae on a
    task: one command (argv, no shell line), recorded on the task as `did` whatever its exit, printed, and committed like any
    judgment. guin-site, 2026-10-12: the cleanup's eight operations (an archive, a deploy, secrets, Access, R2 and D1 deleted)
    ran as plain Bash in a todo task and survive only as prose in a plan file; nothing in the record says what ran, what it
    answered, or where the person agreed to the ones that cannot be undone. `--each FILE` runs several, one per line, as one
    judgment: guin-site's R2 emptying and deletion, and D1's, were one decision recorded as separate commits."""
    d = run_dir(args.target)
    plan, state = (load_plan(d), load_state(d)) if d else ({}, {})
    if state.get("status") != "running":
        raise SystemExit("no run in progress — `did` records an operation on a task of the running run (`chongdae init --session`, then `add`)")
    ts = state["tasks"].get(args.task)
    if not ts:
        raise SystemExit("no task %s — `chongdae add %s --brief ...` first: an operation is some task's work" % (args.task, args.task))
    if ts.get("status") in ("dropped", "skipped"):
        raise SystemExit("%s is %s — an operation is recorded on a task that is being done or was done" % (args.task, ts["status"]))
    pending = operation_pending(d, args.task)
    if pending:
        return recover_operation(args, d, state, pending)
    if getattr(args, "reconcile", None):
        raise SystemExit("did: this task has no interrupted operation to reconcile; nothing executed")
    usage = "`chongdae did %s [--why WHY] [--approved-in source:ID] -- COMMAND ARG...` (or `--each FILE`, one command per line)" % args.task
    if args.each and args.command:
        raise SystemExit("did: a command after `--` or `--each FILE`, not both — " + usage)
    if args.each:
        try:
            text = sys.stdin.read() if args.each == "-" else io.open(args.each, encoding="utf-8").read()
        except OSError as e:
            raise SystemExit("did --each %s: %s" % (args.each, e))
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        commands = [one_command(l, "did --each") for l in lines]
    else:
        commands = [list(args.command or [])] if args.command else []
        for argv in commands:
            shell_words(argv, "did", shlex.join(argv))
    if not commands or not all(commands):
        raise SystemExit("did: no command — " + usage)
    if args.approved_in is not None and not re.match(r"^[\w.-]+:\S+$", args.approved_in):
        raise SystemExit("--approved-in %r: where the person agreed, as source:ID (a mangsang source, `source:at-63`) or KIND:REF" % args.approved_in)
    import uuid
    journal_path = work_path(d, args.task + ".did.pending.json")
    journal = {"id": "O-" + uuid.uuid4().hex[:16], "task": args.task, "record-start": len(ts.get("did") or []),
               "status": "pending", "items": [{"status": "planned"} for _ in commands], **stamp()}
    save(journal_path, journal)   # even a crash before the first item cannot cause the invocation to be silently replayed
    recs, first_bad = [], None
    for i, argv in enumerate(commands, 1):
        shown, outside = outside_argv(args.target, argv)
        # what the record keeps of the command line and of what it answered, a secret's value masked (guin-site 10-16: a
        # secrets file's text went into a committed record; a value on the command line or echoed back would go the same way)
        shown, in_command = mask_argv(shown)
        intent = {"command": shlex.join(shown), **stamp(),
               **({"why": args.why} if args.why else {}), **({"approved-in": args.approved_in} if args.approved_in else {}), "signer": signer(args)}
        if outside:
            intent["outside"] = outside   # a script outside the project: the record keeps what it was, not a path on this machine
        if len(commands) > 1:
            intent["batch"] = {"of": len(commands), "n": i}
        journal["items"][i - 1] = {"status": "started", "intent": intent}
        journal.pop("operation-pid", None)
        save(journal_path, journal)   # before effects; an absent result means unknown, not permission to retry
        code, said, ran = operation_argv(args.target, argv, journal_path, journal)
        said, in_tail = mask_secrets(said)
        rec = {**intent, "exit": code, "tail": portable(kept_tail(said), args.target), **stamp()}
        if in_command or in_tail:
            rec["masked"] = {k: v for k, v in (("command", in_command), ("tail", in_tail)) if v}
        if not ran:
            rec["ran"] = False   # the process could not be started
        recs.append(rec)
        journal["items"][i - 1]["result"] = rec
        journal["items"][i - 1]["status"] = "finished"
        save(journal_path, journal)   # each batch result is durable before the next operation can start
        operation_merge(d, state, args.task, journal)
        if code:
            first_bad = i
            break   # one judgment, in order: what comes after a failure is not run on a state nobody has looked at
    journal["status"] = "finished"
    save(journal_path, journal)
    bad = [r for r in recs if r["exit"]]
    subject = (short_command(recs[0]["command"]) + " -> exit %d" % recs[0]["exit"] if len(commands) == 1
               else "%d operation(s)%s: %s" % (len(recs), " (stopped at %d of %d)" % (first_bad, len(commands)) if first_bad else "",
                                                 short_join(["%s -> %d" % (short_command(r["command"], 60), r["exit"]) for r in recs], 150)))
    commit_record(args.target, os.path.basename(d), "did %s: %s" % (args.task, subject))   # cut at argument boundaries already, never inside a marker
    for r in recs:
        print("did %s: `%s` -> exit %d%s — recorded on %s, signed %s%s" % (
            args.task, r["command"], r["exit"], "" if r.get("ran", True) else " (it did not run)", args.task, signer_text(r["signer"]),
            "; approved in %s" % args.approved_in if args.approved_in else ""))
        for line in r["tail"]:
            print("  | " + line)
        for o in r.get("outside") or []:
            print("  %s is outside the project: %s" % (outside_what(o), outside_text(o)))
        if r.get("masked"):
            print("  " + masked_text(r["masked"]))
    if first_bad and first_bad < len(commands):
        print("  not run (an earlier command exited non-zero): %s" % "; ".join(shlex.join(mask_argv(outside_argv(args.target, c)[0])[0]) for c in commands[first_bad:]))
    if bad:
        print("  a non-zero exit stays in the record: `report` lists it as an objection until a reviewer disposes of it")
    save(work_path(d, args.task + ".did." + journal["id"] + ".json"), journal)
    os.remove(journal_path)
    return 1 if bad else 0


DID_CONTENT_CAP = 32000   # bytes of an outside program the record keeps whole; past it, its hash and size

# The program a command runs, when argv[0] is an interpreter: the first argument after it that is not an option (`node x.mjs`,
# `python3 -u x.py`, `npx tsx x.ts`, `deno run x.ts`). Every other file the command names is data it was given.
INTERPRETERS = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|node|nodejs|bash|sh|zsh|dash|ksh|fish|deno|bun|ruby|perl|php|lua|Rscript|tsx|ts-node(?:-esm)?|npx|bunx|pnpx|uv)$")
RUNNER_WORDS = ("run", "x", "exec", "dlx", "tsx", "ts-node", "ts-node-esm")   # `npx tsx F`, `deno run F`, `bun run F`, `uv run F`: the word before the program
INLINE_CODE = ("-c", "-e", "--eval", "-p", "--print", "-m")   # `python3 -c CODE`, `node -e CODE`, `python3 -m MOD`: no program file

# What looks like secrets — a file's name, or text in it, in the command or in what it answered. guin-site 10-16:
# `did lexicon-publish -- node <scratch>/publish_lexicons.mjs ./lexicons/… <the PDS's .dev.vars> --write` kept the
# data argument `.dev.vars` whole in `did[0].outside[1].content`, and the record was committed: a secrets file in history.
SECRET_NAME = re.compile(r"^(?:\.env(?:\..+)?|\.dev\.vars(?:\..+)?|\.netrc|\.npmrc|\.pypirc|id_(?:rsa|dsa|ecdsa|ed25519).*|.*\.(?:pem|key|p12|pfx|jks|keystore)"
                         r"|.*(?:key|secret|token|credential|password|passwd).*)$", re.I)
SECRET_WORD = r"[A-Za-z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|PASSWD|PRIVATE|CREDENTIAL)[A-Za-z0-9_]*"
SECRET_ASSIGN = re.compile(r"(?m)(?<![\w.])((?:export\s+)?%s\s*[=:]\s*)(?!<masked>)(\"[^\"\n]+\"|'[^'\n]+'|[^\s\"'#;,]+)" % SECRET_WORD)
SECRET_TOKENS = [re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),
                 re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
                 re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), re.compile(r"\bAKIA[0-9A-Z]{16}\b")]
SECRET_OPTION = re.compile(r"^--?[\w-]*(?:token|secret|password|passwd|api-?key|private-?key|credential)s?$", re.I)


def looks_secret_name(name):
    return bool(SECRET_NAME.match(os.path.basename(str(name))))


def is_secret_value(v):
    """A value that names where a secret comes from (`$X`, `process.env.X`, `os.environ[...]`) is not one."""
    v = v.strip("\"'")
    return len(v) >= 6 and not re.match(r"^(?:\$|process\.env|os\.environ|os\.getenv|getenv|env\(|Deno\.env|<)", v)


def looks_secret_text(text):
    """Does this text hold what reads as a secret: `NAME=value` where NAME says TOKEN, SECRET, KEY, PASSWORD or PRIVATE, a private
    key block, or a known token's shape (ghp_, sk-, xoxb-, AKIA…)?"""
    text = str(text)
    return any(is_secret_value(m.group(2)) for m in SECRET_ASSIGN.finditer(text)) or any(p.search(text) for p in SECRET_TOKENS)


def mask_secrets(text):
    """(text with every secret-looking value replaced by `<masked>`, how many were). `NAME=value` keeps its name."""
    n = [0]

    def assign(m):
        if not is_secret_value(m.group(2)):
            return m.group(0)
        n[0] += 1
        return m.group(1) + "<masked>"

    def token(m):
        n[0] += 1
        return "<masked>"
    text = SECRET_ASSIGN.sub(assign, str(text))
    for p in SECRET_TOKENS:
        text = p.sub(token, text)
    return text, n[0]


def mask_argv(argv):
    """(argv with secret-looking values masked, how many were): an argument's own text, and the value after an option named
    for a secret (`--token VALUE`)."""
    out, n = [], 0
    for i, a in enumerate(argv):
        if i and SECRET_OPTION.match(str(argv[i - 1])) and not str(a).startswith("-") and is_secret_value(str(a)):
            out.append("<masked>")
            n += 1
            continue
        a, k = mask_secrets(a)
        out.append(a)
        n += k
    return out, n


def program_arg(target, argv):
    """The index of the argument that is the program this command runs, or None: argv[0] when it is itself a script (`#!`), else
    the first argument after an interpreter that is not an option (`node x.mjs data.json` -> 1; `npx tsx x.ts` -> 2). Inline
    code (`python3 -c …`, `node -e …`) or a module (`-m`) runs no file."""
    if not argv:
        return None
    first = os.path.join(target, argv[0])
    if os.path.isfile(first):
        try:
            if io.open(first, "rb").read(2) == b"#!":
                return 0
        except OSError:
            pass
    if not INTERPRETERS.match(os.path.basename(str(argv[0]))):
        return None
    for i in range(1, len(argv)):
        a = str(argv[i])
        if a in INLINE_CODE:
            return None
        if a.startswith("-"):
            continue
        if a in RUNNER_WORDS and not os.path.isfile(os.path.join(target, a)):
            continue
        return i
    return None


def outside_argv(target, argv):
    """(argv as the record writes it, [the files outside the project it names]). An argument that is a file outside the project —
    a script in a scratchpad, `python3 /private/tmp/…/empty_r2.py` — becomes `<outside:empty_r2.py>`, and the record keeps the
    file itself: its sha256, its size, and — for the program the command runs only — its text when it is text and small (paths
    of this machine taken out). guin-site run-20261012-052255-3556 kept only the machine path, and the script that emptied the
    R2 bucket is gone. Every other file the command names is data it was given (`role: argument`): its sha256 and size, never
    its text — guin-site 10-16 kept a secrets file passed to a publishing script whole, and committed it. Neither is kept, even
    the program, when the file's name or text looks like secrets. The program itself (argv[0], found on PATH or an
    interpreter) counts only when it is a script: `#!` text. Everything else is written portably (the project `.`, the home `~`)."""
    import hashlib
    root = os.path.realpath(target)
    prog = program_arg(target, argv)
    shown, outside = [], []
    for i, a in enumerate(argv):
        full = os.path.realpath(os.path.join(target, a))
        if not (os.path.isfile(full) and not (full + os.sep).startswith(root + os.sep)):
            shown.append(neutral_path(a, target))
            continue
        raw = io.open(full, "rb").read()
        if i == 0 and not raw.startswith(b"#!"):
            shown.append(neutral_path(a, target))   # an interpreter or a binary: the command, not a script it ran
            continue
        marker = neutral_path(a, target)
        if not marker.startswith("<plugin:"):
            marker = "<outside:%s>" % os.path.basename(full)
        rec = {"arg": i, "name": os.path.basename(full), "role": "program" if i == prog else "argument",
               "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if marker.startswith("<plugin:"):
            rec["content"] = None   # an installed plugin's file: its version names it
        elif looks_secret_name(full) or (text is not None and looks_secret_text(text)):
            rec["content"] = None
            rec["not-kept"] = "looks like secrets"
        elif i != prog:
            rec["content"] = None
            rec["not-kept"] = "an argument, not the program"
        elif text is None or "\0" in text:
            rec["content"] = None
            rec["not-kept"] = "not text"
        elif len(raw) > DID_CONTENT_CAP:
            rec["content"] = None
            rec["not-kept"] = "over %d bytes" % DID_CONTENT_CAP
        else:
            rec["content"] = neutral_path(text, target)
            if rec["content"] != text:
                rec["content-portable"] = True   # this machine's paths taken out of it: the sha256 is the file's as it ran
        if rec.get("content") is None:
            rec.pop("content")
        shown.append(marker)
        outside.append(rec)
    return shown, outside


def masked_text(m):
    """What `did` masked, for a reader."""
    return "masked in the record (looked like secrets): %s" % ", ".join("%d value(s) in the %s" % (v, "command line" if k == "command" else "output's end") for k, v in sorted(m.items()))


def outside_what(o):
    """Which file outside the project this was, for a reader: the program the command ran, or a file it was given."""
    return {"program": "the program it ran (%s)", "argument": "a file it was given as an argument (%s)"}.get(o.get("role"), "a file it named (%s)") % o.get("name")


def outside_text(o):
    """What the record keeps of a file outside the project, for a reader."""
    return "sha256 %s…, %d bytes, %s" % (o.get("sha256", "")[:12], o.get("size", 0),
                                         "its content kept in the record" if "content" in o else "content not kept: %s" % (o.get("not-kept") or "an installed plugin's file"))


CHATTER = (re.compile(r"^[\s\-=_~*#.·─━═┄┈╌▔▁│┃|+]{3,}$"),   # a rule: ─────, =====, ----
           re.compile(r"^\W{0,4}\s*[A-Za-z][\w.-]* v?\d+(?:\.\d+)+(?:\s*\((?:update available|latest)[^)]*\))?\s*$", re.I))   # a tool's banner: ⛅️ wrangler 4.143.1 (update available 4.149.0)


def kept_tail(said, n=6):
    """An output's last n meaningful lines: blank lines, rules and a tool's version banner are not what it answered —
    guin-site kept "⛅️ wrangler 4.143.1 (update available 4.149.0)" and a row of ─ as half of a deletion's tail."""
    lines = [l.rstrip() for l in str(said).strip().split("\n")]
    meant = [l for l in lines if l.strip() and not any(p.match(l.strip()) for p in CHATTER)]
    return (meant or lines)[-n:]


def short_command(cmd, n=100):
    """A command for a commit's subject: whole when it fits, else cut at argument boundaries — its first word, as many of the
    others as fit (in order, `…` where some were left out) and its last word, a long path shortened to its basename. Never
    inside a word: `[:120]` cut "…/scratchpad/empty_r2.py" to "…/scratchpad/empty", and f3beee0's subject ended
    `'<outsi… --write -> exit 0`, a `<outside:…>` marker cut in half."""
    cmd = " ".join(str(cmd).split())
    if len(cmd) <= n:
        return cmd
    try:
        words = [shlex.quote(w) for w in shlex.split(cmd)]
    except ValueError:
        words = cmd.split(" ")

    def short(w):
        if len(w) <= n // 2:
            return w
        bare = w.strip("'\"")
        base = bare.rstrip("/").rsplit("/", 1)[-1] if "/" in bare else bare
        base = shlex.quote(base)
        return base if len(base) <= n // 2 else "…" + base[-(n // 2 - 1):]
    if len(words) == 1:
        return short(words[0])
    first, last = short(words[0]), short(words[-1])
    budget = n - len(first) - len(last) - 3   # the spaces around a `…`
    kept = [first]
    for w in words[1:-1]:
        if len(w) + 1 > budget:
            break   # one gap, after as much of the head as fits: what is left out is in the record
        kept.append(w)
        budget -= len(w) + 1
    if len(kept) < len(words) - 1 or last != words[-1]:
        kept.append("…")
    return " ".join(kept + [last])


def short_join(items, n):
    """`; `-joined items in at most n characters, whole items only: the rest counted, never cut inside one."""
    out = []
    for i, x in enumerate(items):
        rest = len(items) - i - 1
        if out and len("; ".join(out + [x])) + (len(" (and %d more)" % rest) if rest else 0) > n:
            return "; ".join(out) + " (and %d more)" % (len(items) - i)
        out.append(x)
    return "; ".join(out)


def take_over(target, d, state, task, ts, why, who, extra=None, checked=None):
    """The task becomes the session's: self-performed instead of its role, with the reason; a stopped attempt (and who made
    it) stays in `attempts`. `take` is a person's or the session's word; chongdae takes a task itself when a member's
    sandbox lacked a capability and the lock has no alternate that can (`extra`: how it was decided)."""
    tid = task["id"]
    taken = {"from": task["role"], "why": why, "by": who, **(extra or {}), **stamp()}
    ts["taken"] = taken
    ts["self-performed"] = {"instead-of": task["role"], "why": why, "by": who, "taken-over": True, **stamp()}
    for key in ("touched_by_provider", "checks-ran-overruled", "accepted"):
        ts.pop(key, None)
    was = ts.pop("performed_by", None)   # who made the stopped attempt goes with that attempt; the task's hands are the session's now
    ts.setdefault("non-claims", []).append("%s: taken over by the session from %s: %s" % (tid, task["role"], why))
    if ts.get("response") or ts.get("rejected"):
        n = resend(target, d, state, tid, {"by": who, "taken": why}, message="take %s: %s" % (tid, why), checked=checked)
        if was:
            ts["attempts"][-1]["performed_by"] = was
            save_state(d, state)
        return "took %s from %s — its attempt %d stays in the record; the session finishes it, then `chongdae run` decides it" % (tid, task["role"], n)
    if checked:
        ts.pop("checked", None)
        ts["checked"] = checked
    save_state(d, state)
    commit_record(target, os.path.basename(d), "take %s: %s" % (tid, why))
    return "took %s from %s — the session does it; then `chongdae run` decides it" % (tid, task["role"])


def cmd_drop(args):
    """A session task that will not be done — mis-specified, superseded, abandoned — leaves the open set with its reason, and
    stays in the record as `dropped`. Without this the cheap way out of a task was to close the run around it (or start a
    new run), which left it open forever and nobody looking; a drop is a decision, written down."""
    d = run_dir(args.target)
    plan, state = (load_plan(d), load_state(d)) if d else ({}, {})
    if plan.get("kind") != "session" or state.get("status") != "running":
        raise SystemExit("no session run in progress — only a session run's own tasks can be dropped; a plan's tasks are the plan's")
    ts = state["tasks"].get(args.task)
    if not ts:
        raise SystemExit("no task %s" % args.task)
    if ts["status"] in ("done", "skipped", "dropped"):
        raise SystemExit("%s is %s — nothing to drop" % (args.task, ts["status"]))
    leases = lease_backend(args.target)
    if leases:
        try:
            held = leases.current(task_key(os.path.basename(d), args.task))
        except LeaseError as err:
            raise SystemExit("drop: the lease store cannot be reached (%s) — nothing dropped" % err)
        if held and not lapsed(held) and not same_holder(held.get("holder"), lease_holder(args.target)):
            raise SystemExit("%s is held by another session — wait for release or explicitly `claim --break %s --why WHY` before taking or dropping it" % (args.task, args.task))
    try:
        local_owner = local_owner_blocks(args.target, d, args.task, ts, leases)
    except LeaseError as err:
        raise SystemExit("drop: the lease store cannot be reached (%s) — nothing dropped" % err)
    if local_owner:
        raise SystemExit("%s belongs to another session (or this call has no session identity) — use `chongdae take %s --why WHY` for an idle task's handover before dropping it" % (args.task, args.task))
    elif not leases and ts.get("claimed_by") and claim_owner(ts["claimed_by"]) != me(args.target):
        raise SystemExit("%s is claimed by %s — its owner must release it before it can be dropped" % (args.task, signer_text(ts["claimed_by"])))
    native = []
    for tag in task_in_flight(d, args.task):
        pending = load(work_path(d, tag + ".pending.json"))
        if pending_alive(work_path(d, tag + ".pending.json"), pending):
            raise SystemExit("%s still has a running process (%s) — wait for it to stop before dropping; nothing was cancelled or dropped" % (args.task, tag))
        if pending.get("native"):
            native.append(tag)   # dropping asserts the session has cancelled its host agent; the engine cannot observe that agent
    if ts.get("response") and (ts["response"].get("status") == "done" or measured(args.target, ts)):
        print("note: %s's hands changed the tree — if that work stands, `chongdae take %s --why` finishes it as done work instead" % (args.task, args.task))
    ts["status"] = "dropped"
    ts["dropped"] = {"why": args.why, "by": signer(args), **stamp()}
    if native:
        ts["dropped"]["native-dispatches-retired"] = native
    ts["touched"] = scoped_measure(args.target, plan, state, args.task, ts, providers(args.target, plan))[0]   # what changed in its window stays attributed to it, dropped or not (open tasks' scopes say whose)
    ts.setdefault("non-claims", []).append("dropped, not done: %s" % args.why)
    release_result(args.target, d, args.task, ts)
    save_state(d, state)
    for tag in native:
        os.remove(work_path(d, tag + ".pending.json"))   # request/asked evidence stays; no other task's pending job is touched
    commit_record(args.target, os.path.basename(d), "drop %s: %s" % (args.task, args.why))
    print("dropped %s: %s" % (args.task, args.why))
    if native:
        print("  retired native dispatch %s on the session's word that its host agent was cancelled; request evidence kept" % ", ".join(native))
    return 0


def cmd_unstage(args):
    """A role hired before or after a task that cannot do its work here — a newbie on a project with nothing a newbie can
    run, say — comes off that task, with the reason. The task goes on without it; the record says the role did not look
    (a non-claim), and what it answered before it came off stays under `stages-taken-off`. Other tasks keep the role."""
    d = run_dir(args.target)
    if not d:
        raise SystemExit("no run")
    plan, state = load_plan(d), load_state(d)
    ts = state["tasks"].get(args.task)
    task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), None)
    if not ts or not task:
        raise SystemExit("no task %s" % args.task)
    if args.role not in stage_roles(plan, task, "before") + stage_roles(plan, task, "after"):
        raise SystemExit("%s is not hired before or after %s" % (args.role, args.task))
    ts.setdefault("unstaged", {})[args.role] = {"why": args.why, "by": signer(args), **stamp()}
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
    """A person takes a task. chongdae does not assign; `run` on other machines skips what is claimed here. Under a `lease`
    setting the claim is a hold in the lease store, not a line in the record (claim_lease)."""
    leases = lease_backend(args.target)
    if leases:
        return claim_lease(args, leases)
    if args.brk or args.prune:
        raise SystemExit("--%s needs a lease: settings.chongdae.lease (\"local\", \"git\" or a command) — without one a claim is a line in the record; "
                         "`claim TASK --release` (or `--by \"\"`) releases it" % ("break" if args.brk else "prune"))
    code = None if args.list else remote_before(args.target, "`chongdae claim`")
    if code is not None:
        return code
    d = run_dir(args.target)
    if not d:
        raise SystemExit("no run")
    state = load_state(d)
    if args.list:
        plan = load_plan(d)
        rows = [(t["id"], state["tasks"].get(t["id"], {})) for t in all_tasks(plan, state)]
        rows = [(tid, ts) for tid, ts in rows if ts.get("claimed_by")]
        for tid, ts in rows:
            print("%s  claimed by %s  (%s; in the record — no lease setting)" % (tid, signer_text(ts["claimed_by"]), ts.get("status", "?")))
        if not rows:
            print("no task of %s is claimed (claims are written in the record: no lease setting)" % os.path.basename(d))
        return 0
    if not args.task:
        raise SystemExit("claim TASK, or claim --list")
    ts = state["tasks"].get(args.task)
    if not ts:
        raise SystemExit("no task %s" % args.task)
    # a claim says which machine advances the task (`run` compares it with this machine's user) and who decided it: a
    # person's `--by NAME`, else the session — on this machine, signed as itself, not with the owner's name
    releasing = args.release or args.by == ""
    who = None if releasing else args.by if args.by is not None else {**agent_signer(args.target), "machine": me(args.target)}
    owner = me(args.target) if releasing else claim_owner(who)
    if ts.get("claimed_by") and claim_owner(ts["claimed_by"]) != owner:
        raise SystemExit("%s is claimed by %s — they release it (claim --by \"\") or you agree with them, not with chongdae" % (args.task, signer_text(ts["claimed_by"])))
    ts["claimed_by"] = who or None
    save_state(d, state)
    print("%s claimed by %s" % (args.task, signer_text(who)) if who else "%s released" % args.task)
    return 0


def claim_lease(args, leases):
    """`claim TASK` takes a hold for this session (one at a time by default: `lease-max`); `claim --list` shows every hold with
    its age and last progress, lapsed and long-held ones marked; `claim --break TASK --why` takes over a live hold — a
    judgment, recorded on the task and committed; the old holder is told at its next renewal; `claim TASK --release` (or
    `--by ""`) gives a hold back. Done, drop and close give holds back on their own."""
    target = args.target
    try:
        if args.list:
            if args.prune:
                gone = leases.prune(leases.ceiling)
                print("pruned %d released marker(s) older than lease-ceiling%s — a take of those keys now counts its generation from the record"
                      % (len(gone), ": " + ", ".join(gone) if gone else ""))
            now, rows = clock(), leases.list()
            if not rows:
                print("no hold in the lease store (%s)" % leases.kind)
                return 0
            for l in sorted(rows, key=lambda l: l.get("key", "")):
                marks = [m for m, on in (("lapsed", lapsed(l, now)), ("long-held", long_held(l, leases.ceiling, now))) if on]
                print("%s  %s  gen %s  %s%s%s" % (l.get("scope") and "scope %s (%s)" % (l["scope"] or ".", l.get("task")) or l.get("task") or l.get("key"),
                                                 holder_text(l.get("holder")), l.get("gen"), lease_age(l, now),
                                                 "  [%s]" % ", ".join(marks) if marks else "", "  — " + lease_from_text(l["from"]) if l.get("from") else ""))
            return 0
        if not args.task:
            raise SystemExit("claim TASK, claim --list, or claim --break TASK --why WHY")
        code = remote_before(target, "`chongdae claim`")
        if code is not None:
            return code
        d = run_dir(target)
        if not d:
            raise SystemExit("no run")
        plan, state = load_plan(d), load_state(d)
        ts = state["tasks"].get(args.task)
        task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), None)
        if not ts or not task:
            raise SystemExit("no task %s" % args.task)
        run_name, key = os.path.basename(d), task_key(os.path.basename(d), args.task)
        holder = lease_holder(target, by=args.by or None)
        cur = leases.current(key)
        if args.release or args.by == "":
            held = ts.get("lease-held")
            if not (cur and same_holder(cur.get("holder"), holder)):
                raise SystemExit("%s: this session holds no lease on it%s" % (args.task, " (%s does)" % holder_text(cur.get("holder")) if cur else ""))
            ts["lease-held"] = held or {"gen": cur["gen"], "holder": holder, "scopes": []}
            release_task(leases, run_name, args.task, ts)
            save_state(d, state)
            print("%s released (gen %s)" % (args.task, cur["gen"]))
            return 0
        if ts.get("status") in CLOSED:
            raise SystemExit("%s is %s — nothing to hold" % (args.task, ts["status"]))
        if args.brk:
            if not args.why:
                raise SystemExit("--break takes over someone's live hold: say why (--why) — it is recorded and they are told")
            if not cur:
                raise SystemExit("%s is not held — `claim %s` takes it" % (args.task, args.task))
            if same_holder(cur.get("holder"), holder):
                raise SystemExit("%s is this session's already (gen %s)" % (args.task, cur.get("gen")))
            was_long, was_lapsed = long_held(cur, leases.ceiling), lapsed(cur)
            r = take_task(leases, run_name, task, ts, holder, over=cur.get("gen"), why=args.why)
            if not r["ok"]:
                raise SystemExit("%s: the hold changed while it was broken (%s holds it at gen %s) — `claim --list`, then again"
                                 % (args.task, holder_text((r.get("lease") or {}).get("holder")), (r.get("lease") or {}).get("gen")))
            ts.setdefault("lease-breaks", []).append({"from": cur.get("holder"), "gen": cur.get("gen"), "to-gen": r["lease"]["gen"], "why": args.why,
                                                      "by": signer(args), **({"long-held": True} if was_long else {}), **({"lapsed": True} if was_lapsed else {}), **stamp()})
            save_state(d, state)
            commit_record(target, run_name, "break the hold on %s: %s" % (args.task, args.why))
            print("broke %s's hold on %s (gen %s -> %s): %s — recorded; they are told at their next renewal, and a result made under gen %s is not accepted"
                  % (holder_text(cur.get("holder")), args.task, cur.get("gen"), r["lease"]["gen"], args.why, cur.get("gen")))
            return 0
        if cur and same_holder(cur.get("holder"), holder) and not args.by:
            if not ts.get("lease-held"):
                take_task(leases, run_name, task, ts, holder)
                save_state(d, state)
            print("%s is this session's already (gen %s, %s)" % (args.task, cur.get("gen"), lease_age(cur)))
            return 0
        mine = [l for l in live_holds(leases, holder) if l.get("key") != key]
        if len(mine) >= leases.max:
            raise SystemExit("this session holds %s already (settings.chongdae.lease-max: %d) — finish or give one back (`claim TASK --release`) first"
                             % (", ".join(l.get("task") or l["key"] for l in mine), leases.max))
        r = take_task(leases, run_name, task, ts, holder)
        if not r["ok"]:
            who = r.get("lease") or {}
            ready = [t["id"] for t in all_tasks(plan, state) if t["id"] != args.task and state["tasks"].get(t["id"], {}).get("status") not in CLOSED
                     and all(state["tasks"].get(n, {}).get("status") == "done" for n in t.get("needs", []))
                     and not (lambda c: c and not lapsed(c))(leases.current(task_key(run_name, t["id"])))]
            print("%s: %s%s" % (args.task, "its scope overlaps %s, held by %s for %s" % (who.get("scope") or who.get("key"), holder_text(who.get("holder")), who.get("task"))
                                if r.get("conflict") == "scope" else "held by %s (gen %s, %s)" % (holder_text(who.get("holder")), who.get("gen"), lease_age(who)),
                                " — ready and unheld: %s (`chongdae run` takes the next one)" % ", ".join(ready) if ready else " — no other task is ready and unheld"))
            return 1
        save_state(d, state)
        lease = r["lease"]
        print("%s claimed by %s (gen %s)%s" % (args.task, holder_text(holder), lease["gen"], " — " + lease_from_text(lease.get("from")) if lease.get("from") else ""))
        return 0
    except LeaseError as err:
        print("decision: the lease store cannot be reached (%s) — this machine cannot take a task; nothing was started untaken" % err)
        return DECISION


def close_busy(target, d, plan, state):
    """A close cannot end the shared container while another session or dispatched hands still use it. Unlike
    uncommitted work, `--anyway` cannot dispose of somebody else's ongoing work or cancel a running process."""
    busy = []
    leases = lease_backend(target)
    if leases:
        try:
            holder = lease_holder(target)
            for held in leases.list(ref_part(os.path.basename(d)) + "/"):
                if not lapsed(held) and not same_holder(held.get("holder"), holder):
                    busy.append("%s is held by %s — wait for its holder to finish or release it" % (held.get("key"), holder_text(held.get("holder"))))
        except LeaseError as err:
            busy.append("the lease store cannot be reached (%s); whether another session is working cannot be established" % err)
    declared = providers(target, plan)
    for task in all_tasks(plan, state):
        tid, ts = task["id"], state["tasks"][task["id"]]
        pending_operation = operation_pending(d, tid)
        if pending_operation:
            busy.append("%s has interrupted operation %s — `chongdae did %s` recovers observed results without repetition; reconcile any unknown outcome before closing" %
                        (tid, pending_operation["id"], tid))
        active = task_in_flight(d, tid)
        if active:
            busy.append("%s has running or unanswered dispatched work (%s) — finish the dispatch and `chongdae run %s` to consume it" % (tid, ", ".join(active), tid))
        if ts.get("status") in CLOSED:
            continue
        try:
            local_owner = local_owner_blocks(target, d, tid, ts, leases)
        except LeaseError as err:
            busy.append("%s: the lease store cannot be reached (%s); ownership cannot be established" % (tid, err))
            local_owner = False
        if local_owner:
            busy.append("%s is unfinished and owned by another session (or this call has no session identity) — let its owner finish, "
                        "or use `chongdae take %s --why WHY` for an explicit handover once its hands have stopped" % (tid, tid))
        elif not leases and ts.get("claimed_by") and claim_owner(ts["claimed_by"]) != me(target):
            busy.append("%s is unfinished and claimed by %s — its owner must finish or release it" % (tid, signer_text(ts["claimed_by"])))
        if not ts.get("taken") and hire(declared, task)[1] == "subagent":
            busy.append("%s is an unfinished sub-agent task — wait for its hand-back, then `chongdae run %s`; if cancelled, stop its hands "
                        "before `chongdae drop %s --why WHY`" % (tid, tid, tid))
    return busy


def cmd_close(args):
    """A session run ends. Open tasks stay in the record as open; nothing is decided for them.
    A worktree run also merges back: commit the worktree, merge into main — clean merge + green recheck ends the run;
    a conflict or a red recheck leaves the branch for a merge run (`init --merge` in main). The worktree is removed
    only when the merge landed; otherwise it stays, and the record says why."""
    d = run_dir(args.target, getattr(args, "run", None))
    plan, state = (load_plan(d), load_state(d)) if d else ({}, {})
    wt = state.get("worktree")
    if plan.get("kind") != "session":
        # a plan/bootstrap run in a worktree ends by `run` (complete); `close` is then its way back to main
        if not (wt and state.get("status") == "complete"):
            raise SystemExit("no session run in progress" + (" — this %s run is %s; `chongdae run` completes it, then `close` merges its worktree back" % (plan.get("kind"), state.get("status")) if wt else ""))
        refused = parent_refusal(args.target, state)
        if refused:
            raise SystemExit("not merged back: " + refused)
        return merge_back(args.target, wt, os.path.basename(d))
    if state.get("status") != "running":
        raise SystemExit("no session run in progress")
    busy = close_busy(args.target, d, plan, state)
    if busy:
        return stop("session agent: this run still has other owners or active hands — it stays open; `--anyway` cannot end their work", *busy)
    refused = parent_refusal(args.target, state)
    if refused:
        raise SystemExit("not closed: " + refused)
    anyway = getattr(args, "anyway", False)
    if anyway and not getattr(args, "why", None):
        raise SystemExit("close --anyway needs --why: what stands when the run closes is recorded with the reason")
    open_ = open_tasks(plan, state)
    # the run's own work, not committed: a worktree run's merge-back commits its worktree; in a shared tree the work is the
    # session's to commit, and a close that leaves it uncommitted closes on work no commit holds. guin-site
    # run-20261012-052255-3556 closed with plan/ATPROTO.md — cleanup-ops' scope and `touched` — edited and uncommitted
    loose = {} if wt else uncommitted_work(args.target, plan, state)
    if loose and not anyway:
        files = sorted(loose)
        return stop("session agent: this run's work is not committed — %s. Commit it a task at a time, as the lines above say (the subject "
                    "`%s/<task> (session): …` — `%s: …` is chongdae's own record commits), then `chongdae close`; "
                    "or `chongdae close --anyway --why WHY` closes with it uncommitted (recorded)"
                    % ("; ".join("%s (%s)" % (f, ", ".join(loose[f])) for f in files), os.path.basename(d), os.path.basename(d)),
                    *work_commit_lines(os.path.basename(d), plan, state, loose, args.target))
    state["status"] = "complete"   # which tasks stayed open is the tasks' own status; `report`/`status` recount it, nothing read a copy
    state["ended"] = stamp()
    save_state(d, state)
    # the reviewer reads the run ended — before the close is final: what it finds that the tree can answer stops the close
    # here, for the session, instead of arriving after it (guin-site run-20261012-052255-3556: two cq-failed came with the
    # close commit and were fixed outside any run)
    before, said_before = dirty(args.target, records_too=True) or {}, list(state.get("non-claims") or [])
    wrote = place_reviewer(args.target, d, state, plan)
    standing = fixable_findings(args.target, wrote)
    if standing and not anyway:
        took_back = take_back_review(args.target, wrote, before)
        state["status"] = "running"
        for k in ("ended", "reviewed"):
            state.pop(k, None)
        state["non-claims"] = said_before
        save_state(d, state)
        return stop("session agent: the reviewer found %d objection(s) this tree can answer (%s) — fix each, then `chongdae close` again "
                    "(the run stays open%s); or `chongdae close --anyway --why WHY` closes with them standing (recorded)"
                    % (len(review_distinct(standing)), review_count(standing), "; what the reviewer wrote for this close was taken back" if took_back else ""),
                    *("%s @ %s: %s" % (review_kind(f), f.get("where"), f.get("text")) for f in standing))
    if anyway:
        state["closed-anyway"] = {"why": args.why, "by": signer(args), **({"uncommitted": sorted(loose)} if loose else {}),
                                  **({"standing": [{k: f.get(k) for k in ("kind", "where", "text")} for f in standing]} if standing else {}), **stamp()}
        if loose or standing:
            state.setdefault("non-claims", []).append("closed with %s standing (`close --anyway`): %s" % (
                " and ".join(x for x in ("%d uncommitted file(s) of its work (%s)" % (len(loose), ", ".join(sorted(loose))) if loose else "",
                                         "%d reviewer objection(s) the tree could answer (%s)" % (len(review_distinct(standing)), review_count(standing)) if standing else "") if x), args.why))
    for tid, ts in state["tasks"].items():
        if ts.get("lease-held"):
            release_result(args.target, d, tid, ts, only_mine=True)   # the run ends: what this session held goes back
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "close — %s (%d done, %d open)" % (plan.get("goal", ""), sum(ts["status"] == "done" for ts in state["tasks"].values()), len(open_)), also=wrote)
    dropped = [tid for tid, ts in state["tasks"].items() if ts["status"] == "dropped"]
    said = said_last_run(args.target, d, state)
    print("closed %s: %d task(s) done, %d open (%s)%s. non-claims: %s" % (os.path.basename(d), sum(ts["status"] == "done" for ts in state["tasks"].values()), len(open_), ", ".join(open_) or "-",
                                                                 ", %d dropped (%s)" % (len(dropped), ", ".join(dropped)) if dropped else "", [n for n in non_claims(state) if n not in said] or "none"))
    line = None if wt else upstream_line(args.target)
    if line:
        print("  " + line)   # read from the last fetch: closing is when unpushed work is still in mind
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
    plan = load_plan(d)
    task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), ts.get("def") or {"id": args.task})
    code = produced_freshness({"target": args.target, "d": d, "plan": plan, "state": state}, task, ts)
    if code is not None:
        return code
    refused = result_gen_refusal(args.target, d, args.task, ts)
    if refused:
        raise SystemExit("%s: %s" % (args.task, refused))
    verdict = verdict_of(ts)   # a reject every finding of which chongdae overruled went on as accepted
    if args.delegated and gate_of(task).get("delegate") == "after-verifier" and verdict != "accept":
        raise SystemExit("%s: this gate delegates only after a verifier accepts (verdict: %s) — a person must read it, or the plan must say otherwise" % (args.task, verdict or "none"))
    # Delegation is recorded with what stood in for the reader: a verifier's accept, or nothing. The reviewer counts the two apart.
    ts["confirmed"] = {**({"by": args.by} if args.by else {**delegation_record(d, args.delegated, "confirm"), "verifier": verdict}), **stamp()}
    ts["status"] = "done"
    ts["done"] = {k: ts["confirmed"][k] for k in ("at", "chongdae")}   # the confirmation is the moment it became done
    release_result(args.target, d, args.task, ts)
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
    # not a gate: a retry the session decides alone is signed by the session (`--by NAME` when a person decided it)
    judgment = delegation_record(d, args.delegated, "retry") if args.delegated else {"by": signer(args)}
    plan, to = load_plan(d), ""
    checked = run_checked(args.target, args.checked, args.checked_red) if (args.checked or args.checked_red) else None   # before anything is recorded: a failing one refuses the retry
    if args.requires:
        # what the work requires of its sandbox, said on the task now that a member's sandbox lacked it: the request names it
        # (`needs`), and the lock's `<role>@<cap>` alternate, when it has one, is hired instead of the plain role
        task = ts["def"] if "def" in ts else next((t for t in plan.get("tasks", []) if t.get("id") == args.task), None)
        if task is None:
            raise SystemExit("no task %s in the plan" % args.task)
        task["requires"] = list(dict.fromkeys(list(task.get("requires") or []) + list(args.requires)))
        judgment["requires"] = task["requires"]
        if "def" not in ts:
            save_state(d, state, plan=plan)
        key, who = hire(providers(args.target, plan), task)
        if ts.get("taken") and key != task["role"] and who not in SESSION_HANDS:
            # asking for a capability the lock's alternate has is asking for that hand: a take stood in its way, and `run`
            # kept the task with the session while this line said the alternate does it (guin-site write-bsky-build,
            # 2026-10-10: two "evidence only" retries the session then did itself). The take stays in the record, lifted.
            judgment["untaken"] = ts.pop("taken")
            ts.pop("self-performed", None)
            # what the take said and ran was the session's: the alternate's verifier gets neither
            ts["non-claims"] = [n for n in ts.get("non-claims", []) if not str(n).startswith("%s: taken over by the session from " % args.task)]
            ts.pop("checked", None)
        to = " — it requires %s now; %s" % (", ".join(task["requires"]), "the session took it (`take`), so the session does it again" if ts.get("taken")
                                             else "the lock's %s does it" % key if key != task["role"]
                                             else "the lock has no %s@%s, so the plain %s does it again" % (task["role"], "+".join(task["requires"]), task["role"]))
    elif ts.get("taken"):
        to = " — the session took it (`take`), so the session does it again"
    # a session task is measured again here, and what the measure leaves out is said: a retry that resends the same empty
    # diff gets the same reject (guin-site's escape-build, rejected on every retry for a `touched: []` beside the work)
    tdef = ts["def"] if "def" in ts else next((t for t in plan.get("tasks", []) if t.get("id") == args.task), {})
    lines = []
    if isinstance(ts.get("start"), dict) and session_tree(providers(args.target, plan), tdef, ts):
        m, said, _ = scoped_measure(args.target, plan, state, args.task, ts, providers(args.target, plan))
        judgment["measured"] = m
        lines += ["note: " + x for x in said]
        lines.append("measured now: %s — what the next judgment counts as %s's" % (", ".join(m or []) or "nothing", args.task))
        for f in held_at_start(args.target, tdef, ts):
            by = (ts.get("pinned") or {}).get(f)
            lines.append("%s: %s, and %s's %s names it — not in its measure. If it is this task's work: `chongdae adopt %s %s --why WHY`"
                         % (f, "pinned into its start when %s finished (counted as %s's)" % (by, by) if by else "already changed when %s was added (its start holds it)" % args.task,
                            args.task, "tests" if f in (tdef.get("tests") or []) else "brief", args.task, f))
        lines += contested_lines(args.task, contested(args.target, plan, state, args.task, m or []), plan, state)
    if checked:
        judgment["checked"] = [r["command"] for r in checked["ran"]]
    n = resend(args.target, d, state, args.task, judgment, checked=checked)
    print("retry %s: attempt %d kept in the record%s; `chongdae run` sends the task out again with it attached" % (args.task, n, to))
    if checked:
        print("  checked by chongdae: %s — the verifier gets them as evidence chongdae saw" % checked_text(checked))
    for line in lines:
        print("  " + line)
    return 0


def cmd_dispute(args):
    """The session (or a person) says some of a build's protected tests contradict the contract — the route a provider's
    build has in its answer's `disputed-tests`. guin-site, 2026-10-02: a session build found two test errors and a parser
    the machine could not load; every judgment of the build restored the tests, so the fix could not land, and a fix task
    added with `--tests` protected the very files it fixed. Recorded as a judgment; the task that wrote those tests is
    reopened with the dispute (or a tests task is made when none is on record), and once it is done the build takes the
    amended files as its contract, so its next judgment keeps the fix."""
    d = run_dir(args.target)
    plan, state = (load_plan(d), load_state(d)) if d else ({}, {})
    if state.get("status") != "running":
        raise SystemExit("no run in progress")
    ts = state["tasks"].get(args.task)
    task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), None)
    if not ts or not task:
        raise SystemExit("no task %s" % args.task)
    if ts["status"] != "todo":
        raise SystemExit("%s is %s — a dispute is about the contract of an open build" % (args.task, ts["status"]))
    protected = list(task.get("tests") or []) if not writes_tests(task) else []
    files = []
    for f in args.tests:
        f = f.replace("\\", "/").strip()
        while f.startswith("./"):
            f = f[2:]
        files.append(f.split("::")[0])
    stray = [f for f in files if f not in protected]
    if stray:
        # refused, with the next step: a test no build protects is not a contract — the task doing the work changes it; one
        # another build protects is disputed on that build. guin-site's refusal named neither, and the session was left guessing
        guards = {f: [t2["id"] for t2 in all_tasks(plan, state) if t2["id"] != args.task and f in (t2.get("tests") or []) and not writes_tests(t2)
                      and state["tasks"].get(t2["id"], {}).get("status") not in ("done", "skipped", "dropped")] for f in stray}
        steps = ["%s is protected by %s: `chongdae dispute %s --tests %s --why WHY`" % (f, ", ".join(g), g[0], f) for f, g in guards.items() if g]
        free = [f for f, g in guards.items() if not g]
        if free:
            steps.append("%s: no open build protects %s — %s not the contract, so there is nothing to dispute: change %s in this task (%s), "
                         "recorded as its work; if a build should protect %s, name that build (`chongdae dispute BUILD --tests ...`), or add it with --tests"
                         % (", ".join(free), "it" if len(free) == 1 else "them", "it is" if len(free) == 1 else "they are", "it" if len(free) == 1 else "them",
                            args.task, "it" if len(free) == 1 else "them"))
        raise SystemExit("%s: not among %s's protected tests (%s) — the next step:\n  %s"
                         % (", ".join(stray), args.task, ", ".join(protected) or ("none" if not task.get("tests") else "none: %s has no check, its --tests are what it writes" % args.task),
                            "\n  ".join(steps)))
    judgment = {**({"delegated": delegation_record(d, args.delegated, "dispute")["delegated"]} if args.delegated else
                   {"by": signer(args)}), "why": args.why}
    owner = tests_writer(plan, state, task, files)
    if owner is None and amending_tasks(plan, state, task, files):
        raise SystemExit("%s: already being amended by %s — `chongdae run` once it is done" % (", ".join(files), ", ".join(amending_tasks(plan, state, task, files))))
    writer = route_dispute(args.target, d, state, plan, task, [{"test": f, "why": args.why, "by": "session"} for f in files], judgment=judgment)
    wdef = next(t for t in all_tasks(plan, state) if t.get("id") == writer)
    hands = "the session" if state["tasks"][writer].get("taken") or hire(providers(args.target, plan), wdef)[1] in SESSION_HANDS else wdef.get("role")
    print("dispute %s: %s %s to amend %s — %s; %s waits for it, then takes the amended tests as its contract. `chongdae run` next."
          % (args.task, writer, "made" if owner is None else "reopened", ", ".join(files),
             "the session amends them (`run` stops for it until they change)" if hands == "the session" else "%s amends them" % hands, args.task))
    return 0


def cmd_adopt(args):
    """A judgment: these files are TASK's work. Two open session tasks share one tree and each measures from its own `add`, so
    the tree cannot say whose a change is when both were open — or when the work came before its task was added (the contract
    edited before its task, the order slip every guin-site review found). guin-site, 2026-10-02: escape-tests finished first
    and counted src/lib/outputs.ts, written for escape-build; escape-build's start held it, its diff was empty, the verifier
    rejected it on every retry, and the drop-and-add that followed recorded nothing. `adopt` moves the attribution: out of
    every other task's `touched` (and pinned into an open one's start), out of TASK's start, into TASK's own — recorded as a
    judgment, with who and why."""
    d = run_dir(args.target)
    plan, state = (load_plan(d), load_state(d)) if d else ({}, {})
    if state.get("status") != "running":
        raise SystemExit("no run in progress — `adopt` moves attribution between the tasks of a running run; a closed run's record stands as it was judged")
    ts = state["tasks"].get(args.task)
    task = next((t for t in all_tasks(plan, state) if t.get("id") == args.task), None)
    if not ts or not task:
        raise SystemExit("no task %s" % args.task)
    if ts["status"] == "skipped":
        raise SystemExit("%s was skipped — nothing was done in it to own files" % args.task)
    files = []
    for f in args.files:
        f = f.replace("\\", "/").strip()
        while f.startswith("./"):
            f = f[2:]
        files.append(f.rstrip("/"))
    files = sorted(set(files))
    based = (state.get("created") or {}).get("based_on")
    known = set(dirty(args.target, records_too=True) or {}) | set(committed_since(args.target, based, heads=(state.get("created") or {}).get("nested")) if based else {})
    for t2 in all_tasks(plan, state):
        o = state["tasks"].get(t2["id"], {})
        known |= set(o.get("touched") or []) | set((o.get("start") or {}) if isinstance(o.get("start"), dict) else {})
    unknown = [f for f in files if f not in known]
    if unknown:
        raise SystemExit("%s: nothing in this run or in the tree changed it — there is no work to attribute (a path is project-relative)" % ", ".join(unknown))
    now = dirty(args.target) or {}
    for t2 in all_tasks(plan, state):
        o = state["tasks"].get(t2["id"], {})
        if t2["id"] == args.task:
            continue
        affected = bool(set(files) & (set(o.get("touched") or []) | set(o.get("shared") or {}) |
                        {f for a in o.get("adopted") or [] if isinstance(a, dict) for f in a.get("files") or []}))
        if o.get("status") == "todo" and isinstance(o.get("start"), dict):
            affected = affected or any(o["start"].get(f) != (now.get(f) or file_hash(args.target, f)) for f in files)
        if affected:
            refused = mutation_owner_refusal(args.target, d, t2["id"], o)
            if refused:
                raise SystemExit("adopt would also change %s: %s" % (t2["id"], refused))
    judgment = {**({"delegated": delegation_record(d, args.delegated, "adopt")["delegated"]} if args.delegated else
                   {"by": signer(args)}), "why": args.why, "files": files, **stamp()}
    moved = {}
    for t2 in all_tasks(plan, state):
        o = state["tasks"].get(t2["id"], {})
        if t2["id"] == args.task:
            continue
        gave = [f for f in files if f in (o.get("touched") or [])]
        if gave:
            o["touched"] = [f for f in o["touched"] if f not in files]
        for a in o.get("adopted") or []:
            if isinstance(a, dict) and set(a.get("files") or []) & set(files):
                gave += [f for f in a["files"] if f in files]
                a["files"] = [f for f in a["files"] if f not in files]
        if o.get("status") == "todo" and isinstance(o.get("start"), dict):
            for f in files:
                if f in (measured(args.target, o) or []):
                    gave.append(f)
                h = now.get(f) or file_hash(args.target, f)
                if o["start"].get(f) != h:
                    o["start"][f] = h   # an open task measures its own changes from here: these are TASK's
                    o.setdefault("pinned", {})[f] = args.task
        for f in files:
            if f in (o.get("shared") or {}):
                o["shared"].pop(f)
        if o.get("shared") == {}:
            o.pop("shared")
        if gave:
            gave = sorted(set(gave))
            moved[t2["id"]] = gave
            o.setdefault("gave", []).append({"files": gave, "to": args.task, "why": args.why, **{k: judgment[k] for k in ("by", "delegated") if k in judgment}, **stamp()})
    for f in files:
        if isinstance(ts.get("start"), dict):
            ts["start"].pop(f, None)   # out of TASK's own start: its measure counts them from HEAD (or the commit it stood on)
        (ts.get("pinned") or {}).pop(f, None)
        (ts.get("shared") or {}).pop(f, None)
    for k in ("pinned", "shared"):
        if ts.get(k) == {}:
            ts.pop(k)
    ts.setdefault("adopted", []).append({**judgment, **({"from": moved} if moved else {})})
    if "touched" in ts and ts["touched"] is not None:
        ts["touched"] = sorted(set(ts["touched"]) | set(files))
    save_state(d, state)
    commit_record(args.target, os.path.basename(d), "adopt %s: %s — %s" % (args.task, ", ".join(files), args.why))
    src = "; ".join("from %s: %s" % (k, ", ".join(v)) for k, v in moved.items())
    nobody = [f for f in files if not any(f in v for v in moved.values())]
    stopped = ts["status"] == "todo" and (ts.get("rejected") or (ts.get("response") or {}).get("status") not in (None, "done"))
    print("adopted %s into %s (%s%s%s): %s" % (", ".join(files), args.task, src, "; " if src and nobody else "",
                                            "no task held %s" % ", ".join(nobody) if nobody else "", args.why))
    if ts["status"] == "todo":
        print("  %s measures them as its own now — %s" % (args.task, "`chongdae retry %s --by NAME | --delegated WHY`, then `chongdae run`" % args.task if stopped
                                                           else "`chongdae run` decides it with them"))
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
        name, plan, state = os.path.basename(r), load_plan(r), load_state(r)
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
    seen_where, seen_count = [], 0
    for r in all_runs(target):
        name, plan, state = os.path.basename(r), load_plan(r), load_state(r)
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
                if not (ts.get("taken") or {}).get("for-lack"):   # chongdae's own reason when it took a task for lack: counted below, not a stamp
                    stamp(own.get("why"), "%s/%s" % (name, tid))
                findings.append({"kind": "self-performed", "where": "%s/%s" % (name, tid), "layer": "observation",
                                 "text": "the session did this itself instead of the lock's %s (decided by %s): %s" % (own.get("instead-of"), signer_text(own.get("by")), own.get("why"))})
            # judgments the session signed as itself (no `--by NAME`): not a person's decision, and said so — a reviewer
            # reading delegations must not take them for the owner's
            signed = [("drop", ts.get("dropped")), ("take", ts.get("taken")), ("claim", ts.get("claimed_by")), ("dispatch", ts.get("dispatched"))]
            signed += [("unstage %s" % role, rec) for role, rec in (ts.get("unstaged") or {}).items()]
            signed += [("adopt %s" % ", ".join(a.get("files") or []), a) for a in ts.get("adopted") or [] if isinstance(a, dict)]
            signed += [("retry after attempt %d" % i, a.get("retried")) for i, a in enumerate(ts.get("attempts", []), 1)]
            signed += [("reopen for attempt %d" % i, a.get("reopened")) for i, a in enumerate(ts.get("attempts", []), 1)]
            for what, j in signed:
                by = j if what == "claim" else (j.get("by") if isinstance(j, dict) else None)
                if is_agent(by):
                    findings.append({"kind": "session-judged", "where": "%s/%s" % (name, tid), "layer": "observation", "by": by,
                                     "text": "%s decided by %s, not a person%s" % (what, signer_text(by), ": " + str(j.get("why") or j.get("taken") or "") if isinstance(j, dict) and (j.get("why") or j.get("taken")) else "")})
            for i, r in enumerate(ts.get("did") or [], 1):
                # an operation outside the repository, as chongdae ran it: what it was is an observation; one that failed is an
                # objection — a deploy or a deletion that exited non-zero left the outside in a state nobody has looked at
                f = {"kind": "did", "where": "%s/%s did %d" % (name, tid, i), "by": r.get("signer"),
                     "text": "`%s` -> exit %s%s, run by chongdae at %s, signed %s%s%s" % (
                         r.get("command"), "unknown" if r.get("outcome") == "unknown" else r.get("exit"), " (it did not run)" if r.get("ran") is False else "", r.get("at"), signer_text(r.get("signer")),
                         ": " + r["why"] if r.get("why") else "", "; approved in %s" % r["approved-in"] if r.get("approved-in") else "; no approval cited")
                         + "".join("; %s is outside the project: %s" % (outside_what(o), outside_text(o)) for o in r.get("outside") or [])
                         + ("; " + masked_text(r["masked"]) if r.get("masked") else "")}
                if r.get("exit") == 0:
                    f["layer"] = "observation"
                else:
                    f["text"] += " — it said: " + " / ".join(r.get("tail") or [])
                findings.append(f)
            word = reads_as_operation(ts.get("def") or {}) if ts.get("status") == "done" and not ts.get("did") else None
            if word:
                # A filename or the subject of an edit can mention deploy/publish. Do not turn wording into a claim of
                # missing execution, ask to re-run an operation, or create debt at close.
                findings.append({"kind": "operation-mention", "where": "%s/%s" % (name, tid), "layer": "observation",
                                 "text": "brief or role mentions '%s'; this task has no `did` record. Wording alone does not establish that an operation "
                                         "was intended or executed: %s" % (word, cut((ts.get("def") or {}).get("brief") or "", 160))})
            if (ts.get("performed_by") or {}).get("provider") == "subagent" and ts.get("status") in ("done", "dropped"):
                findings.append({"kind": "subagent", "where": "%s/%s" % (name, tid), "layer": "observation",
                                 "text": "done by the session's sub-agent (%s) — declared hands, not self-performed; chongdae saw the session's tree, not the sub-agent%s"
                                         % (" ".join(x for x in ((ts.get("performed_by") or {}).get("host"), (ts.get("performed_by") or {}).get("model")) if x) or "?",
                                            "; scope " + ", ".join(x or "." for x in (ts.get("def") or {}).get("scope") or []) if (ts.get("def") or {}).get("scope") else "")})
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
                later_ok = verdict_of(ts) == "accept"
                gone = [o.get("finding") for o in (a.get("overruled") or {}).get("findings") or []]   # overruled: said in its non-claim, not charged again
                for f in ((a.get("review") or {}).get("findings") or []):
                    if f in gone:
                        continue
                    findings.append({"kind": "verifier-reject", "where": "%s/%s attempt %d: %s" % (name, tid, i, f.get("where", "")),
                                     **({"layer": "observation"} if later_ok else {}),
                                     "text": "%s: %s — record: \u201c%s\u201d — tree: \u201c%s\u201d%s" % (f.get("kind"), f.get("why"), f.get("record_quote"), f.get("tree_quote"),
                                                                          " (a later attempt was accepted by the verifier)" if later_ok else "")})
        # tasks chongdae took for the session because a member's sandbox lacked a capability and the lock had no alternate:
        # one observation per run, so a review sees the setup's cost without it being a charge
        lack = {}
        for tid, ts in state.get("tasks", {}).items():
            fl = (ts.get("taken") or {}).get("for-lack")
            if isinstance(fl, dict):
                caps = fl.get("lacked") or []
                key = (fl.get("role"), "+".join(caps), ", ".join("%s: %s" % (c, (fl.get("capabilities") or {}).get(c, "undecided")) for c in caps))
                lack.setdefault(key, []).append(tid)
        if lack:
            n = sum(len(v) for v in lack.values())
            findings.append({"kind": "taken-for-lack", "where": ", ".join("%s/%s" % (name, t) for v in lack.values() for t in v), "layer": "observation",
                             "text": "taken for lack: %d task(s) — %s" % (n, "; ".join("%s lacked %s (no %s@%s; capabilities: %s)" % (role, cap, role, cap, dec)
                                                                                for (role, cap, dec) in sorted(lack, key=str)))})
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
        for n in non_claims(state, unseen=True):
            if "(verifier) " in n:
                # what the verifier says it did not do (an accept without reading the tree): for the reviewer to weigh the
                # accept by, not a charge of its own
                findings.append({"kind": "verifier-non-claim", "where": name, "layer": "observation", "text": n})
            else:
                findings.append({"kind": "non-claim", "where": name, "text": n})
        for tid, ts in sorted(state.get("tasks", {}).items()):
            n = len((ts.get("seen-non-claims") or {}).get("texts") or [])
            if n:
                seen_where.append("%s/%s (%d)" % (name, tid, n))
                seen_count += n
        # a task left open when its run closed, or rejected and never retried: the cheap way past a rejection is to abandon the
        # task and open a new run — the record keeps it visible; this line makes someone look
        if state.get("status") == "complete":
            for tid, ts in state.get("tasks", {}).items():
                if ts.get("status") not in ("done", "skipped", "dropped"):
                    rej = ts.get("rejected")
                    findings.append({"kind": "left-open", "where": "%s/%s" % (name, tid),
                                     "text": ("rejected by %s (%s) and never retried" % (rej["by"], rej["why"]) if rej else "left open when the run closed")
                                             + " — `chongdae drop %s --why` if it will not be done, or a run that does it" % tid})
    if seen_count:
        findings.append({"kind": "seen-non-claims", "layer": "observation", "where": ", ".join(seen_where),
                         "text": "%d provider non-claim(s) went to the verifier with the work and it accepted — read there, said here, not charged; "
                                 "each stays in its task's `non-claims`" % seen_count})
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
        plan, state = load_plan(r), load_state(r)
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
    plan, state = load_plan(d), load_state(d)
    open_ = open_tasks(plan, state)
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
        return "by %s (auto: %s)" % (signer_text(j.get("by", "chongdae")), j["auto"])
    if j.get("taken"):
        return "by %s (taken: %s)" % (signer_text(j.get("by")), j["taken"])
    extra = [x for x in ("%s: %s" % (k, j[k] if not isinstance(j[k], list) else ", ".join(j[k])) for k in ("disputed", "why", "requires") if j.get(k))]
    return "by %s%s" % (signer_text(j.get("by")), " (%s)" % "; ".join(extra) if extra else "")


def author_text(by):
    """An author line for a reader: provider, what ran, host, model, effort — and what its trace says it did."""
    if not isinstance(by, dict) or not by:
        return "nobody recorded"
    p = by.get("provider", "?")
    head = ["the session's sub-agent" if p == "subagent" else p]
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
             ("scope " + ", ".join(x or "." for x in task["scope"])) if task.get("scope") else None,
             ("claimed by " + signer_text(ts["claimed_by"])) if ts.get("claimed_by") else None]
    if any(facts):
        out.append("  " + " · ".join(f for f in facts if f))
    # who did it: the role, and who stood in it
    own = ts.get("self-performed")
    if isinstance(own, dict):
        out.append("  self-performed: the session instead of the lock's %s — by %s at %s: %s" % (own.get("instead-of"), signer_text(own.get("by")), when(own.get("at"), day), own.get("why")))
    if isinstance(ts.get("dispatched"), dict):
        dp = ts["dispatched"]
        out.append("  the session's sub-agent%s — by %s at %s%s" % (" instead of the lock's %s" % dp["instead-of"] if dp.get("instead-of") else "", signer_text(dp.get("by")), when(dp.get("at"), day), ": " + dp["why"] if dp.get("why") else ""))
    if isinstance(ts.get("taken"), dict):
        tk = ts["taken"]
        out.append("  taken from %s by %s at %s: %s" % (tk.get("from"), signer_text(tk.get("by")), when(tk.get("at"), day), tk.get("why")))
    if ts.get("amending") and ts.get("status") not in ("done", "dropped", "skipped"):
        out.append("  amending (disputed): %s" % "; ".join("%s — %s" % (x.get("test"), x.get("why")) for x in ts["amending"] if isinstance(x, dict)))
    if ts.get("performed_by"):
        hands = "session" if ts.get("taken") or role in SESSION_HANDS else (ts["performed_by"].get("as") or role)
        out.append("  who: %s%s" % ("" if hands == "session" else hands + " → ", author_text(ts["performed_by"])))
    # the attempts: each one's answer, its verdict with every finding, and the judgment that sent it again
    attempts = list(ts.get("attempts") or [])
    current = {k: ts[k] for k in ("review", "rejected", "answered", "verdict-given", "overruled") if k in ts}
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
                                                   " — %d finding(s)" % len(rv.get("findings") or []) if rv.get("findings") else "")
                       + (", every one overruled — went on as accepted" if rv.get("verdict") == "reject" and verdict_of(a) == "accept" else ""))
            gone = {json.dumps(o.get("finding"), sort_keys=True): o.get("why") for o in (a.get("overruled") or {}).get("findings") or []}
            for f in rv.get("findings") or []:
                why = gone.get(json.dumps(f, sort_keys=True))
                out.append(pad + "  " + finding_line(f) + (" — overruled by chongdae: %s" % why if why else ""))
            for n in rv.get("unfounded") or []:
                if isinstance(n, dict):
                    out.append(pad + "  dropped by the verifier as unfounded: %s — %s" % (finding_line(n), n.get("unfounded")))
        rj = a.get("rejected")
        if isinstance(rj, dict) and rj.get("by") != "verifier":
            out.append(pad + "rejected by %s: %s%s%s" % (rj.get("by"), rj.get("why"), " (restored: %s)" % ", ".join(rj["restored"]) if rj.get("restored") else "",
                                                     " (removed again: %s)" % ", ".join(rj["removed"]) if rj.get("removed") else ""))
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
        out.append("  %s taken off at %s by %s: %s" % (role_, when(rec.get("at"), day), signer_text(rec.get("by")), rec.get("why")))
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
    for t, w in sorted((ts.get("deleted-tests") or {}).items()):
        out.append("  deleted by the contract: %s (%s deleted it) — not sent as a test to keep" % (t, w))
    for r in ts.get("checked", {}).get("ran", []) if isinstance(ts.get("checked"), dict) else []:
        out.append("  checked by chongdae at %s: %s -> exit %s%s" % (when(r.get("at"), day), r.get("command"), r.get("exit"), " (%s)" % r["outcome"] if r.get("outcome") else ""))
    for r in ts.get("did") or []:
        out.append("  did at %s by %s: %s -> exit %s%s%s%s" % (when(r.get("at"), day), signer_text(r.get("signer")), r.get("command"), "unknown" if r.get("outcome") == "unknown" else r.get("exit"),
                                                          " (it did not run)" if r.get("ran") is False else "",
                                                          " — " + r["why"] if r.get("why") else "", "; approved in %s" % r["approved-in"] if r.get("approved-in") else ""))
        out += [pad + "| " + line for line in r.get("tail") or []]
        out += [pad + "%s is outside the project: %s" % (outside_what(o), outside_text(o)) for o in r.get("outside") or []]
        out += [pad + masked_text(r["masked"])] if r.get("masked") else []
    if isinstance(ts.get("dropped"), dict):
        dr = ts["dropped"]
        out.append("  dropped at %s by %s: %s" % (when(dr.get("at"), day), signer_text(dr.get("by")), dr.get("why")))
    if "touched" in ts:
        out.append("  touched: %s" % (", ".join(ts["touched"] or []) or "nothing"))
    # how the attribution moved, when a judgment moved it or the tree could not say
    for a in ts.get("adopted") or []:
        if isinstance(a, dict):
            out.append("  adopted %s%s — %s at %s: %s" % (", ".join(a.get("files") or []), " (from %s)" % "; ".join("%s: %s" % (k, ", ".join(v)) for k, v in a["from"].items()) if a.get("from") else "",
                                                       "by %s" % signer_text(a["by"]) if a.get("by") else "delegated: %s" % deleg_words(run_d, a.get("delegated")), when(a.get("at"), day), a.get("why")))
    for g in ts.get("gave") or []:
        if isinstance(g, dict):
            out.append("  gave %s to %s at %s%s: %s" % (", ".join(g.get("files") or []), g.get("to"), when(g.get("at"), day),
                                                    " by %s" % signer_text(g["by"]) if g.get("by") else " delegated: %s" % deleg_words(run_d, g["delegated"]) if g.get("delegated") else "", g.get("why")))
    for f, ids in sorted((ts.get("shared") or {}).items()):
        out.append("  %s: also %s's by its own word — whose it is was not settled (`adopt`)" % (f, ", ".join(ids)))
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
    t = {"tasks": 0, "done": 0, "dropped": 0, "open": 0, "skipped": 0, "self": 0, "taken": 0, "subagent": 0, "attempts": 0, "rejects": 0, "delegated": 0}
    for task in all_tasks(plan, state):
        ts = state["tasks"].get(task["id"], {})
        t["tasks"] += 1
        st = ts.get("status")
        t[st if st in ("done", "dropped", "skipped") else "open"] += 1
        t["self"] += 1 if ts.get("self-performed") else 0
        t["taken"] += 1 if ts.get("taken") else 0
        t["subagent"] += 1 if (ts.get("performed_by") or {}).get("provider") == "subagent" and not ts.get("taken") else 0
        attempts = ts.get("attempts") or []
        t["attempts"] += len(attempts) + (1 if ts.get("response") or ts.get("review") or ts.get("rejected") or st in ("done", "produced") else 0)
        t["rejects"] += sum(1 for a in attempts + [ts] if (a.get("review") or {}).get("verdict") == "reject")
        judgments = [ts.get("confirmed"), ts.get("accepted")] + [a.get("retried") for a in attempts]
        judgments += [rec.get("accepted") for a in attempts + [ts] for rec in (a.get("stages") or {}).values()]
        t["delegated"] += sum(1 for j in judgments if isinstance(j, dict) and "delegated" in j)
    return t


def tally_text(t):
    return ("tasks %d: %d done, %d dropped, %d open%s · %d self-performed (%d taken)%s · %d attempt(s) · %d verifier reject(s) · %d delegated"
            % (t["tasks"], t["done"], t["dropped"], t["open"], ", %d skipped" % t["skipped"] if t["skipped"] else "", t["self"], t["taken"],
               " · %d by the session's sub-agents" % t["subagent"] if t.get("subagent") else "", t["attempts"], t["rejects"], t["delegated"]))


def cut(text, n):
    """One line of at most n characters: whitespace collapsed, a cut marked."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def day_of(at):
    t = as_utc(at)
    return t.strftime("%Y-%m-%d") if t else "?"


def run_created(r, state):
    """When a run was created: the record's time, else the time in its id (`run-YYYYMMDD-HHMMSS-…`) — never git, never file time."""
    at = (state.get("created") or {}).get("at")
    if at:
        return at
    m = re.match(r"run-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", os.path.basename(r))
    return "%s-%s-%sT%s:%s:%s+00:00" % m.groups() if m else None


def task_when(ts, fallback):
    return (ts.get("done") or {}).get("at") or (ts.get("dropped") or {}).get("at") or ts.get("added") or fallback


def show_note(target, want):
    """`show --path FILE --brief`: at most two lines for a reader's first look at a file — the last task that changed it, and a
    task that changed it and is open or dropped now. Nothing on record: nothing printed. Full outputs pasted into an agent's
    context were ignored; one line per fact is read (jokbo's note)."""
    def holds(files):
        return any(f == want or f.startswith(want + "/") for f in files or [])
    last, loose = None, None
    for r in all_runs(target):
        plan, state = load_plan(r), load_state(r)
        created = run_created(r, state)
        for t in all_tasks(plan, state):
            ts = state["tasks"].get(t["id"], {})
            status = ts.get("status")
            files = ts.get("touched")
            if status == "todo" and state.get("status") == "running" and isinstance(ts.get("start"), dict):
                files = measured(target, ts)   # open now: what it has changed so far
            if not holds(files):
                continue
            at = task_when(ts, created)
            hit = (str(as_utc(at) or ""), os.path.basename(r), t, ts, at, state)
            if status in ("done", "produced") and (last is None or hit[0] >= last[0]):
                last = hit
            elif (status == "dropped" or (status in ("todo", "produced") and state.get("status") == "running")) and (loose is None or hit[0] >= loose[0]):
                loose = hit
    if loose:
        # a reader's note, not the file's whole history: an open or dropped task is said while its run is open or it ended in
        # the last 7 days, and only when no done task changed the file after it. guin-site, 2026-10-06: weeks-old drops
        # ("dropped: task tests-support (09-24)…") were printed 51 times in one session, at every first look at those files
        import datetime
        ended = as_utc(loose[4])
        fresh = loose[5].get("status") == "running" or (ended is not None and ended >= datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7))
        if not fresh or (last is not None and last[0] > loose[0]):
            loose = None
    if last:
        print("last changed in %s (%s), task %s: %s" % (last[1], day_of(last[4]), last[2]["id"], cut(last[2].get("brief") or "(no brief)", 100)))
    if loose:
        _, rid, t, ts, at, _ = loose
        if ts.get("status") == "dropped":
            print("dropped: task %s in %s (%s) changed it and was not done — %s" % (t["id"], rid, day_of(at), cut((ts.get("dropped") or {}).get("why") or "", 100)))
        else:
            print("open now: task %s in %s (%s) has changed it — %s" % (t["id"], rid, ts.get("status"), cut(t.get("brief") or "(no brief)", 100)))
    return 0


def show_map(target):
    """`show --brief`: one line for a session's first look — how many runs, how many this week (the last 7 days), and the last
    one closed. The running run and its open tasks are the SessionStart line's, not repeated here (jokbo's map)."""
    runs = all_runs(target)
    if not runs:
        return 0
    import datetime
    week = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    recent, closed = 0, None
    for r in runs:
        state = load(os.path.join(r, "state.json"))   # the run's own fields: no task files needed for a count
        created = as_utc(run_created(r, state))
        if created and created >= week:
            recent += 1
        if state.get("status") == "complete":
            end = (state.get("ended") or {}).get("at") or run_created(r, state)
            if closed is None or str(as_utc(end) or "") >= closed[0]:
                closed = (str(as_utc(end) or ""), r, end)
    line = "%d run%s (%d this week)" % (len(runs), "" if len(runs) == 1 else "s", recent)
    if closed:
        line += ", last closed: %s (%s)" % (cut(load_plan(closed[1]).get("goal") or "(no goal)", 80), day_of(closed[2]))
    else:
        line += ", none closed yet"
    print(line)
    return 0


def show_hands(target, after, paths):
    """`show --after ISO --hands PATH...` (jokbo's `hands` read): one JSON object, path -> whose hands this record says changed
    it, for the paths a hired task's provider changed — out now (its pending record's pid alive, the file not what it was at the
    provider's start) or answered at or after `after` (the path in that attempt's `touched_by_provider` or `touched`). The
    session's own tasks are never named; the rest is left out. Runs inside a hook: no git, no network, `{}` on any problem.
    guin-site 10-15 05:53:57: the session's own hired builder (cache-build, run-20261015-054352-a0ec) edited two files, and the
    change line told them as another hand's."""
    out = {}
    try:
        since = as_utc(after)
        want = [p for p in paths or [] if isinstance(p, str) and p]
        if since is None or not want:
            return out
        clean = {p: clean_path(p) for p in want if clean_path(p)}
        found = {}   # path -> (rank, phrase): one in flight outranks any answer, then the latest answer
        prov = None
        for r in all_runs(target):
            head = load(os.path.join(r, "state.json"))
            ended = as_utc((head.get("ended") or {}).get("at"))
            if head.get("status") != "running" and (ended is None or ended < since):
                continue   # only a run that is open, or closed within the window, can have changed the tree since then
            plan, state, rid = load_plan(r), load_state(r), os.path.basename(r)
            if prov is None:
                prov = providers(target, plan)
            tasks = {t["id"]: t for t in all_tasks(plan, state)}
            folder = os.path.join(r, LOCAL)
            for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
                if not name.endswith(".pending.json") or name.endswith(".checks.pending.json"):
                    continue   # chongdae's own run of the checks is nobody's hands
                tag = name[:-len(".pending.json")]
                tid = next((t for t in sorted(tasks, key=len, reverse=True) if tag == t or tag.startswith(t + ".")), None)
                if tid is None:
                    continue
                pend, ts = load(os.path.join(folder, name)), state["tasks"].get(tid, {})
                if not isinstance(pend, dict) or not isinstance(pend.get("start"), dict) or not pid_alive(pend.get("pid")):
                    continue   # a native subagent's (the session's own) has no pid; a dead one is not out now
                if tag == tid and session_tree(prov, tasks[tid], ts):
                    continue
                stage = tag[len(tid) + 1:].split(".")[0]
                role = {"verify": "verifier"}.get(stage, stage) if stage else hire(prov, tasks[tid])[0] or tasks[tid].get("role") or "?"
                for p, c in clean.items():
                    if file_hash(target, c) != pend["start"].get(c):
                        found[p] = ((1, ""), "the %s of %s (%s)" % (role, tid, rid))
            for tid, t in tasks.items():
                ts = state["tasks"].get(tid, {})
                for i, rec in enumerate((ts.get("attempts") or []) + [ts]):
                    at = as_utc((rec.get("answered") or {}).get("at")) if isinstance(rec.get("answered"), dict) else None
                    by = next((b for b in (rec.get("performed_by"), ts.get("performed_by")) if isinstance(b, dict)), {})   # a resent attempt's hands are the task's, unless it was taken
                    if at is None or at < since or not by or by.get("provider") in SESSION_HANDS:
                        continue   # not answered in the window, or the session's own hands
                    files = set(rec.get("touched_by_provider") or rec.get("touched") or (ts.get("touched_by_provider") or [] if rec is not ts else []))
                    role = by.get("as") or t.get("role") or "?"
                    for p, c in clean.items():
                        if c in files and (p not in found or found[p][0] < (0, str(at))):
                            found[p] = ((0, str(at)), "the %s of %s (%s)" % (role, tid, rid))
        out = {p: v[1] for p, v in found.items()}
    except Exception:
        out = {}
    return out


def cmd_show(args):
    """What happened in a run, for a person or an agent reading it after: plain text, every reader's text whole. Read-only.
    `--since REV`: one line per run since then, and their totals. `--path FILE`: the tasks that touched it, newest first."""
    target = args.target
    if getattr(args, "hands", None) is not None:
        print(json.dumps(show_hands(target, args.after, args.hands), ensure_ascii=False, sort_keys=True))
        return 0
    if getattr(args, "brief", False):
        if args.run or args.since:
            raise SystemExit("--brief is a note on a file (`show --path FILE --brief`) or the map (`show --brief`); a run is told whole (`show --run ID`)")
        if args.path:
            want = args.path.replace("\\", "/").strip()
            while want.startswith("./"):
                want = want[2:]
            return show_note(target, want.rstrip("/"))
        return show_map(target)
    if args.since:
        names = runs_since(target, args.since)
        tot, seconds, rows = None, 0, []
        for r in all_runs(target):
            if os.path.basename(r) not in names:
                continue
            plan, state = load_plan(r), load_state(r)
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
            plan, state = load_plan(r), load_state(r)
            hits = [(t, state["tasks"].get(t["id"], {})) for t in all_tasks(plan, state)]
            hits = [(t, ts) for t, ts in hits if any(f == want or f.startswith(want + "/") for f in ts.get("touched") or [])]
            if not hits:
                continue
            created = (state.get("created") or {}).get("at")
            print("%s  %s  %s — %s" % (os.path.basename(r), when(created) if created else "?", state.get("status", "?"), plan.get("goal", "")))
            for t, ts in reversed(hits):
                found += 1
                hands = "session (taken from %s)" % t.get("role") if ts.get("taken") else "session" if t.get("role") in SESSION_HANDS else ((ts.get("performed_by") or {}).get("as") or t.get("role", "?"))
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
    plan, state = load_plan(d), load_state(d)
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
    link = state.get("parent")
    if isinstance(link, dict) and link.get("run"):
        print("parent: %s / task %s%s" % (link["run"], link.get("task", "?"), " (held at gen %s)" % link["gen"] if link.get("gen") else ""))
    for cid, clink, cstatus, counts, where in child_runs(target, os.path.basename(d)):
        print("child %s — task %s: %s (%s) [%s]" % (cid, clink.get("task", "?"), cstatus, ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())) or "no tasks", where))
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

class CommandLock:
    """One record-changing command per checkout, from its first read through its commit.

    A per-task lease coordinates remote workers; it cannot protect this checkout's shared state snapshots or git
    index. Hold an OS lock here instead of a timed marker: a slow check cannot expire it, and process death releases
    it. Other projects and worktrees have their own lock. Never unlink the file (waiters may hold the old inode).
    """
    def __init__(self, target, path=None):
        self.path = path or os.path.join(os.path.realpath(target), RUNS, LOCAL, "command.lock")
        self.file = None
        self.acquired = False

    def __enter__(self):
        import errno
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.file = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(self.file.fileno()).st_size == 0:
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError as err:
            self.file.close()
            self.file = None
            if err.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
        return self

    def __exit__(self, *exc):
        if self.file is not None:
            # Ordinary command locks are not inherited; the internal launcher explicitly keeps its own lock across exec.
            self.file.close()
            self.file = None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_checks"] and len(argv) == 3:
        return checks_worker(argv[1], argv[2])   # the task's checks in a process of their own (budget_checks): not a command anyone types
    if argv[:1] == ["_launch"] and len(argv) == 3:
        return launch_worker(argv[1], argv[2])   # durable detached launch, before the worker can execute
    command = None
    if argv[:1] == ["did"] and "--" in argv:
        # `did TASK [options] -- COMMAND ARG...`: everything after the first `--` is the command's own argv, options included
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="chongdae", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "status", "run", "confirm", "accept", "retry", "recheck", "add", "claim", "take", "drop", "dispute", "adopt", "unstage", "close", "report", "delegate", "show", "did"):
        p = sub.add_parser(name)
        p.add_argument("--target", default=None, help="the project (default: the nearest directory at or above this one that holds .chongdae/, else this one)")
        if name == "init":
            p.add_argument("--goal", default=None)
            p.add_argument("--plan", default=None, help="a plan the session agent wrote (chongdae/plan@1): a path, or `-` for stdin (no file to write before the run exists); without it, the bootstrap plan")
            p.add_argument("--merge", action="store_true", help="the merge plan: recheck every completed run (+ coherence when the lock declares that role)")
            p.add_argument("--session", action="store_true", help="a session run: tasks are added as the work goes")
            p.add_argument("--from", dest="from_doc", default=None, help="session run: the plan document (plan/PLAN.md) whose `## Q-…` sections tasks `--closes`; providers receive those sections as the contract")
            p.add_argument("--base", default=None, help="with --merge: the revision the other side's relations are compared from (default: the merge base of HEAD^1 and HEAD^2)")
            p.add_argument("--parent", default=None, metavar="RUN/TASK", help="this run does TASK of run RUN (typically a worktree run on its own branch): recorded as `parent`; the parent's `show` lists its children and their states, computed from the children's records. Under a lease the task is taken for this session now")
            p.add_argument("--worktree", action="store_true", help="the run's container is physical: its own worktree and branch under .chongdae/wt/ (from HEAD, or from --base REV: two independent slices branch from the same base); `close` merges it back")
        if name == "close":
            p.add_argument("--run", default=None, help="the run to close (default: the one running, else the newest) — a completed worktree run is named here to merge it back")
            p.add_argument("--anyway", action="store_true", help="with --why: close although the run's work is not committed or the reviewer found objections the tree can answer — recorded (`closed-anyway`) and said as a non-claim")
            p.add_argument("--why", default=None, help="with --anyway: why the run closes with them standing")
            p.add_argument("--by", default=None, help="with --anyway: who decided (default: the session — its host and model)")
        if name == "run":
            p.add_argument("tasks", nargs="*", metavar="TASK", help="advance only these tasks; dependencies must already be done or also selected. "
                           "Naming a no-check task is the session's word that it is done. Host sub-agent tasks must be named after their answers arrive. "
                           "Another session's task needs an explicit `take --why` handover; naming it does not transfer ownership")
        if name in ("confirm", "accept", "retry"):
            p.add_argument("task")
            p.add_argument("--by", default=None, help="the person who decided" + (" (a gate: --by NAME or --delegated is required)" if name != "retry" else " (default: the session — its host and model; a retry is not a gate)"))
            p.add_argument("--delegated", default=None, help="instead of --by: why the human handed this off (or D-xxxx)")
        if name == "retry":
            p.add_argument("--requires", nargs="+", default=None, choices=list(REQUIRES), help="say on the task what its sandbox must give (a member's sandbox lacked it): added to its `requires`; the lock's `<role>@<cap>` alternate, when it has one, is hired")
        if name in ("retry", "take"):
            p.add_argument("--checked", action="append", default=None, metavar="COMMAND", help="a command (quoted) chongdae runs itself in the project now; exit 0 is recorded as evidence chongdae saw and goes to the verifier (with what changed after), a failure refuses. Repeatable — e.g. the full test run a worker's report could not show")
            p.add_argument("--checked-red", action="append", default=None, metavar="COMMAND", help="a tests task's expected red run (quoted): chongdae runs it now; a non-zero exit is recorded as red as expected, a zero exit as passed before the build — both recorded, as evidence chongdae saw. Repeatable")
        if name == "dispute":
            p.add_argument("task", help="the open build whose protected tests are wrong")
            p.add_argument("--tests", nargs="+", required=True, help="the protected test files that contradict the contract (FILE or FILE::test)")
            p.add_argument("--why", required=True, help="what in them contradicts the contract (or cannot run here) — the brief of the amendment")
            p.add_argument("--by", default=None, help="who disputes (default: the session — its host and model, not git user.name)")
            p.add_argument("--delegated", default=None, help="instead of --by: why the human handed this off (or D-xxxx)")
        if name == "adopt":
            p.add_argument("task", help="the task whose work these files are")
            p.add_argument("files", nargs="+", metavar="FILE", help="project-relative paths")
            p.add_argument("--why", required=True, help="why they are this task's work (written for it while another task was open; written before it was added)")
            p.add_argument("--by", default=None, help="who judged (default: the session — its host and model, not git user.name)")
            p.add_argument("--delegated", default=None, help="instead of --by: why the human handed this off (or D-xxxx)")
        if name == "report":
            p.add_argument("--since", default=None, help="the revision the last review covered; changes since it are checked against the runs' `touched`")
        if name == "show":
            g = p.add_mutually_exclusive_group()
            g.add_argument("--run", default=None, help="the run to tell (default: the one running, else the newest)")
            g.add_argument("--since", default=None, help="one line per run whose record was not complete at REV, and their totals")
            g.add_argument("--path", default=None, help="the runs and tasks whose `touched` holds this file (or a file under this directory), newest first")
            p.add_argument("--brief", action="store_true", help="one line per fact, for a reader's first look (jokbo): with --path, at most two lines — the last task that "
                           "changed the file, and one that changed it and is open or dropped now (nothing on record: nothing printed); alone, the map — "
                           "how many runs, how many in the last 7 days, the last one closed (the running run is the SessionStart line's)")
            p.add_argument("--hands", nargs="*", default=None, metavar="PATH", help="jokbo's `hands` read: one JSON object, path -> whose hands changed it — "
                           "a hired task's provider out now (the file not what it was at its start) or answered at or after --after; `{}` otherwise")
            p.add_argument("--after", default=None, help="with --hands: when the session's last call left the tree (ISO, UTC)")
        if name == "delegate":
            p.add_argument("--run", default=None, help="the run this delegation belongs to (default: the one running, else the newest)")
            p.add_argument("--scope", required=True, help="comma-separated judgment kinds it covers, e.g. confirm,accept,retry")
            p.add_argument("--why", required=True, help="why these judgments are handed off — the one reason, written once")
            p.add_argument("--by", required=True, help="the person who declared the delegation")
        if name == "unstage":
            p.add_argument("task")
            p.add_argument("role", help="a role hired before or after the task (quibble, newbie, ...)")
            p.add_argument("--why", required=True)
            p.add_argument("--by", default=None, help="who decided (default: the session — its host and model, not git user.name)")
        if name == "did":
            p.usage = "chongdae did TASK [--why WHY] [--approved-in SOURCE:ID] [--by NAME] [--target DIR] (-- COMMAND [ARG...] | --each FILE)"
            p.description = ("Run one operation outside the repository (a deploy, a secret deleted, a remote database changed) for TASK: the command after `--` "
                             "runs in the project without a shell, and {command, exit, tail, at, why, approved-in, signer} is recorded on the task whatever "
                             "the exit, printed, and committed. The program it runs, when it is a script outside the project, is kept in the record (sha256, its text "
                             "when small); a file given as an argument keeps only its sha256 and size, nothing that looks like secrets is kept, and a "
                             "secret-looking value in the command or its output is masked. `--each FILE` "
                             "runs one command per line as one judgment (one commit; a non-zero exit stops the rest). `show` prints it; `report` lists it as an "
                             "observation, or as an objection when it exited non-zero.")
            p.add_argument("task", help="the task whose work the operation is")
            p.add_argument("--why", default=None, help="what the operation is for")
            p.add_argument("--reconcile", default=None, metavar="ID", help="resolve an interrupted operation after checking external effects; requires --why, executes nothing, and keeps unknown outcomes as unknown")
            p.add_argument("--approved-in", dest="approved_in", default=None, metavar="SOURCE:ID",
                           help="where the person agreed to it (a mangsang source, `source:at-63`) — cite it when the operation cannot be undone")
            p.add_argument("--by", default=None, help="who decided to run it (default: the session — its host and model)")
            p.add_argument("--each", default=None, metavar="FILE", help="several operations as one judgment: FILE (or `-`, stdin) holds one command per line (no shell line; "
                           "blank lines and `#` comments skipped). Each is recorded with its own exit and tail, all in one commit; a non-zero exit stops the rest")
        if name == "take":
            p.add_argument("task")
            p.add_argument("--why", required=True, help="why this session finishes it or takes ownership from another session; live checks/providers and unanswered native dispatches must finish first")
            p.add_argument("--by", default=None, help="who decided (default: the session — its host and model, not git user.name)")
        if name == "drop":
            p.add_argument("task")
            p.add_argument("--why", required=True, help="why this task will not be done (mis-specified, superseded, abandoned)")
            p.add_argument("--by", default=None, help="who decided (default: the session — its host and model, not git user.name)")
        if name == "claim":
            p.add_argument("task", nargs="?", default=None)
            p.add_argument("--by", default=None, help="who takes it (default: the session, on this machine — `run` on other machines skips it); an empty string releases")
            p.add_argument("--list", action="store_true", help="every hold: who (machine/session), its generation, its age and last progress; lapsed and long-held ones marked "
                           "(without a lease setting: the record's claims)")
            p.add_argument("--break", dest="brk", action="store_true", help="with --why: take over a live hold (a lease setting) — a judgment, recorded and committed; the old holder is told at its next renewal")
            p.add_argument("--why", default=None, help="with --break: why the hold is broken")
            p.add_argument("--release", action="store_true", help="give this session's hold back (done, drop and close give holds back on their own); the key stays as a released marker that keeps its generation")
            p.add_argument("--prune", action="store_true", help="with --list: delete released markers older than lease-ceiling (a take of such a key then counts its generation from the record)")
        if name == "add":
            p.add_argument("id")
            p.add_argument("--role", default=None, help="who does it. Left out, the lock says: a task with --check goes to its `implementer`, one that writes --tests to its `nitpick`, anything else to this session. `session` where the lock declares a provider needs --why (recorded); `subagent`: the session's own sub-agent (the host's Agent tool) — declared hands, not self-performed (a lock role may name `subagent` as its provider too); any role the lock declares can be named outright")
            p.add_argument("--scope", nargs="+", default=None, metavar="PATH", help="the files and directories this task's hands own (project-relative). While scoped tasks are open, a changed file is the open task's whose scope holds it most narrowly, not whichever finishes first; a file in two scopes, or in none, is said at the finish with the `adopt` that settles it. Unscoped tasks keep the window rule")
            p.add_argument("--why", default=None, help="with --role session: why this session does the task itself, instead of the provider the lock declares for it")
            p.add_argument("--by", default=None, help="with --role session --why (or --role subagent): who decided (default: the session — its host and model, not git user.name)")
            p.add_argument("--brief", default=None)
            p.add_argument("--closes", nargs="*", default=None)
            p.add_argument("--check", action="append", default=None, help="a check argv (quoted); repeatable. On an open session task with no check (and nothing else given): attaches it")
            p.add_argument("--tests", nargs="*", default=None, help="test files. For a nitpick task (or one no --check decides): the tests it writes. For a task with --check: files it may not change — its judgment restores them (`add` says which). A task that corrects a build's tests does not protect them: `chongdae dispute BUILD --tests F --why`")
            p.add_argument("--gate", choices=["human"], default=None)
            p.add_argument("--before", nargs="*", default=None, help="roles to run before the work (their findings must be accepted first): --before quibble")
            p.add_argument("--after", nargs="*", default=None, help="roles to run after the checks pass, before the gate; their findings go to the record: --after newbie")
            p.add_argument("--domain", default=None, help="what kind of artifact the task makes (code, site, plan, ...): carried in every request, so a worker reads it in that domain's terms")
            p.add_argument("--requires", nargs="*", default=None, choices=list(REQUIRES), help="what the work requires of the sandbox its hands run in (network, loopback): sent as the request's `needs`; a member that cannot give it refuses before starting. The lock's `<role>@<cap>[+<cap>]` alternate whose capabilities cover it is hired instead of the plain role")
    args = ap.parse_args(argv)
    if args.cmd == "did":
        args.command = command
    if args.target is None:
        # the shell's directory is not the project: `cd tests` and then `chongdae run` found no run there
        args.target = record_root(os.getcwd()) or "."
    try:
        if args.cmd in ("status", "show", "report", "recheck"):
            return COMMANDS[args.cmd](args)
        with CommandLock(args.target) as lock:
            if not lock.acquired:
                print("still working: another chongdae command is updating this project; "
                      "this call changed nothing — retry `chongdae %s` with the same arguments" % args.cmd)
                return WAITING
            recover_project_states(args.target)
            refused = task_mutation_guard(args)
            if refused:
                return stop(refused)
            if args.cmd == "close":
                d = run_dir(args.target, getattr(args, "run", None))
                main = (load_state(d).get("worktree") or {}).get("main") if d else None
                if main and os.path.realpath(main) != os.path.realpath(args.target):
                    # Landing changes the destination checkout too. Acquire before close changes either record;
                    # a busy destination must leave the child running so the same close can be retried.
                    with CommandLock(main) as destination:
                        if not destination.acquired:
                            print("still working: another chongdae command is updating the destination project; "
                                  "this call changed nothing — retry `chongdae close` with the same arguments")
                            return WAITING
                        recover_project_states(main)
                        return COMMANDS[args.cmd](args)
            return COMMANDS[args.cmd](args)
    except RemoteStop as err:
        print("decision: %s" % err)
        return DECISION


COMMANDS = {"init": cmd_init, "status": cmd_status, "run": cmd_run, "confirm": cmd_confirm, "recheck": cmd_recheck, "accept": cmd_accept, "retry": cmd_retry,
            "add": cmd_add, "claim": cmd_claim, "take": cmd_take, "drop": cmd_drop, "dispute": cmd_dispute, "adopt": cmd_adopt, "unstage": cmd_unstage, "close": cmd_close, "report": cmd_report, "delegate": cmd_delegate, "show": cmd_show, "did": cmd_did}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
