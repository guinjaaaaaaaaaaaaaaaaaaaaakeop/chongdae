---
description: Send a stopped task (blocked, failed, no response) out again (--by NAME, --delegated WHY, or left out: signed by the session — a retry is not a gate); the next call receives the earlier attempts. --requires: the sandbox lacked CAP — the task says so, and goes to the lock's <role>@<cap>. A session task is measured again and what its measure leaves out is named, with the adopt that settles it
argument-hint: <task> [--by NAME | --delegated WHY] [--requires CAP..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" retry $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.
