---
description: Advance the current run one step; exit 2 = stopped for the session agent or a human
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" status --target .`

The line above is the run's state (no run, or which run and what is open). To advance it: `python "${CLAUDE_PLUGIN_ROOT}/chongdae.py" run --target .` — exit 2 means stopped, and the last line says who must act. Show the output to the user as is. Do not interpret or act on it unless asked.
