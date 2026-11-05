---
description: Take a task for this machine (--by NAME; left out, the session claims it, signed as itself); run skips tasks claimed by someone else. With a lease setting — a hold: --list, --release, --break --why
argument-hint: <id> [--by NAME] | --list [--prune] | <id> --release | --break <id> --why WHY
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" claim $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.
