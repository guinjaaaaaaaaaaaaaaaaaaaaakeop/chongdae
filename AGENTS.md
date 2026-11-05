# Working on chongdae

This is the shared source-checkout guidance for Claude Code and Codex. `CLAUDE.md`
imports this file; keep maintenance instructions here. Installing the plugin does
not automatically load this file into a user's project.

- Read [plugin/README.md](plugin/README.md) for contracts, host adapters, limits and versioning.
  The installed workflow is [run](plugin/skills/run/SKILL.md); keep its procedure shared
  between hosts, with enforced sequencing and gates in `plugin/chongdae.py`. The skill
  also describes the session's orchestration responsibilities.
- Keep Claude commands as adapters to individual engine actions. Codex uses the
  same skill and Python engine; do not replace a single-action command with the
  entire run workflow or duplicate that workflow in host manifests.
- Preserve explicit task selection, session ownership, lease generations and
  record transactions. A completed task must not imply another worker finished.
  Source changes invalidate checks and reviews of the old source.
- Preserve durable launch, result-consumption and external-operation records.
  Recovery must not repeat an operation whose outcome is unknown. Keep recorded
  human decisions distinct from the session's own judgments.
- Providers come from declared roles and artifact contracts. Do not hardcode
  sibling products or import them. Settings come from `hunsu.json` with its local
  overlay; the lock records resolved dependencies.
- For behavior changes, run `python3 test_chongdae.py` from this repository root.
  This also runs `test_payload.py` and the concurrency and recovery suites; it uses temporary projects
  and recorded provider responses, without model calls. For documentation changes,
  check links and command examples. Follow the README's versioning policy before
  publishing or installing changed source.

## Layout and development environment

Runtime lives only in `plugin/`; nothing in it may link, import or refer to the repository around it.
Tests and development configuration stay at the root. The root `chongdae.py` is only a shim for
`plugin/chongdae.py`, not another runtime source.

Read `hunsu.json` as the committed declaration: engine floors, plugins with version, source and marketplace,
roles, capabilities, settings and resolutions. `hunsu.local.json` is this machine's ignored overlay:
links, `local-hooks-ok`, hosts and settings such as `commit-records`. `hunsu.lock.json` records what was resolved.

Prepare the host you are running by installing the released plugins at the versions `hunsu.json` pins,
using that host's marketplace commands (or hunsu's `install`). Then run
`python3 "<root>/hunsu.py" check --target .` from the repository, using the locked hunsu root given by
SessionStart for `<root>`; never use a glob over the plugin cache. One host is enough; preparing a second
host is not required. A role whose worker runs on another host's CLI needs that CLI only when hired;
`check` says what is missing.

The installed release orchestrates changes, never this checkout's `plugin/chongdae.py` or the root shim.
Do not move development pins to an unreleased version. To try working source, use hunsu's `dev`, on this
machine only. See the repository README's [release and adoption](README.md#release-and-adoption) procedure.
