---
description: Send a stopped task (blocked, failed, no response) out again; the next call receives the earlier attempts. --requires: the sandbox lacked CAP — the task says so, and goes to the lock's <role>@<cap>
argument-hint: <task> --by NAME | --delegated WHY [--requires CAP..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" retry $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.
