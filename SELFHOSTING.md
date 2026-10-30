# Maintaining chongdae with chongdae

Start with [AGENTS.md](AGENTS.md) for source maintenance and [README.md](README.md)
for contracts, [providers](README.md#providers), and [limits](README.md#limits).
Follow the shared [run skill](skills/run/SKILL.md) for orchestration.
This entry records this checkout's environment and maintenance constraints.

## Installed release and working source

[hunsu.json](hunsu.json) declares the environment; [hunsu.lock.json](hunsu.lock.json)
locks hunsu 1.15.1, chongdae 1.24.0, mangsang 1.19.3, jokbo 1.8.1,
hacheong 1.12.1, and dwitbuk 1.16.0, installed at project scope for Claude Code.
Use each locked plugin's `<root>` from the SessionStart line to call its engine;
never select an engine with a glob over the plugin cache.

This checkout is the source of the next chongdae. The installed locked release N
(currently chongdae 1.24.0) orchestrates every change to it, producing N+1;
never orchestrate with this checkout's `./chongdae.py`.
N+1 manages nothing, not even the next change, until it is bumped in every manifest,
published, installed, re-locked by hunsu, and loaded by a new session.
Follow [versioning](README.md#versioning); version bump, push, and release are separate steps.
`source_revision` in `chongdae.py` marks an engine run from working source with
`+g<sha>[-dirty]`; `.chongdae/run-*/state.json` records its writer in `written_by`.
Testing working source with `python3 test_chongdae.py`, as AGENTS.md requires for
behavior changes, is not orchestration; see [self-check](README.md#self-check).

The environment requires Python >=3.11 and claude-code >=2.1.
The released 1.24.0 (commit `c1c3f63`) declared Python >=3.9 in `plugin.json` and
`.claude-plugin/plugin.json`, and >=3.11 in `.codex-plugin/plugin.json`.
Source now declares >=3.11 in all three manifests. Dropping Python 3.9/3.10 is a major
change under README's [versioning](README.md#versioning).

## Roles and checks

The manifest and lock declare identical roles:

| Role | Provider |
| --- | --- |
| planner | session |
| implementer | hacheong dakdol on codex |
| nitpick | hacheong teujip on claude |
| quibble | hacheong sibi on claude |
| newbie | hacheong chojja on codex |
| verifier | dwitbuk eyes_worker.py on claude |
| reviewer | `dwitbuk review --target .`, run by chongdae at close |
| coherence | `mangsang impact --target .` |

No role passes `--model`; model workers use their host's default model.
Reporters are `hunsu check --findings --target .`,
`chongdae report --since {since} --target .`, and `mangsang impact --findings --target .`.
These names denote the corresponding Python engines at their locked roots.
Both `capabilities.loopback` and `capabilities.network` are `session`.
All five resolutions are `reviewed: false`; `hunsu policy` prints them.

## Before future work

Before any write in a prospective run, use the locked chongdae root:
`python3 "<root>/chongdae.py" init --session --goal "..." --target .`.
The chongdae PreToolUse hook refuses ordinary source Edit/Write without an open run.
Add a task before its work; `adopt` work predating its task with a `--why` naming its author.
Commit only that task's own paths, with subject `run-<id>/<task> (session): ...`;
never use `git add -A`. Keep outside-run edits unstaged as someone's prior work.
A documentation-only task needs no tests writer: say so on the task and decide it
with link/manifest checks. `close` runs the declared reviewer.

## Observed limits of this environment

A Claude Code session launched from a Codex parent inherits `CODEX_THREAD_ID`.
In chongdae 1.24.0, `performer` honors `AGENT_HOST` first, otherwise that marker
selects codex and its thread's model. Export `AGENT_HOST=claude-code` before calling
engines in such a Claude session. Run `run-20261030-065818-2049`, task `adopt-env`,
records `codex gpt-6-astra`; commit `4de6d33` carries the provenance correction.

The recorded `AGENT_HOST=codex hunsu check` exits 1 with "content differs" for hunsu,
mangsang, and jokbo: their Codex installs add root `.codex-marketplace-install.json`,
which hunsu 1.15.1 counts in its content fingerprint. This awaits a hunsu repair;
do not use `--take-content` to bypass it. The recorded Claude-host check passes.
Codex project hooks (`.codex/hooks.json`) are written only by `hunsu lock` from a
Codex session; this project has none. `{plugin:NAME}` resolves through Claude's
install records; Codex-only installs need `hunsu.local.json` links (see README limits).

mangsang has no model here yet: no concepts and nothing registered.
An impact report of 0 unresolved therefore means nothing is watched, not coverage.
