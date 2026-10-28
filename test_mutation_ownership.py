"""Task judgments cannot bypass ownership; related-task mutations are checked before writes."""
import os
import sys
import unittest
from unittest.mock import patch

from test_chongdae import Project, run, write
import chongdae as c


class MutationOwnership(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def setup_task(self, pj, *extra):
        self.assertEqual(run("init", "--session", "--goal", "ownership", "--target", pj.dir)[0], 0)
        self.assertEqual(run("add", "work", *extra, "--target", pj.dir)[0], 0)
        return c.run_dir(pj.dir)

    def test_foreign_judgments_refuse_before_checks_operations_or_record_changes(self):
        commands = [
            ("retry", "work", "--by", "owner-a", "--checked", sys.executable + " -c \"open('effect','w').write('ran')\""),
            ("accept", "work", "--by", "owner-a"),
            ("confirm", "work", "--by", "owner-a"),
            ("unstage", "work", "newbie", "--why", "cannot run"),
            ("adopt", "work", "source.py", "--why", "attribution"),
            ("did", "work", "--", sys.executable, "-c", "open('effect','w').write('ran')"),
            ("dispute", "work", "--tests", "test_source.py", "--why", "wrong contract"),
            ("drop", "work", "--why", "cancelled"),
            ("add", "work", "--check", sys.executable + " -c pass"),
        ]
        for command in commands:
            with self.subTest(command=command[0]), Project() as pj:
                os.environ["CHONGDAE_SESSION"] = "owner-a"
                d = self.setup_task(pj, "--before", "newbie")
                state = pj.state()
                state["tasks"]["work"]["response"] = {"status": "blocked", "decisions": [{"what": "question"}]}
                c.save_state(d, state)
                write(c.work_path(d, "work.response.json"), {"status": "blocked"})
                before = pj.state()
                os.environ["CHONGDAE_SESSION"] = "owner-b"
                # --target must precede did's separator; --by never substitutes for ownership.
                argv = (command[0], "--target", pj.dir, *command[1:])
                code, out = run(*argv)
                self.assertEqual(code, c.DECISION, out)
                self.assertIn("another session", out)
                self.assertEqual(pj.state(), before)
                self.assertTrue(os.path.exists(c.work_path(d, "work.response.json")))
                self.assertFalse(os.path.exists(os.path.join(pj.dir, "effect")))

    def test_unknown_caller_cannot_retry_known_owner_but_explicit_take_can(self):
        with Project() as pj:
            d = self.setup_task(pj)
            state = pj.state()
            state["tasks"]["work"]["response"] = {"status": "blocked"}
            c.save_state(d, state)
            with patch.dict(os.environ):
                for key in ("CHONGDAE_SESSION", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
                    os.environ.pop(key, None)
                self.assertEqual(run("retry", "work", "--target", pj.dir)[0], c.DECISION)
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            code, out = run("take", "work", "--why", "owner handover", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            code, out = run("retry", "work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(len(pj.state()["tasks"]["work"]["attempts"]), 1)

    def test_claimed_task_requires_claim_owner_even_in_same_session(self):
        with Project() as pj:
            d = self.setup_task(pj)
            state = pj.state()
            state["tasks"]["work"]["response"] = {"status": "blocked"}
            c.save_state(d, state)
            self.assertEqual(run("claim", "work", "--by", "bob", "--target", pj.dir)[0], 0)
            code, out = run("retry", "work", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertIn("claimed by bob", out)
            os.environ["CHONGDAE_USER"] = "bob"
            self.assertEqual(run("retry", "work", "--target", pj.dir)[0], 0)

    def test_lease_holder_controls_mutation_including_the_original_owner(self):
        with Project() as pj:
            write(os.path.join(pj.dir, "hunsu.json"), {"settings": {"chongdae": {"lease": "local"}}})
            d = self.setup_task(pj)
            state = pj.state()
            state["tasks"]["work"]["response"] = {"status": "blocked"}
            c.save_state(d, state)
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            self.assertEqual(run("claim", "work", "--target", pj.dir)[0], 0)
            os.environ["CHONGDAE_SESSION"] = "owner-a"
            code, out = run("retry", "work", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertIn("held by another session", out)
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            self.assertEqual(run("retry", "work", "--target", pj.dir)[0], 0)

    def test_dispute_cannot_reopen_another_sessions_completed_test_writer(self):
        with Project() as pj:
            self.assertEqual(run("init", "--session", "--goal", "g", "--target", pj.dir)[0], 0)
            self.assertEqual(run("add", "tests", "--tests", "test_a.py", "--target", pj.dir)[0], 0)
            write(os.path.join(pj.dir, "test_a.py"), "# wrong\n")
            self.assertEqual(run("run", "tests", "--target", pj.dir)[0], 0)
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            self.assertEqual(run("add", "build", "--tests", "test_a.py", "--check", sys.executable + " -c pass", "--target", pj.dir)[0], 0)
            before = pj.state()
            code, out = run("dispute", "build", "--tests", "test_a.py", "--why", "fixture wrong", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertIn("tests belongs to another session", out)
            self.assertEqual(pj.state(), before)
            # Automatic provider disputes take the same preflight route.
            state = pj.state()
            plan = c.load(os.path.join(c.run_dir(pj.dir), "plan.json"))
            task = state["tasks"]["build"]["def"]
            self.assertIsNone(c.route_dispute(pj.dir, c.run_dir(pj.dir), state, plan, task, [{"test": "test_a.py", "why": "wrong"}]))
            self.assertEqual(state, before)

    def test_adopt_cannot_change_foreign_attribution_or_pin_foreign_open_work(self):
        for done in (False, True):
            with self.subTest(done=done), Project() as pj:
                os.environ["CHONGDAE_SESSION"] = "owner-a"
                self.setup_task(pj)
                write(os.path.join(pj.dir, "source.py"), "x = 1\n")
                if done:
                    self.assertEqual(run("run", "work", "--target", pj.dir)[0], 0)
                os.environ["CHONGDAE_SESSION"] = "owner-b"
                self.assertEqual(run("add", "mine", "--target", pj.dir)[0], 0)
                before = pj.state()
                code, out = run("adopt", "mine", "source.py", "--why", "mine", "--target", pj.dir)
                self.assertNotEqual(code, 0, out)
                self.assertIn("adopt would also change work", out)
                self.assertEqual(pj.state(), before)

    def test_generated_amendment_keeps_the_disputing_sessions_ownership(self):
        with Project() as pj:
            write(os.path.join(pj.dir, "test_a.py"), "# existing fixture\n")
            self.setup_task(pj, "--tests", "test_a.py", "--check", sys.executable + " -c pass")
            code, out = run("dispute", "work", "--tests", "test_a.py", "--why", "fixture wrong", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(pj.state()["tasks"]["work-tests"]["added-in"], "owner-a")
            before = pj.state()
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            code, out = run("drop", "work-tests", "--why", "cancel", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertEqual(pj.state(), before)


if __name__ == "__main__":
    unittest.main()
