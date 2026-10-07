---
description: Add a task to the session run; its start snapshot is taken now. It says what --tests means for it — written (nitpick) or protected (a task with a check). --role subagent: the session's own sub-agent does it (declared hands, not self-performed); --scope: the files/dirs its hands own, so concurrent tasks split one tree by scope
argument-hint: <id> [--brief ..] [--closes Q..] [--check "argv"]... [--tests F..] [--requires CAP..] [--gate human] [--before ROLE..] [--after ROLE..] [--role R|subagent [--why ..]] [--scope PATH..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" add $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.
