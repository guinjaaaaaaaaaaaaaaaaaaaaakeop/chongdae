---
description: Send a stopped task (blocked, failed, no response) out again; the next call receives the earlier attempts
argument-hint: <task> --by NAME | --delegated WHY
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" retry $ARGUMENTS --target .`

Show the output above to the user as is. Do not interpret or act on it unless asked.
