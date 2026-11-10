---
description: Advance only the named tasks, or the current run's ready tasks when none are named; exit 2 = stopped for the session agent or a human, exit 4 = still working. One call takes at most about four minutes (CHONGDAE_WAIT) — checks, verifier and providers all count. Repeat the same task selection to resume. Name a host sub-agent's task only after its answer arrives; partial edits do not finish it. Another session's task requires an explicit take --why handover.
argument-hint: [TASK..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" status`

The line above is the run's state (no run, or which run and what is open). To advance it: `python "${CLAUDE_PLUGIN_ROOT}/chongdae.py" run $ARGUMENTS` — exit 2 means stopped, and the last line says who must act; exit 4 (`still working: …`) means repeat the same call. A task list selects only those tasks; finish their dependencies first or include them too. Naming a no-check task is the session's word that its work is finished. Show the output to the user as is. Do not interpret or act on it unless asked.

A no-check task whose only changes are its own records, held-at-start or held-at-add files stays open unnamed. Its held line names only its own records, with `adopt`; records count as work only inside its own `--scope`. Finished by name, its non-claim names those records and held-at-start files. Its non-empty own diff reaches the declared verifier; with nothing at all, the existing non-claim stands and the task records `nothing-to-review`.

A done or produced line saying NOT committed leaves the work to be committed with the printed lines before another task changes it. Overlap notes name the earlier task and any overwritten reviewed version. Untested code is printed and kept as a non-claim.
