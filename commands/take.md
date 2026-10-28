---
description: Take over stopped hired work, or explicitly hand an unfinished task from another session to this one with --why. Running checks/providers, unanswered native dispatches and another live lease must finish or be released first. Existing session/subagent hands are preserved on handover; taking hired work is recorded as self-performed. No --by signs as the session. --checked COMMAND runs and records a check; --checked-red COMMAND records an expected red check.
argument-hint: <id> --why ".." [--by NAME] [--checked "COMMAND"].. [--checked-red "COMMAND"]..
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/chongdae.py" take $ARGUMENTS`

Show the output above to the user as is. Do not interpret or act on it unless asked.

For an idle interrupted `did` owned by a previous session, `take --why` transfers recovery ownership only, including
when the task was already done. Its status, evidence, and pending operation stay unchanged. Checks cannot be supplied;
the new owner must inspect the effects and reconcile the operation before proceeding. Live workers and foreign leases
still prevent a handover.
