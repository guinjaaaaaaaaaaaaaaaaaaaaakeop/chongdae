---
description: Advance only the named tasks, or the current run's ready tasks when none are named; exit 2 = stopped for the session agent or a human, exit 4 = still working. One call takes at most about four minutes (CHONGDAE_WAIT) — checks, verifier and providers all count. Repeat the same task selection to resume. Name a host sub-agent's task only after its answer arrives; partial edits do not finish it. Another session's task requires an explicit take --why handover.
argument-hint: [TASK..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" status`

The line above is the run's state (no run, or which run and what is open). To advance it: `python "${CLAUDE_PLUGIN_ROOT}/chongdae.py" run $ARGUMENTS` — exit 2 means stopped, and the last line says who must act; exit 4 (`still working: …`) means repeat the same call. A task list selects only those tasks; finish their dependencies first or include them too. Naming a no-check task is the session's word that its work is finished. Show the output to the user as is. Do not interpret or act on it unless asked.
