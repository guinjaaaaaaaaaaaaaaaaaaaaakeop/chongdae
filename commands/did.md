---
description: Run one operation outside the repository (a deploy, a secret deletion, a remote database change) for a task — one command, no shell line — and record {command, exit, tail, at, why, approved-in, signer} on it whatever the exit; show prints it, report lists it (an objection when it exited non-zero). Cite --approved-in source:ID when it cannot be undone (no --by: signed by the session, not a person). --each FILE: one command per line, one judgment and one commit. A script outside the project is kept in the record
argument-hint: <task> [--why ".."] [--approved-in source:ID] [--by NAME] (-- COMMAND [ARG..] | --each FILE | --reconcile ID --why "external state checked")
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" did $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.

An interrupted operation is never automatically repeated. Calling `did TASK` again restores any observed results without executing a command; batch items that never started stay unexecuted. An unknown outcome blocks further work on that task and closing the run. Inspect the external state and ensure the operation has stopped, then use `did TASK --reconcile ID --why "what was checked"`. This records the unknown outcome and the reconciliation reason, executes nothing, and permits a deliberate subsequent command. It does not claim the interrupted operation succeeded. A known live process must stop before reconciliation.
