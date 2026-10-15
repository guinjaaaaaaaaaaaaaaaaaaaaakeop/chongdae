---
description: Advance the current run one step; exit 2 = stopped for the session agent or a human, exit 4 = still working. One call takes at most about four minutes (CHONGDAE_WAIT) — chongdae's own checks, the verifier and providers all count — then says `still working:`; run again, it resumes there. `run TASK` names a session task whose work leaves nothing in the tree (one with no check, no change and no `did` is otherwise left open)
argument-hint: [TASK..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" status`

The line above is the run's state (no run, or which run and what is open). To advance it: `python "${CLAUDE_PLUGIN_ROOT}/chongdae.py" run $ARGUMENTS` — exit 2 means stopped, and the last line says who must act; exit 4 (`still working: …`) means run it again. Show the output to the user as is. Do not interpret or act on it unless asked.
