---
description: Declare a batch pre-approval once (scope, why, by) — later judgments reference its id with --delegated D-xxxx
argument-hint: --scope confirm,accept,retry --why ".." --by NAME [--run ID]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" delegate $ARGUMENTS --target .`

Show the output above to the user as is. Do not interpret or act on it unless asked.
