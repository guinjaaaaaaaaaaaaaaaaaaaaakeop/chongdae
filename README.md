# chongdae

The orchestrator for an era where development is split into parts done by agents. Runs a plan — a DAG of roles with
checks in code and human gates in between — and records the run apart from commit history: what was decided, by whom,
and what was not verified.

Start with [host entry points](#shared-instructions-and-host-entry-points) and [run types](#runs).
See [commands](#commands) for the CLI, [providers](#providers) for worker lifecycle,
[files](#files-in-your-project) for records, and [versioning](#versioning) for releases and updates.

## Install

Python 3.11 or newer is required on both hosts. Ensure `python3` on the host's PATH selects that interpreter.

```
claude plugin marketplace add guinjaaaaaaaaaaaaaaaaaaaaakeop/chongdae
claude plugin install chongdae@chongdae
```

Codex: `codex plugin marketplace add guinjaaaaaaaaaaaaaaaaaaaaakeop/chongdae`, `codex plugin add chongdae@chongdae`
(the skill is `$chongdae:run`).

## Shared instructions and host entry points

[AGENTS.md](AGENTS.md) is the common guidance for maintaining this source checkout;
[CLAUDE.md](CLAUDE.md) imports it for Claude Code compatibility. Plugin installation does not automatically
load these repository instructions into the consuming project.

For installed use, both hosts share [skills/run/SKILL.md](skills/run/SKILL.md) and `chongdae.py`.
The `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` manifests expose host-specific packaging;
`commands/` contains Claude entry points for individual engine actions, not a second run workflow.
Either host can call `python3 <plugin-root>/chongdae.py <command> --target <project>` directly;
replace the angle-bracket placeholders with actual values and quote paths containing spaces.
For Codex, set `AGENT_HOST=codex` when calling the engine from a shell to identify the session host and select
the host argument for native role adapters. This does not switch plugin-path lookup to the Codex registry:
`plugin_root()` checks project-local links, recognizes its own chongdae root, then uses Claude's installation and
marketplace records. For other plugins installed only in Codex, provide their actual roots through
`hunsu.local.json` links before resolving `{plugin:NAME}` arguments.
Use explicit task names when advancing parallel host workers, as the shared run skill describes.

## Runs

A run is the unit of judgment; commits are the unit of change. Three kinds, plus the default. `init --goal "..."`
alone starts the **bootstrap** plan (questions -> plan document -> modeler; question ids are semantic — `Q-drafts`,
never a bare number, so parallel workers' ids don't collide at a merge). `init --plan FILE` (or `--plan -`: the plan
on stdin — intent written before its run exists needs no file in the tree) runs a **plan** the session agent wrote.
`init --session` opens a **session** run: no plan, tasks added as the work goes. `init --merge [--base REV]` is a
**merge** run: two branches were each right alone; someone must say this tree is right again.

`init ... --worktree` makes the run's container physical: its own worktree and branch (`run/<run-id>`) under
`.chongdae/wt/`, from HEAD or from `--base REV` (two independent slices branch from one commit) — a shared tree may
have other workers, and it is not this run's to dirty. Every later command takes `--target <that path>`; the write
gate inside the worktree is that worktree's own run. `close` merges it back — a session run when you close it, a plan
or bootstrap run once `run` completed it: commit the worktree, `--no-ff` merge into main, recheck there. Clean merge +
green recheck removes the worktree and branch; a conflict or a red recheck comes back as a `decision:` — resolve in
main and `init --merge`, and the worktree stays until the merge landed.

`init ... --parent RUN/TASK` starts a **child** run: it does task TASK of run RUN (typically a worktree run on its own
branch, on whichever machine took the task). The child records `parent: {run, task[, gen]}`; the parent's `show` lists its
children with their states (`child run-… — task T1: running (2 done, 1 todo) [worktree run-… | branch … | remote branch …]`),
computed from the children's own records — in this tree, its worktrees, and its local and remote-tracking branches — never
stored in the parent's state, so machines writing children never rewrite one parent file. `show` of a child names its
parent. A child may start beside its running parent; it is then the run being worked. Under a lease the parent's task is
taken for this session at `init` (held elsewhere: refused), the child's own tasks are this session's by that hold, `run`
renews it on the child's progress, and the child does not close or land if the hold moved on to another generation.

## Many machines on one plan

Off by default: a project that declares neither setting below behaves as before — `claim` writes the record, nothing is
pushed.

**Leases** — `settings.chongdae.lease` in hunsu.json (hunsu.local.json on top, as for every chongdae setting). A lease is who
holds a task right now: coordination, not the record. It enters no branch; what the record keeps is the result's generation
and how its hold began.

| `lease` | where a hold lives | atomic across |
|---|---|---|
| absent | the record (`claimed_by`, as before) | — |
| `"local"` | a file per key under this machine's git common dir (`chongdae-claims/`, shared by its worktrees; `.chongdae/local/claims/` with no git), created with `O_CREAT\|O_EXCL`, swapped under a per-key lock | the sessions of one machine |
| `"git"` | a ref per key on the remote `origin` (or `lease-remote`): `refs/chongdae/claims/<run>/<task>` → a parentless commit with the empty tree whose message is the lease. Taken with `git push --force-with-lease=<ref>: origin <sha>:<ref>` (only if absent), renewed, broken or released by pushing against the value read | machines that reach the remote (it must accept custom refs; the lease's end is the machines' clocks) |
| `["cmd", ...]` | a service's command (contract below) | whatever the service guarantees |

A lease is `{key, holder: {machine, session, agent[, by]}, gen, taken, renewed, last-progress, ttl, task[, scope][, from]}`
(times in UTC). The machine is `CHONGDAE_MACHINE` or the host name; the session is `CHONGDAE_SESSION`, else the host's own
session id. `from` says how a hold began when it replaced another: `{holder, gen, lapsed: true, last-progress}` or
`{holder, gen, broken: WHY, …}`.

**A release keeps the generation.** Giving a hold back does not delete its key: the key is swapped (against the value read)
to a released marker, `{key, released: <at>, gen: N, by}`, and a take succeeds on an absent or a released key, storing gen =
max(the marker's gen, the gen in this machine's record) + 1 — so a machine whose record never saw another's hold still counts
on from it. `claim --list --prune` deletes released markers older than `lease-ceiling`; a take of a pruned key falls back
to the generation in the taker's record, which (without `remote: "shared"`) may not have seen the last holder's — prune
only what no result is still waiting on.

- `claim TASK` takes a hold for this session; one per session (`lease-max`, default 1). Lost: who holds it, and the ready
  unheld tasks (exit 1). `claim --list`: every hold with its generation, age and last progress, `[lapsed]` and `[long-held]`
  marked. `claim TASK --release` (or `--by ""`) gives it back; done (`run`, `confirm`), `drop` and `close` give holds back
  on their own — each leaving a released marker that keeps the generation (`claim --list --prune` removes old ones).
- Under a lease `run` advances only the tasks this session holds; holding fewer than `lease-max`, it takes the next ready
  unheld one (a lost race: told who, the next one is tried). A store it cannot reach stops it — a task is never started
  untaken.
- **Renewed by progress, never by time alone.** After a `run` call, a hold is renewed when the task's record or the tree
  moved since its last renewal; a `run` that only finds the task still waiting at its gate does not renew it. A hold with
  no progress for `lease-ttl` seconds (default 1800) lapses: another session may take it, and its result records `from:
  {lapsed: true}`. A hold older than `lease-ceiling` (default 14400) is shown as long-held.
- `claim --break TASK --why WHY [--by NAME]` takes over a live hold: a judgment, recorded on the task (`lease-breaks`:
  from, gen, to-gen, why, by, at) and committed. The old holder is told at its next renewal: its `run` stops with who holds
  the task now and why, and its work stays in its tree or branch for the new holder.
- **Generations.** Each take raises the task's `gen`; the task's result carries it (`gen`, and `lease: {gen, holder, taken[,
  from]}` in its record). A result made under an older generation is refused: `run` stops instead of recording it done,
  `confirm` refuses it, and a child run whose parent's hold moved on does not close or land.
- **Scopes are keys.** A task with `scope` (`add --scope`, or a plan task's `scope`) also holds `scope/<path>` per entry;
  a take whose scope overlaps (one holds the other) a live scope held by another session gives every key back and is
  refused. An unscoped task meets its overlap at the merge, as before.
- `lease-ttl`, `lease-ceiling`, `lease-max`, `lease-remote` sit beside `lease`.

**The argv backend contract.** `settings.chongdae.lease: ["cmd", "arg", ...]`; chongdae appends one operation and reads one
JSON object from the last line of stdout. Exit non-zero (or no JSON): the store could not be reached.

```
cmd take    KEY --holder H --ttl S --gen N [--task T] [--scope P] [--over G --why W] -> {"ok": bool, "lease": L|null}
cmd renew   KEY --holder H --gen N                                                  -> {"ok": bool, "lease": L|null}
cmd release KEY --gen N [--by B]                                                    -> {"ok": bool, "lease": null}
cmd list    PREFIX                                                                  -> {"leases": [L, ...]}
cmd prune   PREFIX --age S                                                          -> {"pruned": [KEY, ...]}
```

H is the holder as JSON (`{"machine", "session", "agent"[, "by"]}`); `--task` and `--scope` are stored as the lease's own
fields, so a lease (and the record made from it) has one shape whatever the backend. `take` succeeds when KEY is absent,
released, held by the same machine and session (it answers the hold as it is), or lapsed by the service's clock (`from:
{holder, gen, lapsed: true}`); it stores a lease of the shape above with `gen` = max(N, the stored gen + 1) (N is one more
than the generation chongdae last recorded; a released key's marker keeps the stored gen). With `--over G` it succeeds only when the current
generation is G — a break — and records `from: {holder, gen, broken: W}`. `renew` succeeds when the current lease has gen
N and the same machine and session, and sets `renewed` and `last-progress`. `release`, when KEY's gen is N, replaces the lease with the
released marker `{key, released, gen: N, by: B}` — it keeps the generation. `list` answers every lease (markers may be
included; chongdae leaves them out) whose key starts with PREFIX; `prune` deletes released markers older than S seconds. Keys are `<run>/<task>` and `scope/<path>`, each part
percent-encoded. Otherwise `ok: false` with the current lease, so chongdae can say who holds it.

**The remote** — `settings.chongdae.remote`:

| `remote` | after each judgment's record commit | a push that fails | before a claim, an `add` or a `run` step |
|---|---|---|---|
| absent | nothing is pushed | — | — |
| `"sync"` | pushed to the branch's remote (else `lease-remote`, else origin) | said, with how many commits are not there; the next judgment pushes again | — |
| `"shared"` | pushed | fetch, reconcile (fast-forward or merge), push again; still refused: the command stops (exit 2) and says to fetch, reconcile and push | fetched and taken (fast-forward or merge); a conflict stops |

Declaring `sync` or `shared` is the project's consent to chongdae pushing its records; absent, chongdae never pushes. Whatever
`remote` says, the SessionStart line and `close` say when the branch has no upstream or holds commits its upstream has not
(from the last fetch; see `close`). Under
either, a task named with `add` is committed and pushed at once (absent, it waits for the run's next commit as before), so another
machine can claim it. A claim under a lease adds no commit anywhere — `git log main` holds the runs' judgments and the merges; a break is a
judgment, and is committed.

## Git as notary

Every judgment is one record-only commit, made by the engine itself: `init`, `confirm`, `accept`, `retry`, `dispute`, `drop`,
a task's `done` in `run`, `did`, `close`, `complete`, `claim --break`, and a worktree run's landing each commit `.chongdae/run-<id>/` — that path pinned, so someone
else's work in flight is never swept in (the one addition: what the reviewer wrote when the run ended goes into the
close commit). A `done` reached in `run` is committed when it is made (guin-site run-20261015-054352-a0ec: five tasks' done
results waited, and landed in a commit titled "accept decisions on cache-build (delegated)"). A record file is written only
when what it says changed, so a task nobody judged again keeps the `written_by` that wrote it (guin-site d281c8a: a `did` on one
task restamped six done and dropped tasks 1.19.0 -> 1.20.0). `init` and `close` name the run's goal in the commit, so the log reads without opening the record.
git's immutability then notarizes the judgment: its content, its time, any later edit as a visible diff. Durability is
the engine's, not a habit of whoever remembered to commit (best effort: no repo or an identity-less git config never
stops the run; the reviewer sees uncommitted records as what they are).

Order between machines is never a clock's. Every judgment carries `at` in UTC — for display and honesty only — and so do
the moments `show` reads durations from: a task's `done`, each attempt's `answered` (the hands' answer came back) and
`verdict-given` (the verifier's), the run's `ended`. The
run's place in history is `created: {at, based_on}` (the commit it started from) and, when a worktree run lands,
`landed: {at, commit}` (the merge commit, pinned into the record in main): ancestry decides, run-id timestamps only
approximate. `git log -- .chongdae/run-<id>` joins the record to the changes.

The work itself is the session's to commit, and its subject has its own form: `run-<id>/<task> (session): <what>` — never
the engine's `run-<id>: …`, which is chongdae's record commits only. `run` (when it makes a task done) and `close` (when it
stops on uncommitted work) print the exact `git add -- FILE…` and `git commit -m "…" -- FILE…` for each task.

## Commands

Each runs the engine and shows its output. `chongdae.py --help` for arguments; every command takes `--target DIR` —
by default the nearest directory at or above the shell's that holds `.chongdae/` (a `cd tests` does not lose the run),
else the shell's own. The hooks anchor the same way: their payload's `cwd` is the shell's, so the project is the nearest
ancestor holding `.chongdae/`, else git's top level (guin-site, 2026-10-02: after `cd tests` the write hook found no run
there and would refuse writes during a running run). A shell inside a run's worktree anchors to that worktree.

**Who signs a judgment.** `--by NAME` writes a person's name. Left out, the session signs as itself — `{"agent":
"claude-code claude-opus-5-5"}`, its host and model as chongdae knows them (the host's env and the session's transcript) —
and `show` and `report` say `the session (claude-code claude-opus-5-5)` where a person's would say `NAME`. That holds for
every judgment the session can make alone: `add --role session --why`, `take`, `drop`, `retry`, `claim`, `adopt`,
`dispute`, `unstage`. Until 1.17.0 an omitted `--by` wrote git user.name, so on guin-site 73 of 80 self-performed records
— and the drops, takes, claims and adopts the session decided — read as the owner's decision. Where a person's judgment
is required, the gates (`confirm`, `accept`), `--by NAME` or `--delegated` is still required. `report` lists each
judgment the session signed as an observation (`session-judged`), so a reviewer reading delegations does not take them
for the owner's.

### `/chongdae:init`

Start a run: `--session` (with `--from plan/PLAN.md` when a plan document exists: tasks `--closes Q-…` and the people
hired get those sections as the contract), the bootstrap plan (`--goal`), `--plan FILE` or `--plan -`, or `--merge
[--base REV]`; `--worktree` for the run's own worktree + branch; `--parent RUN/TASK` for a child run that does one task
of another run (above: Runs)

### `/chongdae:add`

A task in the session run — `--brief`, `--closes`, `--check` (repeatable argv), `--tests`, `--gate
human`; its start snapshot is taken now. `--tests` is two things, and `add` prints which: for a nitpick task (or any task
no `--check` decides) the tests it writes; for a task with a `--check`, files it may not change — its judgment restores
them if it does. A task that corrects tests therefore names them without a check: guin-site's `tests-fix` (2026-10-02)
named the files it corrected with `--tests` and a check, and its own judgment restored its fix. `add` refuses that shape
when an open build's judgment just restored those files, and points at `dispute`. Who does it is the lock's to say: a task with `--check` goes to the lock's
`implementer`, a task that writes `--tests` that do not exist yet to its `nitpick`, anything else (a plan section, a
model) to this session. `--requires network loopback` says what the work requires of the sandbox its hands run in: it
travels in the request as `needs` (a task's `needs` in a plan already names the tasks it waits for), and a hired member
that cannot give it refuses before starting — chongdae sends it to the lock's alternate that can, or the session takes it
(below, `retry`), instead of resending. A role may hold capability alternates in the lock's `roles`: `"implementer@loopback"`
(the same member on a host whose sandbox can bind a port), `"<role>@<cap>+<cap>"`. A task that requires capabilities is
sent to the alternate whose capabilities cover them (the smallest set), else to the plain role as before; `add` says which
key does it, and the record keeps it (`performed_by.as`; `show` prints `implementer@loopback → …`). hunsu passes such
keys through to the lock unchanged. A check is one command: a shell line (`sh -c 'a && b'`) is refused — give each command its own
`--check`. `--role nitpick` with a `--check` is refused (a nitpick task is decided by its tests being red before the
build; a task with a check is a build). `--role` names a declared role outright; `--role session` where the lock
declares a provider needs `--why` (and `--by`) — recorded on the task as `self-performed`, reported as an observation,
its reason counted like a delegation's (one reason stamped on task after task is one decision claiming to be many).
`--before`/`--after` name the roles hired around it.

`--role subagent` hands the task to **the session's own sub-agent** (the host's Agent tool): declared hands, not
self-performed — recorded as `performed_by: {provider: subagent, host, model}` (the session's host and model; chongdae sees
the session and the tree, not the sub-agent, and says so in a non-claim), counted in `show` (`N by the session's
sub-agents`) and `report` (`subagent`, an observation), never in `self-performed`. A lock role may name it as its
provider (`"implementer": "subagent"`): a task with `--check` then goes to a sub-agent with no `--why`. Where the lock
declares someone else for the task, `--role subagent` records whose place it took (`dispatched`). Like the session's own
tasks, its start is taken at `add` and `run` decides it from the tree. guin-site run-20261004-144130-9035: the owner asked
the session to dispatch its work; 11 sub-agents did 14 tasks, all recorded as the session's own with no checks.

`--scope PATH...` names the files and directories the task's hands own. While scoped tasks are open, a changed file is
the open task's whose scope holds it — the narrowest entry — instead of whichever task finishes first: a finishing task
leaves a file another open task's scope holds more narrowly (not counted, not pinned away). A file two open tasks'
scopes hold alike, or one in no scope while scoped tasks are open, stays with the finishing task by its window and is
said in `run`'s output (`note: scope: …`) with the `adopt` that settles it; a file held alike stays in the other task's
measure too until then. Unscoped tasks with no scoped task open keep the window rule. On guin-site, concurrent sub-agents
needed `adopt` to split the files each had been told were its own

A scope entry that is a record path — another product's files: `hunsu.json`, `hunsu.lock.json`, `mangsang`, … (the lock's
`record-paths`) — makes those files the task's work: inside its own scope a record file is counted in `touched`, gets its
commit lines, and does not leave the task held as changing nothing; outside every task's scope a record stays nobody's, as
before. `add` says so when a scope names record paths. A no-check task held because what changed is records outside its
scope is told that, with the `adopt` that gives them to it. guin-site run-20261015-094800-de3e: `plugins-lock`
(`--scope hunsu.json hunsu.lock.json …`) and `site-build-stale` (`--scope mangsang`) recorded `touched: []`, were held as
"has changed nothing of its own", became the reviewer's objections, and got no commit lines.

A repository inside the project that its own git does not hold — a directory with its own `.git` that the project's status
names as one untracked or ignored entry, as a workspace of sibling repositories keeps them — is measured like the project:
a task's start keeps each one's commit (`start-heads`, beside `start-head`), its changes and its commits since are the
task's `touched` by their path from the project (`engine/src/gate.py`), its commit lines run there (`git -C engine add -- …`),
`adopt` finds them, and the verify request names the commits the work started from (`since`) so the eyes diff from there.
sagoforce 10-26, six repositories in the workspace's `.gitignore`: 43 of 47 tasks recorded `touched: []`, the verifier
accepted 24 empty packets (one over a 33-file change), no commit lines were printed and `adopt` refused a file committed in
one. A submodule is the project's own (its gitlink is tracked); a shell left in a directory below the project is still in
it for the task's trace. The trace reads the session's sub-agents too — Claude Code keeps each beside the session's
transcript (`<session>/subagents/agent-<id>.jsonl`) — so their edits are in the task's `changed`: the same day's eight
fix batches, done by sub-agents, were in no trace.

A task with no `--check` whose scope (or, at its finish, whose changed files) falls under a check the project declares —
hunsu.json `settings: {"chongdae": {"checks-for": {"<path prefix>": "<command>"}}}`, e.g. `{"lexicons/": "python3
tests/run.py records"}` — is offered it: `add`, a held `run` and the finish print `chongdae add TASK --check "<command>"`.
`add TASK --check C` on an open session task that has no check, with nothing else given, attaches it (`checks-added` in the
record; `--why` where the lock declares an implementer, as for `--role session`); the check decides the task from then on.
chongdae cannot know a project's test layout, so the project says it once. guin-site's `lexicon-descriptions` changed 8
lexicon JSON files with no check and became a carried objection, though the project runs a test group over `lexicons/`.
Where the lock declares an implementer, a task added with no check is told the implementer takes a task a check decides
(`--check C` sends it this one): sagoforce's repair run added every task with none, and hacheong was never sent one.

**Tests the contract deletes.** A contract that retires code can retire its tests: the task that writes the contract's
tests deletes them. A build's protected test that is absent, and that the task which wrote the build's tests deleted (it is
in that writer's `touched` and gone from the tree), is *deleted by the contract*. `add` (or `run`, when the deletion came
after `add`) says so once (`note: … deleted by the contract`) and keeps it on the task (`deleted-tests: {path: writer}`);
the request leaves it out of `tests` and sends it as `deleted-tests: [paths]` (hacheong keeps them absent and skips them
in red-before-build); a tests task's own retry sends what its earlier attempt deleted the same way. Nothing restores or
demands them: `add --tests` naming such a file is accepted, `run` does not stop because it is missing, and a build that
recreates one is refused like a build that changes its tests — the file is removed again (`rejected.removed`). guin-site
run-20261012-052255-3556: the tests writer deleted four retired test files that were also in the build's `--tests`; the
build was refused because its protected tests did not exist, and the session dropped it and added it again without them.

**`--closes` needs a contract document.** The sections a task closes come from the run's plan document (`init --session
--from PLAN`, a plan's `from`). In a run without one — or when the document has no `## Q-…` heading for a closed id —
`add` says so, and `run` refuses to send a quibbler (the task's role, or one hired `--before`) or the verifier a request
whose contract is missing the sections: it stops for the session with the fix (start the run with `--from`, add the
section to the document, or put the section's text in the brief and drop `--closes`). guin-site
run-20261012-052024-de21: a session run started without `--from`; the quibble got `contract: {}` and answered that the
contract was empty

### `/chongdae:claim`

Take a task for this machine (`--by NAME`; left out, the session claims it on this machine, signed as itself; an empty
string releases). `run` skips tasks claimed by someone else; chongdae never assigns. Without a lease setting the claim is
written in the record, as before (`--list` shows the record's claims). With `settings.chongdae.lease` it is a hold in the
lease store: `claim TASK` takes, `claim --list` shows every hold (age, last progress, lapsed, long-held; `--prune`
deletes released markers older than `lease-ceiling`), `claim TASK --release` gives it back, `claim --break TASK --why WHY` takes over a live hold as a recorded judgment (Many machines on
one plan, above)

### `/chongdae:take`

The session finishes a task its hired hands could not — the work is in the tree, and a drop would record it as not done
(three of guin-site's drops on 2026-09-30 were done work: a worker's sandbox could not open a port, a tests worker's guard
read the tree the session was also writing). `--why` is required: the task becomes the session's, recorded as
`self-performed` instead of its role (the reviewer counts it); the stopped attempt, and who made it, stay in `attempts`;
`run` then decides it like any session task — its checks, the verifier, the gate. Every stop on a provider's unfinished
answer names it beside `retry`. chongdae takes a task itself the same way when a member's sandbox lacked a capability and
the lock has no alternate that can (`taken.by: chongdae`, `taken.for-lack`)

`--checked "COMMAND"` (repeatable, also on `retry`): chongdae runs the command itself in the project, now, and records
its exit code and output's end in the task (`checked`) — evidence chongdae saw, where a worker's `verified` is its word. A
failing one refuses the take (or retry) and records nothing; so does a timeout (`CHONGDAE_CHECK_TIMEOUT`, 1800 s) or a
command that is not there. One command, run without a shell: `&&`, `|`, `;`, a redirect or a leading `VAR=` is refused —
give each its own `--checked`. The verifier gets them with the files changed since; they belong to the attempt they were
run for, and a retry moves them there. On
guin-site the session took a build, ran the full test run itself, and had nowhere to put it: the verifier rejected the
builder's old claim three more times

`--checked-red "COMMAND"` (repeatable, also on `retry`): a tests task's expected red run — `--checked` records only a pass,
so the red run a tests task exists for had nowhere to go. chongdae runs it the same way; a non-zero exit is recorded as
`red as expected`, a zero exit as `passed before the build` (both recorded, `expect: fail` and `outcome` on the entry); a
command that is not there or times out did not run, and refuses. `take` without either prints both, so the session that
ran something knows where it goes; `show` prints what was checked

### `/chongdae:dispute`

`dispute BUILD --tests FILE... --why WHY [--by NAME | --delegated WHY]`: some of an open build's protected tests
contradict the contract (or cannot run here). A provider's build says so in its answer (`disputed-tests`); this is the
same route for a build the session performs, or for a person. Recorded as a judgment: the task that wrote those tests —
nitpick's task, or a tests task the session took or did itself — is reopened with the dispute (`amending`); with none on
record, a tests task `<build>-tests` is made for the lock's `nitpick`, else the session, and printed. The build waits for
it; once it is done, the build takes the amended files as its contract (its start and its kept copies are re-baselined),
so its next judgment keeps the fix instead of restoring it. When the session amends, `run` stops until the disputed files
differ from what the build protected — a fix already in the tree counts. guin-site, 2026-10-02: a session build found two
test errors and a parser the machine could not load; each judgment restored the tests, and dropping the build, adding a
fix task (with `--tests`, by mistake) and dropping that too took about an hour. A dispute naming a file the build does not
protect is refused with the next step: if an open build protects it, the dispute that names that build; if none does, it is
not the contract — change it in this task, as its work

### `/chongdae:adopt`

`adopt TASK FILE... --why WHY [--by NAME | --delegated WHY]`: a judgment that these files are TASK's work. Two open
session tasks share one tree and each measures `touched` from its own `add`, so the tree cannot say whose a change is when
both were open — nor whose work was written before its task was added (the contract edited before its task, the order slip
every guin-site review found: it sits in that task's start snapshot, and its measure counts nothing there). `adopt` moves
the attribution: out of every other task's `touched` (each keeps a `gave` record), pinned into an open one's start, out of
TASK's own start, and into TASK (`adopted`, with who and why, and where from). A file nothing in the run or the tree
changed is refused. `run` says when it cannot tell: a finishing task that counted a file another open session task's brief
(or the tests it writes) names, and that changed after that task was added or was already changed when it was, prints a
`note:` with both `adopt` commands — and the file is not pinned away from the other task (that would be a guess); it stays
in both measures until the judgment. A verify request carries `attribution` (adopted, pinned at another task's finish,
held at start) when `touched` alone would mislead. guin-site run-20261002-065900-f588: escape-tests finished first and
counted `src/lib/outputs.ts`, written for escape-build before it was added; escape-build's diff was empty, the verifier
rejected it on every retry, and the drop-and-add that followed recorded nothing

### `/chongdae:drop`

A session task that will not be done (mis-specified, superseded, abandoned): `--why` is recorded, the task leaves the
open set as `dropped`. The alternative was closing the run around it — open forever, nobody looking. When the task's hands
changed the tree, `drop` says so and points at `take`: work that stands is done, not dropped

### `/chongdae:did`

`did TASK [--why WHY] [--approved-in source:ID] [--by NAME] (-- COMMAND... | --each FILE)`: an operation outside the repository — a deploy,
a secret deleted, a remote database changed — run through chongdae for a task. Everything after `--` is the command's own
argv, run once in the project with no shell (a `&&`, `|`, `;`, redirect or leading `VAR=` is refused, as for `--checked`)
and no input; the task gets, whatever the exit, a `did` entry:

    {"command": "wrangler d1 delete guin", "exit": 0, "tail": ["…last 6 lines…"], "at": "…+00:00", "chongdae": "…",
     "why": "retire the old D1", "approved-in": "source:at-63", "signer": {"agent": "claude-code claude-opus-5-5"}}

(`why` and `approved-in` only when given; `signer` is `--by NAME`, else the session; `ran: false` when the command was not
there or timed out). It is printed, and committed like any judgment; `did` exits 1 when the command did. `show` prints
each one with its output's end; `report` lists every `did` of a run as an observation, and one with a non-zero exit as an
objection (it left the outside in a state nobody has looked at), saying `no approval cited` when none was. guin-site
run-20261012-052255-3556: the cleanup's eight operations (an archive, the deploys, secrets, Access, R2 and D1 deleted) ran
as plain Bash in a todo task and survive only as prose in a plan file

A file outside the project that the command names (`python3 /private/tmp/…/empty_r2.py`: a script in a scratchpad) is written
`<outside:empty_r2.py>` in `command`, and the entry keeps what it was under `outside`: `{arg, name, role, sha256, size, content}`.
Only the program the command runs (`role: program`) keeps its `content` — argv[0] when it is a `#!` script, or the first
non-option argument after an interpreter (`node`, `python3`, `bash`, `sh`, `deno`, `bun`, `ruby`, `perl`, `npx tsx`, …) — its
text when it is text and at most 32,000 bytes, with this machine's paths taken out (`content-portable` says so; the sha256 is
the file's as it ran). Every other outside file is data the command was given (`role: argument`): its sha256 and size, and
`not-kept: an argument, not the program`. Nothing is kept, the program included, when the file's name looks like secrets
(`.env`, `.env.*`, `.dev.vars`, `*.pem`, `*.key`, `id_rsa*`, a name with key, secret, token, credential or password in it) or
its text does (a line `NAME=value` whose NAME says TOKEN, SECRET, KEY, PASSWORD or PRIVATE; a `-----BEGIN … PRIVATE KEY-----`
block; a `ghp_`, `sk-`, `xoxb-` or `AKIA…` token): `not-kept: looks like secrets`. The command line and the tail are read for the
same patterns and a matched value is written `NAME=<masked>` (or `<masked>`); `masked` counts them and `did`, `show` and
`report` say so. guin-site 10-16: `did lexicon-publish -- node <scratch>/publish_lexicons.mjs ./lexicons/… <the PDS's
.dev.vars> --write` kept the secrets file passed as data whole in the committed record, and the report said "it ran a file outside the
project, .dev.vars" — it now says which file was the program run and which was an argument. `did` prints what it kept, `show`
and `report` say it. The tail is the output's last six meaningful lines: blank lines, rules (`─────`, `=====`) and a tool's
version banner (`⛅️ wrangler 4.143.1 (update available 4.149.0)`) are left out. The commit's subject is cut at argument
boundaries: the command's head words, a `…`, its last word (a long path as its name) — never inside a word, a quoted argument or
an `<outside:…>` marker. guin-site run-20261012-052255-3556 kept only the machine path of the script that emptied the R2 bucket,
its subject cut mid-name ("…/scratchpad/empty"), and two lines of banner and rule as the tail of each deletion; f3beee0's subject
ended `'<outsi… --write`.

A done task that mentions an operation and has no `did` — its brief or role holds one of a small list: `deploy`, `push`,
`publish`, `migrate`, `delete` (the verbs, not "deployed"), `배포`, `푸시`, `삭제`, `마이그레이션` (not as a modifier: "배포 버전",
"배포한 …", "삭제된 …"); a task its checks decide is a build and is not read — is only a lexical hint in `report`
(`operation-mention`, layer `observation`). It never stops `close` or creates missing-operation debt: a filename such as
`deploy.yml`, or the subject of an edit such as “미배포”, does not establish that an operation was intended or executed.
Actual operations still go through `did`, whose exit and output are evidence; never repeat an operation to clear a word match.

`did` saves its intent before execution and each batch item's observed result before starting the next item. If its
caller is interrupted, `did TASK` recovers known results without executing any supplied command. An item with no
observed result is unknown, even if its process has stopped; the task cannot advance or close while that
operation remains unresolved. Inspect its external effects and ensure it has stopped, then use
`did TASK --reconcile ID --why "what was checked"`. This executes nothing and retains an unknown exit with the reason;
it does not convert an unobserved outcome into success. Issue any remaining operation deliberately after reconciliation.
If the original session ended, `take TASK --why "recovery handover"` transfers an idle interrupted operation's task
without running checks or changing its completion status. The pending journal stays intact for the new owner's
reconciliation. Live workers and live foreign leases still prevent a handover.

`--each FILE` (or `--each -`, stdin): several operations as one judgment — one command per line (no shell line; blank lines and
`#` comments skipped), each recorded with its own exit and tail (`batch: {of, n}`), all in one commit. A non-zero exit stops the
rest, which are said as not run: what comes after a failure is not run on a state nobody has looked at. guin-site's R2 emptying
and deletion, one decision, were two commits

### `/chongdae:unstage`

Take a role hired `before` or `after` a task off that task, with `--why`: a role that cannot do its work here (a
newbie on a project with nothing a newbie can run). The task goes on; the record says the role did not look (a
non-claim), and what it answered before it came off stays under `stages-taken-off`

### `/chongdae:close`

End the session run (open tasks recorded as open); the lock's `reviewer` is placed (below); a worktree run merges back
— `--run ID` names a completed one. The commit names the goal: `run-…: close — <goal> (N done, M open)`

Three stops before it is final, all the session's (`decision: session agent: …`), never a person's question:

- **Other owners or active hands.** An unfinished task owned by another session, a live foreign lease, a running
  checker/provider, an unanswered native dispatch, or an unfinished host sub-agent task keeps the run open. `--anyway`
  cannot override this: wait for the hand-back and `run TASK`, or explicitly hand over idle work with `take --why`.
  Stop a cancelled sub-agent before dropping its task. Ordinary open tasks owned by this session and with no active
  hands can still be left open in a closed record; this does not mark them done.
- **Work not committed.** A finished task's work — its `touched`, anything under its `--scope` — that differs from HEAD stops
  the close, with the files, their tasks and the commands, a commit per task: `git add -- FILE…`, then
  `git commit -m "run-<id>/<task> (session): <its brief>" -- FILE…`. That subject is the form for the session's commits of a
  task's work; `run-<id>: …` is chongdae's own record commits (guin-site 10-15: the agent copied the engine's prefix in
  737db95 and made up `run:` in 33b5bda, and `git log` could not tell them apart). `run` prints the same two lines when it
  makes a task done with its work uncommitted. The record is committed by
  chongdae; the work is the session's to commit, and a close over uncommitted work closes on work no commit holds. guin-site
  run-20261012-052255-3556 closed with plan/ATPROTO.md (cleanup-ops' scope and `touched`) edited and uncommitted. A worktree run
  is exempt: its merge-back commits the worktree.
- **What the reviewer finds the tree can answer.** The reviewer runs with the run ended, before the commit. An open objection
  (layer `objection`, no disposition, not a carry) of a kind the tree can answer now — `cq-failed`, `cq-drifted`,
  `invariant-failed`, `stale`, `broken`, `contradiction`, `record-vs-tree`, `plan-vs-code`, `anomaly` — stops the close: each
  is listed, the run stays running, and what the reviewer wrote for this close is taken back (a file it created removed, one it
  changed put back to HEAD), so the next close's review is not based on a review of a close that did not happen. The session
  fixes them and closes again. A non-claim, a delegation or a carried charge is a person's to dispose and never stops it.
  guin-site run-20261012-052255-3556: two cq-failed arrived with the close commit and were fixed outside any run. The count is
  the reviewer's own (dwitbuk's `count_text`): each open charge once under the kind of charge it makes — a carry (`undisposed`)
  under the kind it carries — kinds sorted, then how many of them are carried: `cq-failed 2, non-claim 10; 3 of them carried,
  already in the count`; two copies of one charge count once.

`close --anyway --why WHY [--by NAME]` closes with uncommitted work or reviewer objections standing, never other owners
or active hands: recorded in state.json `closed-anyway` (why, by, the
uncommitted files, the standing objections, at) and said as a non-claim.

The close then says, in one line, when the branch has no upstream (`main: no upstream`, when the repository has a remote) or
commits its upstream has not (`main: 213 commits not on origin/main (as of the last fetch)`) — read from the local
remote-tracking refs, never a fetch, whatever `settings.chongdae.remote` says; level, nothing. The SessionStart line says the
same. guin-site: 213 commits sat unpushed for 10 days, main had no upstream, and nothing said so.

### `/chongdae:report`

What this record says a reviewer should see, typed `dwitbuk/findings@1`: outside-run, unattributed, delegated,
self-performed (with who decided it: `NAME`, or `the session (<host> <model>)`), session-judged (a drop, take, claim,
retry, adopt, reopen or dispatch the session signed as itself — an observation, carrying `by`), subagent (a task the
session's sub-agent did — an observation), did (an operation run with `did` — an observation; an objection when it
exited non-zero), operation-mention (an operation word in a done task with no `did` — an observation, not evidence of execution), verifier-non-claim (what a
verifier says it did not do, such as an accept without reading the tree — an observation), stage-finding, verifier-reject (every rejected attempt's findings), left-open, non-claims (the same
sentence on several tasks of a run is said once, with the tasks), unreleased-writer (a committed record a working
source wrote) — with `--since REV`, changes since that revision and the runs whose record was not complete there
(earlier runs were the previous review's). Only those runs claim a change since REV: an earlier run's `touched` names
paths it worked on before the review, and once hid any later change made there outside a run. Declared as a reporter in hunsu.json; dwitbuk collects it without knowing
chongdae

### `/chongdae:status`

The run in progress (or the newest) and its open tasks; never fails

### `/chongdae:show`

What happened in a run, for whoever reads it after — a person, or an agent that would otherwise `cat` the task files and
guess their keys (a retrospective of one day on guin-site took ~50 tool calls that way). Read-only, plain text, nothing
cut. `--run ID` (default: the running run, else the newest): the goal, kind, created (time, the commit it started on), when
it ended and how long it took; each task in order — who did it (role → provider, host, model; or the session, and why it
took the work), every attempt with its answer, its verdict and every finding whole, the retry, accept, confirm and drop
judgments with who made them or the delegation's words, the checks and what the record says of them, the touched files and
the times; then what is left (open tasks, what the reviewer said at close). A run recorded before chongdae kept these times
is timed from its own record commits, and says so. `--since REV`: one line per run whose record was not complete at REV
(the runs `report --since` reads) — goal, status, tasks done/dropped/open, self-performed and taken, attempts, verifier
rejects, delegated judgments, duration — and a totals line. `--path FILE`: the runs and tasks whose `touched` holds that
file (or a file under that directory), newest first, with who did each. A judgment that moved a file (`adopt`) is told on
both tasks, and a file two open tasks measured is told as not settled. A task's `did` operations, what chongdae ran for it
(`--checked`, `--checked-red`) and the tests the contract deleted are told with it. A child run names its parent
(`parent: run-… / task T1`); a parent lists its children and their states, read from the children's records.

`--brief` is the reader's first look, one line per fact (jokbo's `note` and `map` reads; full outputs pasted into an
agent's context were ignored): `show --path FILE --brief` prints at most two lines — `last changed in run-… (date), task ID:
<brief>` and, if any, a task that changed it and is open or dropped now — said only while its run is open or it ended in
the last 7 days, and only when no done task changed the file after it (guin-site, 2026-10-06: weeks-old drops were printed
51 times in one session) — and nothing at all when no task on record touched it; `show --brief` prints one line, `N runs (K this week), last closed: <goal> (date)` (this week: the last 7 days). The
running run and its open tasks are the SessionStart line's, and are not repeated. The manifests declare them in `reads`
(kind -> argv, for a reader plugin): `file` (`show --path {path}`), `since` (`show --since {since}`), `note`
(`show --path {path} --brief`), `map` (`show --brief`) and `hands` (`show --after {after} --hands {paths}`), each with
`--target {target}`.

`show --after ISO --hands PATH...` is jokbo's `hands` read: given paths that changed while the session was not calling (jokbo's
`{paths}`, one argument per path; `{after}`, when the session's last call left the tree, ISO UTC), it prints one JSON object
from path to whose hands this record says changed it — `{"src/worker/index.ts": "the implementer of cache-build
(run-20261015-054352-a0ec)"}` — so the change line says the session's hired worker, not "another hand" (guin-site 10-15
05:53:57: the session's own builder's two files were told as anyone's). A path is a hired task's when its provider is out now
(the task's `local/<tag>.pending.json`, its pid alive) and the file is not what it was at that provider's start, or when an
attempt answered at or after `{after}` holds it in `touched_by_provider` (or `touched`); the role is the one the task was
hired as (the lock's key). Only running runs, and runs closed within the window, are read. The session's own tasks (session,
sub-agent, taken) are never named, nor is chongdae's own run of the checks. It runs inside a hook: no git, no network, and
`{}` — never an error — when nothing is on record, `--after` does not parse, or anything else goes wrong.

### `/chongdae:run`

Advance the current run one step. Exit codes: 0 — advanced as far as it goes (a session run waiting for `add` or `close`, a
plan run complete); 2 (`DECISION`) — stopped for the session agent or a human, the last line (`decision: …`) says who and what;
4 (`WAITING`) — still working: the call's budget is spent while a provider or chongdae's own checks run, the line starts with
`still working:`, and the same command resumes the same work. A call takes at most about four minutes (`CHONGDAE_WAIT`, below).
`run TASK…` advances only those tasks. Unfinished dependencies are reported, never silently included. With no check and
no change or operation, naming a task is still the session's word that it is done (recorded as a non-claim).
Without task names, the ordinary plan can advance its ready tasks; a host sub-agent's task needs an explicit name after
the parent receives its completed result. Partial edits do not mean the sub-agent finished. In a run shared by sessions,
another session's task is left alone even when named, with changes, operations or passing checks; `take TASK --why …`
records a handover after its outstanding work has stopped. Legacy tasks with no recorded session retain the old ownership
behavior. Under a lease it advances
only the tasks this session holds (taking a ready unheld one when it holds fewer than `lease-max`) and renews a hold
where it saw progress; under `remote: "shared"` it fetches and takes the remote's record first

The same ownership rule protects judgments and task edits: `retry`, `accept`, `confirm`, `unstage`, `adopt`, `did`,
`dispute`, `drop`, and attaching checks cannot change another owner's task. A `--by` signature does not transfer it.
Adoption and disputes also check any other task they would change; generated amendment tasks retain their parent session.

**Concurrent commands in one checkout.** A record-changing command holds an OS lock at
`.chongdae/local/command.lock` from its first read through its last commit. Another such command returns exit 4 promptly,
without changing the record: retry that same command and its arguments. This prevents an old task snapshot overwriting
another session's changes, duplicate provider dispatch and competing record commits. Killing the command releases the
lock; a detached provider/check can still be resumed from its pending record. `status`, `show`, `report`, and `recheck`
remain available, and JSON files are replaced atomically for readers. Separate projects and worktrees have separate locks;
the existing leases still coordinate different machines. This lock protects chongdae commands, not arbitrary source edits.
Detached checks and providers have a durable launch intent before a process is created. An internal launcher registers
its own PID before executing the worker; recovery uses the same intent, so a caller interrupted around process creation
does not create an undiscoverable duplicate worker.
Completed worker answers and check results remain bound to that launch until the task durably acknowledges applying
them. An interrupted caller consumes the retained result on resume; cleanup cannot cause a completed worker to run again.
Changed source still invalidates the retained result and requires fresh verification.
Task records, run state, the plan, and their private overlays are saved through one local transaction journal. Readers see a
complete generation even when a writer stops between files; the next mutation or record commit finishes applying it.
The journal and source witnesses remain local and git-ignored.
Landing a worktree also acquires the destination project's lock before changing either run. Record commits use their own
temporary git index and advance HEAD only if it still names the commit they started from, so a concurrent source commit
is preserved. If HEAD moved, the judgment stays on disk for the next record commit.

Checks and verifier results belong to the source they examined. Content snapshots include ignored nested repositories
and initialized submodules, including uncommitted changes; record-only changes and committing identical source content do
not invalidate them. If source changes while checks, a verifier or an after-role runs, the old pass cannot finish the task.
Resume the named task after its writers stop: checks and affected reviewers run again. The same rule applies while a
produced task waits at its human gate: changed source returns it to work before a fresh confirmation. Scopes declare
ownership rather than dependencies, so changes elsewhere in the source tree conservatively invalidate a running review.

**Parallel implementation and independent review.** Add each implementation task before dispatch, with disjoint scopes
and `--role subagent`. Keep the task owned by its parent session; workers return their result to that parent. When A
finishes while B is still editing, `run A` must leave B open. After the writers finish, launch fresh reviewers in parallel
with the requirements and the resulting code; keep those reviewers read-only. Apply their findings as implementation
work and review the changed result again. Use named `run` calls for the completed pieces. A second parent in the same
project keeps its own tasks in the shared run; independent projects use independent runs. Finish outstanding workers and
reviews before closing the shared run.

### `/chongdae:delegate`

A batch pre-approval declared once as its own judgment (`--scope confirm,accept,retry --why "…" --by NAME`; one
record, one notary commit) — it prints `D-xxxx`, and every later judgment in that run references it with `--delegated
D-xxxx` instead of pasting the reason. Per run: a delegation belongs to the run it was declared in. `report` flags one
reason string stamped on 3+ judgments as `delegation-stamp`

### `/chongdae:confirm`

Record a human's confirmation of a produced artifact or passed task (`--by NAME`, or `--delegated WHY` / `--delegated
D-xxxx`)

### `/chongdae:accept`

Accept decisions a provider made beyond the contract (after writing them into the plan)

### `/chongdae:retry`

Send a stopped or rejected task out again (`--by NAME`, `--delegated WHY`, or left out: signed by the session — a retry
is not a gate); the earlier attempt (and its review) stays in the record and travels with
the next request. `--requires CAP...` says on the task what its sandbox must give, when a member's sandbox lacked it: the
task's `requires` grows, the request names it, and the lock's `<role>@<cap>` alternate, when there is one, is hired. A
member that stopped mid-task because its sandbox lacked a capability (status `blocked` or `failed`, `lacked: ["loopback"]`,
a non-claim starting `sandbox lacked: `) is a hiring stop like a refusal before starting: the stop names the capability
and nothing is resent to the same member. When the lock has the `<role>@<cap>` alternate that can, the task requires CAP
now and goes there with no stop (`retried.by: chongdae`, the attempt kept): the lock is the person's hiring, already
decided. With none, no person is asked mid-run: a run must go on without stopping for one, and what a project does about a
capability its members' hosts lack is decided once, at setup — hunsu.json `capabilities` (`{"loopback": "session" |
"alternates", "network": ...}`, written by hunsu; hunsu.local.json overlays it, as for settings). Decided `session`, or
not decided, the session takes the task: recorded as taken and self-performed with the reason (`dakdol on codex lacked
loopback; no implementer@loopback in the lock (hunsu.json capabilities: loopback: session)`), and `run` stops only for the
session to do the work (`decision: session agent: …`) — then its checks, the verifier and the gate decide it as for any
task. `report` adds one observation per run: `taken for lack: N task(s) — <role> lacked <cap> (no <role>@<cap>;
capabilities: <decision>)`, so a review sees what the setup cost without it being a charge. Two stops go back to the hands without a person, twice per task at most: a verifier's reject (its
findings attached) and an answer a validator refused for naming a check the session did not run — that one only when
the task's checks fail here too: chongdae runs the checks itself, and when they pass the refusal was about the
report's spelling of a command, not the tree; the report stands with the mismatch on record (`checks-ran-overruled`, a
non-claim). Past that, the stop is a person's. When the hands are the session itself, a reject stops at once — the
session reads it and fixes the tree; resending would only run the verifier again on the same tree. A builder that
disputes a contract test (`disputed-tests`) sends it back to the task that wrote it: that task reopens with the
dispute (`amending` in its request), rewrites the test, the build re-baselines the file and goes out again; with no
writer on record the stop names `dispute`. A session task is measured again at `retry` — the measure is kept with the attempt
(`retried.measured`) and printed, and the files its own word names that the measure leaves out (already changed when it
was added, or pinned into its start when another task finished) are named with the `adopt` that settles them: resending
the same empty `touched` only gets the same reject

### `/chongdae:recheck`

Re-run every completed run's checks on this tree (the merge plan's first check); exit 1 if any is red now

## Files in your project

The engine-owned `plan.json`, `state.json` and `tasks/<id>.json` are public projections. This machine's project root,
home, temporary directories and plugin-cache paths become `.`, `~`, `<tmp>` and `<plugin:NAME@VERSION>` only where
a path begins (including a `**`-wrapped path at a path start); a relative path merely containing such a segment is kept.
Exact raw strings live in ignored `local/plan.json`, `local/state.json` and `local/tasks/<id>.json`; the engine reloads
them for CLI use. Raw provider requests, responses and transcripts stay exact in ignored `local/` storage.
A public dict key that would hold a machine path is refused (`MachinePathKey`), never renamed.

Supported worktree landing (`close`'s merge-back) writes into the main checkout's local overlays only raw strings
whose public value is their projection, for that run's state, task and plan files. It transfers no private state,
journal, leases, acknowledgements or worker artifacts. A run merged by hand, or read on another machine, has only
its public projection there; a check whose argv named machine-specific paths may not rerun there.

`asked/`, `contract/`, `delegations/`, `reviews/` and report output are outside this normalization. Only `**` emphasis
is recognized: other Markdown, HTML and ANSI markup is not parsed, so a machine path behind it can stay public.
Backslash (Windows-style) handling is tested only with mocked strings, not on a live Windows host; drive-letter
or case variants and UNC paths are not recognized.

### `.chongdae/run-<id>/plan.json`

Committed: yes.

the intent: goal, tasks (role, what closes, checks or artifact path, gate), providers

### `.chongdae/run-<id>/tasks/<id>.json`

Committed: yes.

one file per task (so two people's tasks in one run merge as distinct files): status, claim, touched, response,
review, `stages` (the before/after roles' answers and who gave them), attempts, confirmation, non-claims,
`self-performed` (the session took a task the lock had hired someone for, and why), `dispatched` (a sub-agent stood where
the lock declared someone else), `def.scope` (the files its hands own), `done` (when it became done),
`answered` and `verdict-given` (when an attempt's answer and its verdict came back; a retried attempt keeps both),
`did` (operations outside the repository chongdae ran for it, with any script outside the project under `outside`), `checked`
(what `--checked`/`--checked-red` ran), `checks-passed` (the task's own checks as chongdae last ran them green: what the verifier
is told), `overruled` (the verifier's findings chongdae overruled, and why),
`deleted-tests` (its protected tests the contract deleted, and which task did), under a lease `gen` and `lease` (the
generation its result was made under, and how that hold began) and `lease-breaks` (each `claim --break`: from, gen, why,
by) — what this machine holds now (`lease-held`) stays in `local/`,
`performed_by` and `verified_by` —
each author line with its `trace` (the files that call changed, how many commands it ran and how many failed) — and
for session tasks the task's own definition

### `.chongdae/run-<id>/asked/<tag>.json`

Committed: yes.

what a provider was asked — the request with this machine taken out (`.`, `~`, `<plugin:…>`, `<tmp>`), so a reader on
another machine sees the question as it was put, not this machine's paths. Its `contract` points at `contract/`. A
record for reading; no command replays it

### `.chongdae/run-<id>/contract/<Q>-<hash>.md`

Committed: yes.

a plan section as a request carried it, kept once per run per text: three tasks closing one section point at one file;
a section the plan changed between two calls is there twice

### `.chongdae/run-<id>/local/`

Committed: no (`.chongdae/.gitignore`, one line, written by chongdae).

**the work**, apart from the record: each request as sent and each response as written (`<tag>.request.json`,
`<tag>.response.json`, an attempt's under its number), the worker's whole session (`<tag>.response.transcript.jsonl`,
megabytes, this machine's paths), the pending pid and the provider's log while a call is out, and
`local/tasks/<id>.json` — this machine's overlay of a task: the host session behind each author line and the one that
added it (`added-in`), the `start`
snapshot a task measures from, the command lines behind each `trace`, the flags the engine keeps between two `run`
calls. The engine reads it back here; nobody else can open a session or needs a snapshot once `touched` is written.
Files an earlier version kept beside the record (`*.trace.json`, `*.request.json`, …) stay where they are; an ignored
one leaves the index at the next record commit

### `.chongdae/sessions/<session id>.json`

Committed: no (ignores itself).

written by the SessionStart hook: where this host keeps that session's transcript, so a session task can name its
model

### `.chongdae/run-<id>/state.json`

Committed: yes.

the run's status, `created`, `ended`, `closed-anyway` (a close with uncommitted work or answerable objections standing, and why), `environment.locked` (the lock every call ran under — a task's author line says `locked`
only when its call ran under another), `reviewed` (what the reviewer said and wrote when the run ended), `parent` (a
child run's `{run, task[, gen]}`; a parent keeps nothing of its children), `landed`
(older runs kept their tasks here; still read)

### `.chongdae/run-<id>/delegations/D-<id>.json`

Committed: yes.

a declared delegation: scope, why, by, at. `report` prints `by` and `why` beside every judgment that references it

### `plan/questions.json`, `plan/PLAN.md`

Committed: yes.

the bootstrap's artifacts — the project's, not the run's

**Which chongdae wrote it.** Every record file says `written_by: chongdae <version>` — with `+g<sha>[-dirty]` when a
working source wrote it — and every judgment (`created`, `confirmed`, `accepted`, `retried`, `dropped`, …) carries the
version that recorded it beside its `at`: one run can span versions. `settings.chongdae.commit-records: false`
(hunsu.json, or this machine's overlay in hunsu.local.json) writes records without committing them. `report` names any
committed record written by a build that is not a release (`unreleased-writer`). A check given with this machine's
paths is recorded portably — an installed plugin's path as `{plugin:NAME}`, the home as `~` — and resolved again where
it runs.

**Who did it** is recorded on every produced task like a commit's author line. A session task: `performed_by:
{provider: session, agent: <host_version_kind from AI_AGENT>, effort, model}` (the host session id stays in `local/`)
— the host does not tell its subprocesses the model, so it comes from the session's transcript (the SessionStart hook
records where it is; Codex: the thread's rollout); a session the host did not persist gets `model-unknown` with the
reason, never a guess. A command task: `{provider: command, argv: <the un-resolved argv>, host, model, turns,
cost_usd}` (its session and transcript in `local/`) — the argv is portable, the rest is the worker's own account of
its call (`worker` in its response). A verifier's call is recorded the same way as `verified_by`.

**The run is the agent's container.** The plugin's PreToolUse hook refuses Edit/Write in a project with no run in
progress (the record, `.claude/` and `hunsu*` are exempt — their own engines write them); the SessionStart line says
which run is open (not inside a worker session, `AGENT_WORKER=1`: the run is the hiring session's). So runs must be cheap: `init --session` opens one with no plan, `add <id>` names each piece as the
work starts (a task with no check is allowed — done is then the agent's word, recorded as a non-claim), `run` records
what each piece touched (since its start, committed or not: work committed before `run` is still the task's), `close` ends it. A task's word stays its own: when a task is done, the files it recorded are
measured from there for the session tasks still open, and a no-check task that changed nothing of its own and has no `did`
is not done by a `run` that did not name it — it stays open, the pass goes on to the next task, and the call ends (exit 2)
with how to finish it: do the work; an operation through `did TASK -- COMMAND` first; work that leaves nothing in the tree
(a decision, an answer) by naming it, `run TASK` (the session's word, said as a non-claim). guin-site
run-20261015-054352-a0ec: the `run` for cache-comment also made cache-ops done (touched [], no `did`) two minutes before its
deploy, its push and its Done line. A session build's `--tests` must exist when it is added (its
start is taken then); write them in their own task first. Bash writes are not covered; dwitbuk's `outside-run` catches
them. A task claimed by someone else (`claim`) is not this machine's to advance.

**An operation run as plain Bash reaches no record.** A second PreToolUse hook reads each Bash command while a run is in
progress; one that reads as an operation outside the repository — `git push`, `npm run deploy`, `npm publish`, `wrangler
deploy`/`publish`/`… delete`, `terraform apply`, `kubectl apply`, `gh release create`, `fly`/`vercel`/`netlify`/`firebase
deploy` — gets one line of context: `record it: chongdae did TASK --why "…" -- <command>`. Never a refusal, silent with no
run and in a worker session (`AGENT_WORKER=1`), silent on `chongdae.py did` itself — the engine named or kept in a variable
(`python3 $C did …`), the line read command by command with its quotes (sagoforce 10-26: a push given to `$C did` was told
"record it", and pushes after `$C close` were not told they ran after close). hunsu.json
`settings.chongdae.ops-patterns` (a list of regular expressions searched in the command) replaces the list; `[]` silences it.
guin-site run-20261015-054352-a0ec ran `npm run deploy … | grep …; git push 2>&1 | tail -1` — both exits lost — and wrote
the push into ATPROTO.md as prose. An operation that comes after a `chongdae … close` on the same line runs outside any
run, where no `did` can record it: the line then says `this git push runs after close, outside any run — move it before
close as did TASK -- git push` (guin-site 10-15: `…run; git commit; close; git push`, told "record it", pushed after the
close).

Under hunsu's probe (`HUNSU_SURVEY=1`: hunsu runs the SessionStart hook in an empty project to judge what it tells a
session) the hook prints its standing text — the run-in-progress line, the no-run line and the upstream lines, as
templates with no live run id, goal, count or branch — and writes nothing, so the judge reads what chongdae can say in any
state, not the one state an empty project shows.

**What a project does by its own procedure** is not a run's. A site's posts are its author's, written by the project's
own guide, and the pages built from them follow; a run around each would put the author's writing in the builders'
ledger. The project declares those paths once, in hunsu.json `settings: {"chongdae": {"outside-runs": ["content/",
"docs/"]}}` (read there — with this machine's overlay from hunsu.local.json on top — not from the lock):
project-relative files or directories, an entry that leaves the project names nothing. The write hook lets them
through without a run, and `report` leaves them out of `outside-run` — saying so in one `non-claim` with how many
files it left out, so a reviewer sees the boundary rather than a silence.

A merge run's plan has one task — chongdae's own `recheck`, plus whatever the lock's `coherence` role names (argv with
`{base}`; e.g. mangsang's `observe --reset --at {base}` and `impact`) — behind a human gate. No `coherence` role: the
plan says so as a non-claim.

`recheck` re-runs every completed run's checks on the merged tree; a run's `done` was true on its own branch and must
be true again. Red normally means fix the tree, not the record. The one other reading: a red check whose contract was
since amended (the plan moved on and the check now measures a superseded promise) is disposed of in the merge run's
human review — the reviewer says so at the gate; neither the tree nor the old run's record is edited to make it green.

## Providers

A role's provider is `session` (the agent driving this run writes the artifact) or a command — argv with `{request}`
and `{response}` — that gets a `chongdae/request@1` file (task, brief, the plan sections it closes, its checks) and
must leave a response with `status`, `summary`, `verified`, `decisions`, `non-claims`. A non-empty `decisions` stops
the run until a human `accept`s — or rejects the work: reset the tree and `retry` (the attempt, decisions included, stays
in the record). A provider's `non-claims` belong to its attempt: a retry moves them there, and the task keeps only what is
still true; a writer reopened to amend keeps its earlier list, less what its new answer restates (the contract sentence
an old line leads with, quoted again — one new line replaces at most one old). The verifier gets the builder's
non-claims (`built`) and the tests writer's (`tests_non_claims`); when it accepts (a verdict chongdae observed, not one
the session wrote for a native subagent), both tasks' are marked `seen-non-claims` for that attempt (a retry moves the
mark with it), and `report` says them in one `seen-non-claims` observation with a
count per task — read by the eyes placed for it, not charges a person disposes again (175 of 281 review charges in one
guin-site cycle were these). What a role hired `after` a task found is printed by `run` as well as filed. A role with no provider is
skipped and recorded as a non-claim; nothing stands in. `tests` holds one path per entry — a shell-joined list is refused
— and a build whose protected tests are not in the tree when it starts stops there: the guard would watch nothing.

A command provider runs **detached**: its own session, output to `<tag>.provider.log`, its pid in `<tag>.pending.json`
written before `run` waits on it. A `run` that is killed leaves the provider working; the next `run` finds the pending
record and resumes waiting (or consumes the response that landed meanwhile) instead of paying for the work twice. What
detaching does not survive is the host session ending — on macOS a session's exit took its providers with it, detached
or not; that is what the bounded wait below is for. `run` waits for the process to end, not for the file to appear —
half an answer is not an answer (its own child is poll()ed, never left a zombie).

**What a call ran with.** `performed_by` and `verified_by` carry `versions`: chongdae itself and each plugin the
provider's argv names, as installed here (`used`), and every plugin the environment lock pins with its content
fingerprint (`locked`) — to replay a call, its skills and prompts must be the same versions. A task that writes the
contract's tests has no check of its own; its request (and its quibbler's) carries the check of the build that
protects the same files. `add --domain site` (or `code`, `plan`, …) says what kind of artifact the task makes; every
request for it carries the domain, so a worker reads the task in that domain's terms.

**People hired around a task.** A task may list roles to run `before` the work and `after` it (`"before":
["quibble"]`, `"after": ["newbie"]`; a plan's `stages` gives defaults for tasks that say neither; `add --before
quibble --after newbie` in a session run). A `before` role sees the contract and answers with findings; a finding is a
plan question, so the task waits — the hands do not move — until a human decides each in the plan and `accept`s
(`--by` or `--delegated`). An `after` role sees the result (touched files, the builder's report) once the checks and
the verifier are through, before the gate; its findings go to the record and to `report` as `stage-finding`, never a
verdict. Each answer is kept under the task's `stages[role]` with who gave it; a role with no provider is a non-claim.
hacheong's 시비 (`quibble`) and 초짜 (`newbie`) are the first of these. A contract reader added as a task of its own (`add q
--role quibble --closes Q-…`) is sent its role as the `stage`, no checks or tests of its own, and the open builds' checks that
close the same sections labelled as planned (`checks-are: planned: the checks of …`) — or `checks-are: not named yet` when none is
added: guin-site's cache-quibble was sent `stage: build` and its own `checks: []`, and half its findings were "checks가 []라서…".

A third kind: **`native:plugin:role`** — the host's own subagent does the work, dispatched by the session. chongdae
cannot call a host's subagent tool (it has no brain and no host API), so it writes the same request, then stops with a
`decision:` naming the worker's `--prompt-only` argv and the response path; the session gets the prompt, gives it to a
fresh subagent of its host (Claude Code: the Agent tool; Codex: `spawn_agent`), writes the subagent's final JSON
answer verbatim where a worker would have, and `run` consumes it like any provider's. Attributed `performed_by:
{provider: native, argv, relayed_by: <the session's own author line>, …}` plus a non-claim: the answer was written by
the session on the subagent's behalf; chongdae did not observe the subagent. What you gain: no nested host process
(which has failed in tested sandboxed Codex sessions), the host's own concurrency and permissions. What you lose: chongdae's own
record of the call (turns, cost, transcript) unless the subagent's answer carries a `worker` block — the relay is on
the record so the loss is named, not hidden.

A fourth: **`subagent`** — the session's own sub-agent works in the session's tree, as the session would: no request, no
response file, the task decided by its checks (or its word) when `run` comes to it. `performed_by: {provider: subagent,
host, model, …}`. Where `native:` relays a worker's prompt and its JSON answer, `subagent` is for work the session itself
dispatches and reads back; it is always at hand (`--role subagent`), and a lock role may name it.

A plan may declare a `verifier` role — a command, never the hands that built (dwitbuk's `eyes_worker.py` is one).
After a task's checks pass and before its gate, the verifier gets the contract, what the task touched (and what
changed after the builder answered, told apart), what the record paths left out of `touched` (`excluded.record-paths`:
the environment — hunsu's manifest, lock and judgments — and records such as `mangsang/`, which are never a task's work
by rule; a task whose whole work is `hunsu lock` has `touched: []`, and without this the verifier read the changed tree as
an undeclared edit) and the builder's report, and what chongdae itself ran on the tree and saw (`checked`: `{command, exit,
tail, at, changed_since, source}` — the session's `--checked` and the task's own checks chongdae ran to decide it; guin-site
run-20261015-054352-a0ec's verifier was told nothing of the suite chongdae had just run green), and answers `dwitbuk/review@1`: accept, or
reject with findings quoted from both sides. Reject is the failed path: `retry`. Before acting on a reject chongdae holds each
finding to its quotes: a finding whose `where` names a field of the request and whose record quote (each backticked span, or
the whole) is not in the request's own words — or is only in another hand's (`tests_non_claims`, `checked`) that `where` does
not name — and a `claim-unverified` about a check `checked` shows passing with nothing changed since (unless it quotes the
contract sentence the check may not decide), are overruled: printed, kept on the task (`overruled`: each finding and why) and
said as a non-claim. A reject with nothing left standing goes on as accepted (a delegated `after-verifier` gate counts it so);
otherwise only the standing findings are resent, each printed whole. guin-site: the verifier quoted "`built.non-claims` says: `I
did not run the whole suite.`", a sentence only `tests_non_claims.cache-tests[8]` held, and the build was resent for it. What the
verifier's own runner dropped as unfounded (`unfounded` in its answer) is printed and shown. What the verifier says it did not
do — the verdict's `non-claims`, such as dwitbuk's "accepted without reading the tree: …" — is printed, kept on the task as
`(verifier) …` (a resend takes it off with the review it came with), and is an observation in `report`
(`verifier-non-claim`), not a charge. A resent build's `touched` for the verifier is every attempt's: a file an earlier attempt
of the builder changed counts while it still differs from the task's start (guin-site run-20261015-054352-a0ec's second
verify request said `touched: []`, the builder's files under `touched_since`). After a reject the next verification
is a re-verification: the request carries `recheck` — the last reject's findings and the files changed since that verdict
(the tree is kept at each verdict) — and the verifier checks those, not the whole slice again. A task's `tests` are the contract's
own checks, as they are in the tree when the task starts (committed or not — kept then among the run's work files): a
build that changes them, or puts them back to HEAD, is rejected by chongdae, which restores them from what it kept. A gate written `{"human": true, "delegate":
"after-verifier"}` refuses `confirm --delegated` until an accept; a plain `"human"` gate records what stood in
(`verifier: accept` or nothing).

**The reviewer is placed by the runner.** A review that waits for someone to ask for it is never asked for (a site
went 22 runs without one). When a run ends — a session run's `close`, a plan run's `complete` — chongdae runs the
lock's `reviewer` role in the project (a command, like `coherence`: `"reviewer": ["python3",
"{plugin:dwitbuk}/dwitbuk.py", "review", "--target", "."]` in hunsu.json `roles`). Whatever it wrote there is part of
the closing record and goes into the close commit with it; what it said last is kept in state.json `reviewed`. No
`reviewer` in the lock: a non-claim on the run, printed at its close only when the run that ended before it did not
carry it — it is the lock's, the same until the lock changes (a day's ten closes said it ten times), and `hunsu check`
says it once. A reviewer that fails: a non-claim too — the run still ends. The
reviewer places no person's stop; what its findings need from a person is the reviewer's own business (dwitbuk says so at the
next session start). At a session run's `close` it runs before the close is final, and an open objection the tree can answer
stops the close for the session (above, `/chongdae:close`).

`run` takes up to four minutes per call (`CHONGDAE_WAIT` seconds, default 240 — one budget for the whole call, from its start:
chongdae's own checks, the verifier and however many providers it starts all count), then stops with `still working: …` (exit
4, not 2): well under a host's 10-minute tool limit. The task's checks run as a tracked process of their own
(`<task>.checks.pending.json` in `local/`), like a provider: past the budget the call hands back, and the next `run` waits for
the same run — never killed mid-way, never started twice — and reads what it found (run again only if the tree changed after
they finished). Checks that passed on this tree are not run again when a later call resumes at the verifier. guin-site, 10-15:
one call ran the suite (~4.5 minutes), the verifier (~1 minute), resent the build and waited 240 s more — 8m35s; and a backgrounded
`run` said "still working" on a `decision:` line, the wrapper around it exited 0, and it read as done
(guin-site, 2026-10-12: at eight minutes `run` came close enough that the session wrapped it in polling loops of its own); the pending record lets the next `run` resume
waiting for the same work. Keep `run` in the foreground and resume it with the same task selection;
its tracked workers run detached. Detachment is not a guarantee that workers survive host-session cleanup,
as described above, and a shell wrapper must not hide the command's exit status.

A provider call that stops (`blocked`, `failed` — out of budget, say — or no response) is not retried on its own: a
human `retry`s it. The stopped attempt moves to the task's `attempts` and its files move aside under the attempt's
number; the next request carries every attempt's report and what the tree already differs in (`touched`), so a slice
that spans two calls resumes from the tree and the record, not from anyone's memory. A retry keeps a `before` role's
answer when the contract it answered — the brief, checks and the sections the task closes — is unchanged, and hires
the role again only when it changed.

## Limits

- No brain: chongdae never writes a plan, a question, or code. It refuses a plan whose tasks have no way to be
  decided.
- Names no product: every provider — the bootstrap's `session`, a builder, a verifier, the merge's coherence check —
  comes from the plan's `providers` or the lock's `roles`. chongdae names only itself (`recheck`).
- Checks and providers are argv that must exit 0. `{plugin:NAME}` uses local links, chongdae's own root, or the
  Claude installation registry; Codex-only installations need local links as described in
  [host entry points](#shared-instructions-and-host-entry-points). A plan never carries a machine path. A check that measures
  nothing passes; name what a check covers (a test runner that fails when a key selects no tests).
- Not built yet: re-planning on failure, the ideation branch when the goal is under-shaped.
- Leases: the git backend has no server clock — a lapse is the machines' clocks, so keep `lease-ttl` generous or declare a
  service. A child's parent task is decided by the parent's own `run` (its checks on the merged tree), not by the child's
  landing. A version of chongdae before 1.20.0 does not know a lease: every machine on one plan runs 1.20.0 or later.

- **The other products' records** — what a task's `touched`, `outside-run` and the snapshots leave out — come from the
  lock: `record-paths` in hunsu.lock.json, each plugin's own `records` declaration. A project whose lock has no such key gets
  the names as they were (`.mangsang/`, `.dwitbuk/`, `reviews/`). What the reviewer writes at close is a record and still
  goes into the close commit. chongdae declares `records: [".chongdae/"]` itself.

## Versioning

Semver, and a version names one content: every change to the source — code, skill or command text, hooks, this README
— bumps
the version in all three manifests (`plugin.json`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`) and the
marketplace entries before it is used anywhere. Hosts copy a plugin at install and do not look again while the version
stands,
so an unbumped edit is a copy nobody can tell from the old one. **patch**: behavior or wording, every interface
unchanged.
**minor**: a new command, skill, field, hook or artifact key; what exists keeps working. **major**: an artifact type,
lock or
record that other products read changes shape. Dropping a supported Python version or host version is also a major
change: raising `engines.python`, or requiring a newer Claude Code or Codex. See [Install](#install) for the current floor.
hunsu's `check` fails a linked plugin whose source differs from the
installed
copy under one version; for a locally linked plugin, `hunsu install --refresh <plugin>` re-snapshots after the bump.

### Release and adoption

Documentation and shared instruction edits also need a patch bump when interfaces stay unchanged.
Keep the version equal in `plugin.json`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`,
and `.claude-plugin/marketplace.json` (both `metadata.version` and this product's `plugins[].version`).
`.agents/plugins/marketplace.json` currently has no version field; verify its product name and source path,
but do not invent a version field there.

Before publication, run the relevant checks in **Self-check** for behavior changes; for documentation-only
changes, verify links, command examples, imports and manifest consistency, plus `git diff --check`.
Publish the checked commit using this repository's existing release convention. Publication does not update
consumer installations: update the plugin through the host's supported workflow, reconcile the consuming
project's declared environment and lock if managed, and start a new host session to apply the installation.
Report publication, project adoption and live-host verification separately. Refreshing a locally linked
plugin is not an update procedure for every remote installation.

## Self-check

`python test_chongdae.py` — a temp project; every stop, rejection and kind of finding fires once, with recorded
provider responses where a model would have answered. No model calls.
The same entry point also runs the subprocess concurrency, review freshness, and record-transaction suites. Each can be
run separately with `python test_concurrency.py`, `python test_review_freshness.py`, `python test_record_transactions.py`,
or `python test_launch_recovery.py` (fault injection around detached process creation).
It also includes `test_state_recovery.py`, `test_completion_recovery.py`, `test_mutation_ownership.py`,
`test_operation_recovery.py`, and `test_operation_handover.py` for interrupted state saves, result consumption,
task mutation authority, operations, and recovery in a replacement session.
`test_public_projection.py` also runs through this entry point, covering public records and their local overlays.
