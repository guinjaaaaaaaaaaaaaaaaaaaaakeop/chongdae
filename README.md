# chongdae

The orchestrator for an era where development is split into parts done by agents. Runs a plan — a DAG of roles with
checks in code and human gates in between — and records the run apart from commit history: what was decided, by whom,
and what was not verified.

## Install

Python 3.11 or newer is required on both hosts. Ensure `python3` on the host's PATH selects that interpreter.

```
claude plugin marketplace add guinjaaaaaaaaaaaaaaaaaaaaakeop/chongdae
claude plugin install chongdae@chongdae
```

Codex: `codex plugin marketplace add guinjaaaaaaaaaaaaaaaaaaaaakeop/chongdae`, `codex plugin add chongdae@chongdae`
(the skill is `$chongdae:run`).

The repository's catalogs select `./plugin`; the host copies only that directory. Using chongdae needs no clone.
See the [plugin documentation](plugin/README.md) for [host entry points](plugin/README.md#shared-instructions-and-host-entry-points),
[runs](plugin/README.md#runs), [coordination](plugin/README.md#many-machines-on-one-plan),
[Git as notary](plugin/README.md#git-as-notary), [commands](plugin/README.md#commands),
[project files](plugin/README.md#files-in-your-project), [providers](plugin/README.md#providers),
and [limits](plugin/README.md#limits).

## Developing chongdae

Clone the source repository to develop it:

```sh
git clone https://github.com/guinjaaaaaaaaaaaaaaaaaaaaakeop/chongdae.git
cd chongdae
```

`plugin/` is the installable payload: the engine, hooks, commands, skills, three manifests, README and LICENSE.
It is the only runtime source. The root holds the marketplace catalogs, tests, [AGENTS.md](AGENTS.md)/[CLAUDE.md](CLAUDE.md),
[SELFHOSTING.md](SELFHOSTING.md), the development environment's `hunsu.json`, `hunsu.lock.json` and
`hunsu-judgments.json`, and records such as `.chongdae/` and `reviews/`.

The root `chongdae.py` is only a shim that runs `plugin/chongdae.py` and is not installed;
`python3 chongdae.py --help` works in a checkout. An engine run from this checkout names itself
`+g<sha>[-dirty]`, with `-dirty` counting only uncommitted changes in `plugin/`, so its records never
pass working source off as a release.

Read [AGENTS.md](AGENTS.md) for maintenance rules and preparing the declared development environment
with released plugins. The installed release orchestrates development; the checkout is the source under test.
Development pins stay at their released versions until adoption.

## Versioning

See the [plugin's versioning policy](plugin/README.md#versioning) for semver and Python/host floors.

### Release and adoption

Documentation and shared instruction edits also need a patch bump when interfaces stay unchanged.
Keep the version equal in `plugin/plugin.json`, `plugin/.claude-plugin/plugin.json`, `plugin/.codex-plugin/plugin.json`,
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

`python3 test_chongdae.py` — a temp project; every stop, rejection and kind of finding fires once, with recorded
provider responses where a model would have answered. No model calls.
The same entry point also runs the subprocess concurrency, review freshness, and record-transaction suites. Each can be
run separately with `python3 test_concurrency.py`, `python3 test_review_freshness.py`, `python3 test_record_transactions.py`,
or `python3 test_launch_recovery.py` (fault injection around detached process creation).
It also includes `test_state_recovery.py`, `test_completion_recovery.py`, `test_mutation_ownership.py`,
`test_operation_recovery.py`, and `test_operation_handover.py` for interrupted state saves, result consumption,
task mutation authority, operations, and recovery in a replacement session.
`test_public_projection.py` also runs through this entry point, covering public records and their local overlays.

`python3 test_payload.py` also runs through that entry point. It copies only `plugin/` to a temporary
directory outside the repository and runs the CLI workflow and hooks there; it checks that manifests, hooks
and catalog selections resolve inside the payload and that the payload contains no development state.
