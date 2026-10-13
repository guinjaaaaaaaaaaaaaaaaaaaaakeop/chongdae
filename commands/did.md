---
description: Run one operation outside the repository (a deploy, a secret deletion, a remote database change) for a task — one command, no shell line — and record {command, exit, tail, at, why, approved-in, signer} on it whatever the exit; show prints it, report lists it (an objection when it exited non-zero). Cite --approved-in source:ID when it cannot be undone (no --by: signed by the session, not a person)
argument-hint: <task> [--why ".."] [--approved-in source:ID] [--by NAME] -- COMMAND [ARG..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" did $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.
