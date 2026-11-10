---
description: A session task with no check needs --why saying why no check decides it (except --inspect). Add a task to the session run; its start snapshot is taken now. It says what --tests means for it — written (nitpick) or protected (a task with a check). --role subagent: the session's own sub-agent does it (declared hands, not self-performed); --scope: the files/dirs its hands own, so concurrent tasks split one tree by scope. A protected test the tests writer deleted is "deleted by the contract" — said once, sent as deleted-tests, never demanded. --closes in a run without --from is said here: no quibbler or verifier is sent an empty contract
argument-hint: <id> [--brief ..] [--closes Q..] [--check "argv"]... [--tests F..] [--requires CAP..] [--gate human] [--before ROLE..] [--after ROLE..] [--role R|subagent] [--why "required for a session task with no check"] [--scope PATH..]
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" add $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.

For a declared worker’s task, `--role session --why "CLASS: text"` names why it was not hired: `owner-dialogue` (the person shapes the work turn by turn), `latency` (a worker's round trip costs more than the change),
`capability` (the worker's sandbox lacks what the task needs — name it), `provider-unavailable` (the declared provider
cannot run here now), `operation` (an operation outside the repository), `project-rule` (the project's rules give it to
the owning session), or `worker-contract` (the worker's contract cannot take it, such as tests that must pass before the build).
Scoped unclaimed work already changed at add is kept as `held-at-add`; the output names claims and the `adopt` judgment.
