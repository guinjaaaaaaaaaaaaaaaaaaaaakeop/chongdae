# chongdae

The orchestrator for an era where development is split into parts done by agents. Runs a plan — a DAG of roles with checks in code and human gates in between — and records the run apart from commit history: what was decided, by whom, and what was not verified.

## Install

```
claude plugin marketplace add guinjaaaaaaaaaaaaaaaaaaaaakeop/chongdae
claude plugin install chongdae@chongdae
```

Codex: `codex plugin marketplace add guinjaaaaaaaaaaaaaaaaaaaaakeop/chongdae`, `codex plugin add chongdae@chongdae` (the skill is `$chongdae:run`).

## Runs

A run is the unit of judgment; commits are the unit of change. Three kinds, plus the default. `init --goal "..."` alone starts the **bootstrap** plan (questions -> plan document -> modeler; question ids are semantic — `Q-drafts`, never a bare number, so parallel workers' ids don't collide at a merge). `init --plan FILE` (or `--plan -`: the plan on stdin — intent written before its run exists needs no file in the tree) runs a **plan** the session agent wrote. `init --session` opens a **session** run: no plan, tasks added as the work goes. `init --merge [--base REV]` is a **merge** run: two branches were each right alone; someone must say this tree is right again.

`init ... --worktree` makes the run's container physical: its own worktree and branch (`run/<run-id>`) under `.chongdae/wt/`, from HEAD or from `--base REV` (two independent slices branch from one commit) — a shared tree may have other workers, and it is not this run's to dirty. Every later command takes `--target <that path>`; the write gate inside the worktree is that worktree's own run. `close` merges it back — a session run when you close it, a plan or bootstrap run once `run` completed it: commit the worktree, `--no-ff` merge into main, recheck there. Clean merge + green recheck removes the worktree and branch; a conflict or a red recheck comes back as a `decision:` — resolve in main and `init --merge`, and the worktree stays until the merge landed.

## Git as notary

Every judgment is one record-only commit, made by the engine itself: `init`, `confirm`, `accept`, `retry`, `drop`, `close`, `complete`, and a worktree run's landing each commit `.chongdae/run-<id>/` — that path pinned, so someone else's work in flight is never swept in. git's immutability then notarizes the judgment: its content, its time, any later edit as a visible diff. Durability is the engine's, not a habit of whoever remembered to commit (best effort: no repo or an identity-less git config never stops the run; the reviewer sees uncommitted records as what they are).

Order between machines is never a clock's. Every judgment carries `at` in UTC — for display and honesty only. The run's place in history is `created: {at, based_on}` (the commit it started from) and, when a worktree run lands, `landed: {at, commit}` (the merge commit, pinned into the record in main): ancestry decides, run-id timestamps only approximate. `git log -- .chongdae/run-<id>` joins the record to the changes.

## Commands

Each runs the engine and shows its output. `chongdae.py --help` for arguments; every command takes `--target DIR`.

| command | does |
|---|---|
| `/chongdae:init` | Start a run: `--session` (with `--from plan/PLAN.md` when a plan document exists: tasks `--closes Q-…` and the people hired get those sections as the contract), the bootstrap plan (`--goal`), `--plan FILE` or `--plan -`, or `--merge [--base REV]`; `--worktree` for the run's own worktree + branch |
| `/chongdae:add` | A task in the session run — `--brief`, `--closes`, `--check` (repeatable argv), `--tests` (protected files), `--gate human`; its start snapshot is taken now. `--role session` (default: this agent does it) or a role the lock names a provider for (`--role implementer`: the locked hands build it from the brief and checks, in this run); `--before`/`--after` name the roles hired around it |
| `/chongdae:claim` | Take a task (`--by`, default git user.name; empty string releases). `run` skips tasks claimed by someone else; chongdae never assigns |
| `/chongdae:drop` | A session task that will not be done (mis-specified, superseded, abandoned): `--why` is recorded, the task leaves the open set as `dropped`. The alternative was closing the run around it — open forever, nobody looking |
| `/chongdae:unstage` | Take a role hired `before` or `after` a task off that task, with `--why`: a role that cannot do its work here (a newbie on a project with nothing a newbie can run). The task goes on; the record says the role did not look (a non-claim), and what it answered before it came off stays under `stages-taken-off` |
| `/chongdae:close` | End the session run (open tasks recorded as open); a worktree run merges back — `--run ID` names a completed one |
| `/chongdae:report` | What this record says a reviewer should see, typed `dwitbuk/findings@1`: outside-run, unattributed, delegated, stage-finding, verifier-reject (every rejected attempt's findings), left-open, non-claims — with `--since REV`, changes since that revision and the runs whose record was not complete there (earlier runs were the previous review's). Declared as a reporter in hunsu.json; dwitbuk collects it without knowing chongdae |
| `/chongdae:status` | The run in progress (or the newest) and its open tasks; never fails |
| `/chongdae:run` | Advance the current run one step; exit 2 = stopped for the session agent or a human |
| `/chongdae:delegate` | A batch pre-approval declared once as its own judgment (`--scope confirm,accept,retry --why "…" --by NAME`; one record, one notary commit) — it prints `D-xxxx`, and every later judgment in that run references it with `--delegated D-xxxx` instead of pasting the reason. Per run: a delegation belongs to the run it was declared in. `report` flags one reason string stamped on 3+ judgments as `delegation-stamp` |
| `/chongdae:confirm` | Record a human's confirmation of a produced artifact or passed task (`--by NAME`, or `--delegated WHY` / `--delegated D-xxxx`) |
| `/chongdae:accept` | Accept decisions a provider made beyond the contract (after writing them into the plan) |
| `/chongdae:retry` | Send a stopped or rejected task out again; the earlier attempt (and its review) stays in the record and travels with the next request. Two stops go back to the hands without a person, twice per task at most: a verifier's reject (its findings attached) and an answer a validator refused for naming a check the session did not run; past that, the stop is a person's. A builder that disputes a contract test (`disputed-tests`) sends it back to the task that wrote it: that task reopens with the dispute (`amending` in its request), rewrites the test, the build re-baselines the file and goes out again |
| `/chongdae:recheck` | Re-run every completed run's checks on this tree (the merge plan's first check); exit 1 if any is red now |

## Files in your project

| path | committed | what |
|---|---|---|
| `.chongdae/run-<id>/plan.json` | yes | the intent: goal, tasks (role, what closes, checks or artifact path, gate), providers |
| `.chongdae/run-<id>/tasks/<id>.json` | yes | one file per task (so two people's tasks in one run merge as distinct files): status, claim, start snapshot, touched, response, review, `stages` (the before/after roles' answers and who gave them), attempts, confirmation, non-claims, `performed_by` and `verified_by` — and for session tasks the task's own definition |
| `.chongdae/run-<id>/<task>.session.trace.json` | yes | a session task's trace, cut from the host transcript at the task's start: the project files it changed and how many commands it ran there — its command lines stay in the local transcript (a session's lines carry everything else it was doing) |
| `.chongdae/run-<id>/<tag>.trace.json` | yes | what a worker did, from its session: the model, the commands it ran with their exit codes, the files it changed (and read, where the host says) — the project as `.`, home as `~` |
| `.chongdae/run-<id>/<tag>.response.transcript.jsonl`, `<tag>.request.json`, `*.provider.log`, `*.pending.json` | no (`.chongdae/.gitignore`, written by chongdae) | the worker's whole session and the request as sent — this machine's paths, often megabytes; kept here for a local audit, summarized into the trace. A copy an earlier version committed leaves the index at the next record commit |
| `.chongdae/run-<id>/<tag>.pending.json`, `<tag>.provider.log` | yes | a detached provider in flight: its pid and start snapshot, and its output — how a killed `run` finds the work again |
| `.chongdae/sessions/<session id>.json` | no (ignores itself) | written by the SessionStart hook: where this host keeps that session's transcript, so a session task can name its model |
| `.chongdae/run-<id>/state.json` | yes | the run's status, `created`, `landed` (older runs kept their tasks here; still read) |
| `.chongdae/run-<id>/delegations/D-<id>.json` | yes | a declared delegation: scope, why, by, at |
| `.chongdae/rechecks/<time>.json` | yes | a `recheck`'s verdict: which completed runs' checks were green, red or without checks on that tree, at that HEAD |
| `plan/questions.json`, `plan/PLAN.md` | yes | the bootstrap's artifacts — the project's, not the run's |

**Who did it** is recorded on every produced task like a commit's author line. A session task: `performed_by: {provider: session, agent: <host_version_kind from AI_AGENT>, effort, session: <host session id>, model}` — the host does not tell its subprocesses the model, so it comes from the session's transcript (the SessionStart hook records where it is; Codex: the thread's rollout); a session the host did not persist gets `model-unknown` with the reason, never a guess. A command task: `{provider: command, argv: <the un-resolved argv>, host, model, turns, cost_usd, session, transcript}` — the argv is portable, the rest is the worker's own account of its call (`worker` in its response). A verifier's call is recorded the same way as `verified_by`.

**The run is the agent's container.** The plugin's PreToolUse hook refuses Edit/Write in a project with no run in progress (the record, `.claude/` and `hunsu*` are exempt — their own engines write them); the SessionStart line says which run is open. So runs must be cheap: `init --session` opens one with no plan, `add <id>` names each piece as the work starts (a task with no check is allowed — done is then the agent's word, recorded as a non-claim), `run` records what each piece touched, `close` ends it. Bash writes are not covered; dwitbuk's `outside-run` catches them. A task claimed by someone else (`claim`) is not this machine's to advance.

A merge run's plan has one task — chongdae's own `recheck`, plus whatever the lock's `coherence` role names (argv with `{base}`; e.g. mangsang's `observe --reset --at {base}` and `impact`) — behind a human gate. No `coherence` role: the plan says so as a non-claim.

`recheck` re-runs every completed run's checks on the merged tree; a run's `done` was true on its own branch and must be true again. Red normally means fix the tree, not the record. The one other reading: a red check whose contract was since amended (the plan moved on and the check now measures a superseded promise) is disposed of in the merge run's human review — the reviewer says so at the gate; neither the tree nor the old run's record is edited to make it green.

## Providers

A role's provider is `session` (the agent driving this run writes the artifact) or a command — argv with `{request}` and `{response}` — that gets a `chongdae/request@1` file (task, brief, the plan sections it closes, its checks) and must leave a response with `status`, `summary`, `verified`, `decisions`, `non-claims`. A non-empty `decisions` stops the run until a human `accept`s. A role with no provider is skipped and recorded as a non-claim; nothing stands in.

A command provider runs **detached**: its own session, output to `<tag>.provider.log`, its pid in `<tag>.pending.json` written before `run` waits on it. A `run` that is killed leaves the provider working; the next `run` finds the pending record and resumes waiting (or consumes the response that landed meanwhile) instead of paying for the work twice. What detaching does not survive is the host session ending — on macOS a session's exit took its providers with it, detached or not; that is what the bounded wait below is for. `run` waits for the process to end, not for the file to appear — half an answer is not an answer (its own child is poll()ed, never left a zombie).

**What a call ran with.** `performed_by` and `verified_by` carry `versions`: each plugin the provider's argv names, as installed here (`used`), and every plugin the environment lock pins with its content fingerprint (`locked`) — to replay a call, its skills and prompts must be the same versions. A task that writes the contract's tests has no check of its own; its request (and its quibbler's) carries the check of the build that protects the same files. `add --domain site` (or `code`, `plan`, …) says what kind of artifact the task makes; every request for it carries the domain, so a worker reads the task in that domain's terms.

**People hired around a task.** A task may list roles to run `before` the work and `after` it (`"before": ["quibble"]`, `"after": ["newbie"]`; a plan's `stages` gives defaults for tasks that say neither; `add --before quibble --after newbie` in a session run). A `before` role sees the contract and answers with findings; a finding is a plan question, so the task waits — the hands do not move — until a human decides each in the plan and `accept`s (`--by` or `--delegated`). An `after` role sees the result (touched files, the builder's report) once the checks and the verifier are through, before the gate; its findings go to the record and to `report` as `stage-finding`, never a verdict. Each answer is kept under the task's `stages[role]` with who gave it; a role with no provider is a non-claim. hacheong's 시비 (`quibble`) and 초짜 (`newbie`) are the first of these.

A third kind: **`native:plugin:role`** — the host's own subagent does the work, dispatched by the session. chongdae cannot call a host's subagent tool (it has no brain and no host API), so it writes the same request, then stops with a `decision:` naming the worker's `--prompt-only` argv and the response path; the session gets the prompt, gives it to a fresh subagent of its host (Claude Code: the Agent tool; Codex: `spawn_agent`), writes the subagent's final JSON answer verbatim where a worker would have, and `run` consumes it like any provider's. Attributed `performed_by: {provider: native, argv, relayed_by: <the session's own author line>, …}` plus a non-claim: the answer was written by the session on the subagent's behalf; chongdae did not observe the subagent. What you gain: no nested host process (a sandboxed Codex session cannot start one), the host's own concurrency and permissions. What you lose: chongdae's own record of the call (turns, cost, transcript) unless the subagent's answer carries a `worker` block — the relay is on the record so the loss is named, not hidden.

A plan may declare a `verifier` role — a command, never the hands that built (dwitbuk's `eyes_worker.py` is one). After a task's checks pass and before its gate, the verifier gets the contract, what the task touched (and what changed after the builder answered, told apart) and the builder's report, and answers `dwitbuk/review@1`: accept, or reject with findings quoted from both sides. Reject is the failed path: `retry`. A task's `tests` are the contract's own checks: a build that changes them is rejected by chongdae. A gate written `{"human": true, "delegate": "after-verifier"}` refuses `confirm --delegated` until an accept; a plain `"human"` gate records what stood in (`verifier: accept` or nothing).

`run` waits for providers up to eight minutes per call (`CHONGDAE_WAIT` seconds — one budget for the call, however many providers it starts), then stops with `still working — run again`; the pending record lets the next `run` resume waiting for the same work, so a session whose tool calls have their own timeout never has to background `run` — a backgrounded `run` outlives the session that started it only on paper; the provider is that session's child and dies with it.

A provider call that stops (`blocked`, `failed` — out of budget, say — or no response) is not retried on its own: a human `retry`s it. The stopped attempt moves to the task's `attempts` and its files move aside under the attempt's number; the next request carries every attempt's report and what the tree already differs in (`touched`), so a slice that spans two calls resumes from the tree and the record, not from anyone's memory. A retry keeps a `before` role's answer when the contract it answered — the brief, checks and the sections the task closes — is unchanged, and hires the role again only when it changed.

## Limits

- No brain: chongdae never writes a plan, a question, or code. It refuses a plan whose tasks have no way to be decided.
- Names no product: every provider — the bootstrap's `session`, a builder, a verifier, the merge's coherence check — comes from the plan's `providers` or the lock's `roles`. chongdae names only itself (`recheck`).
- Checks and providers are argv that must exit 0. `{plugin:NAME}` in an argv resolves on each machine (a local link in `hunsu.local.json`, else the host's installed plugin) — a plan never carries a machine path. A check that measures nothing passes; name what a check covers (a test runner that fails when a key selects no tests).
- Not built yet: re-planning on failure, the ideation branch when the goal is under-shaped.

## Versioning

Semver, and a version names one content: every change to the source — code, skill or command text, hooks, this README — bumps
the version in all three manifests (`plugin.json`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`) and the
marketplace entries before it is used anywhere. Hosts copy a plugin at install and do not look again while the version stands,
so an unbumped edit is a copy nobody can tell from the old one. **patch**: behavior or wording, every interface unchanged.
**minor**: a new command, skill, field, hook or artifact key; what exists keeps working. **major**: an artifact type, lock or
record that other products read changes shape. hunsu's `check` fails a linked plugin whose source differs from the installed
copy under one version; `hunsu install --refresh <plugin>` recopies after the bump.

## Self-check

`python test_chongdae.py` — a temp project; every stop, rejection and kind of finding fires once, with recorded provider responses where a model would have answered. No model calls.
