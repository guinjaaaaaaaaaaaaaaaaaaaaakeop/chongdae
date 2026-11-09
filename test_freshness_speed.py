"""Contract S: the pending-review freshness test must not depend on how fast the machine is.

test_review_freshness's test_pending_review_keeps_its_original_source_across_calls starts `run a` with a one-second
call budget and waits for the detached verifier's ready file while requiring that `run` has not returned. On a loaded
machine the verifier reaches its ready file after the budget ends; `run` has already handed back 4 — exactly what the
test asserts of the engine — and the test fails anyway. This module runs that single test twice in a subprocess: once
as the machine gives it, once with the fake verifier slowed past the call budget. Neither run changes a file of the
suite: the slowdown is a `sitecustomize.py` in a temporary directory prepended to PYTHONPATH, sleeping only inside the
fake verifier the test writes (its script is named reviewer.py).
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
TEST = "test_review_freshness.ReviewFreshness.test_pending_review_keeps_its_original_source_across_calls"
# CHONGDAE_WAIT in the inner test is 1 second; a verifier that needs two seconds to reach its ready file
# arrives after the budget on any machine.
SLOW_VERIFIER = textwrap.dedent("""\
    import os, sys, time
    if os.path.basename(sys.argv[0]) == "reviewer.py":
        time.sleep(2)
""")
# The inner test's own ceilings (wait_for 10 s, communicate 8-12 s) are far below this: a hang there is reported
# by the inner test, not by this module's timeout, so the outer budget decides nothing about speed.
OUTER_TIMEOUT = 300


class FreshnessSpeed(unittest.TestCase):
    def run_inner(self, pythonpath=None):
        env = dict(os.environ)
        env.pop("CHONGDAE_WAIT", None)   # the inner test sets its own budget; nothing from outside may widen it
        if pythonpath is not None:
            env["PYTHONPATH"] = os.pathsep.join([pythonpath, env["PYTHONPATH"]]) if env.get("PYTHONPATH") else pythonpath
        return subprocess.run([sys.executable, "-m", "unittest", "-v", TEST], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=OUTER_TIMEOUT)

    def assert_passed(self, result, label):
        self.assertEqual(result.returncode, 0,
                         "%s: the pending-review test did not pass\n--- stdout ---\n%s\n--- stderr ---\n%s"
                         % (label, result.stdout, result.stderr))
        self.assertIn("OK", result.stderr, "%s: unittest did not report OK\n%s" % (label, result.stderr))

    def test_S1_pending_review_test_passes_as_the_machine_gives_it(self):
        self.assert_passed(self.run_inner(), "unslowed run")

    def test_S1_pending_review_test_passes_when_the_verifier_is_slower_than_the_call_budget(self):
        with tempfile.TemporaryDirectory(prefix="chongdae-slow-verifier-") as slow:
            pathlib.Path(slow, "sitecustomize.py").write_text(SLOW_VERIFIER)
            result = self.run_inner(pythonpath=slow)
        self.assertNotIn("worker exited before the synchronization point", result.stdout + result.stderr,
                         "the test fails because run handed back before the slowed verifier was ready\n"
                         "--- stdout ---\n%s\n--- stderr ---\n%s" % (result.stdout, result.stderr))
        self.assert_passed(result, "slowed verifier")

    def test_S2_slowed_run_still_asserts_the_original_contract(self):
        """S2 is decided by the inner test's own body, which this module does not rewrite: with the verifier slowed,
        the inner test must still reach and pass its assertions (first call 4 with the review pending on a.py = 1,
        edit and commit while pending, second call says "source changed" and the task is todo, third completes,
        verifier called exactly twice). It is only decided when the inner test passes end to end."""
        with tempfile.TemporaryDirectory(prefix="chongdae-slow-verifier-") as slow:
            pathlib.Path(slow, "sitecustomize.py").write_text(SLOW_VERIFIER)
            result = self.run_inner(pythonpath=slow)
        self.assertIn("test_pending_review_keeps_its_original_source_across_calls", result.stderr,
                      "the inner test was not selected\n%s" % result.stderr)
        self.assertNotIn("ERROR:", result.stderr, "the inner test errored instead of running its body\n%s" % result.stderr)
        self.assert_passed(result, "slowed verifier, full contract")


if __name__ == "__main__":
    unittest.main()
