# Working on chongdae

This is the shared source-checkout guidance for Claude Code and Codex. `CLAUDE.md`
imports this file; keep maintenance instructions here. Installing the plugin does
not automatically load this file into a user's project.

- Read [README.md](README.md) for contracts, host adapters, limits and versioning.
  The installed workflow is [run](skills/run/SKILL.md); keep its procedure shared
  between hosts, with enforced sequencing and gates in `chongdae.py`. The skill
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
  This also runs the concurrency and recovery suites; it uses temporary projects
  and recorded provider responses, without model calls. For documentation changes,
  check links and command examples. Follow the README's versioning policy before
  publishing or installing changed source.
