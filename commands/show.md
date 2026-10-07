---
description: What happened in a run, for a reader after — tasks, who did them, attempts with verdicts and findings, judgments, times; --since REV a line per run; --path FILE the tasks that touched it; --brief one line per fact (with --path: at most two — an open or dropped task only while its run is open or it ended this week, and no done task changed the file since; alone: the map). The session's own judgments read "the session (<host> <model>)"
argument-hint: [--run ID | --since REV | --path FILE] [--brief]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" show $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.
