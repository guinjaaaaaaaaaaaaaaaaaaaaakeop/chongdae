"""Record commits and worktree landing must preserve concurrent work."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import chongdae


class RecordTransactions(unittest.TestCase):
    def test_subprojects_sharing_git_do_not_share_a_scratch_index(self):
        with tempfile.TemporaryDirectory(prefix="chongdae-shared-git-") as tmp:
            root = Path(tmp)
            real_run = subprocess.run

            def git(*args):
                return real_run(["git", *args], cwd=tmp, capture_output=True, text=True, check=True).stdout.strip()

            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (root / "source.txt").write_text("KEEP\n")
            for name in ("a", "b"):
                folder = root / name / ".chongdae" / "run-test"
                folder.mkdir(parents=True)
                (folder / "state.json").write_text("{}\n")
                chongdae.ensure_record_ignore(str(root / name))
            git("add", "-A")
            git("commit", "-qm", "base")
            (root / "a/.chongdae/run-test/state.json").write_text('{"changed":true}\n')
            interleaved = []

            def interleave(argv, *args, **kwargs):
                result = real_run(argv, *args, **kwargs)
                if argv[:2] == ["git", "add"] and kwargs.get("cwd") == str(root / "a") and not interleaved:
                    interleaved.append(True)
                    self.assertIsNone(chongdae.commit_record(str(root / "b"), "run-test", "unchanged B"))
                return result

            with mock.patch("subprocess.run", side_effect=interleave):
                self.assertTrue(chongdae.commit_record(str(root / "a"), "run-test", "changed A"))
            self.assertEqual(interleaved, [True])
            self.assertEqual(git("show", "HEAD:source.txt"), "KEEP")
            self.assertEqual(json.loads(git("show", "HEAD:a/.chongdae/run-test/state.json")), {"changed": True})
            self.assertEqual(json.loads(git("show", "HEAD:b/.chongdae/run-test/state.json")), {})

    def test_record_commit_does_not_replace_a_newer_source_commit(self):
        with tempfile.TemporaryDirectory(prefix="chongdae-record-race-") as tmp:
            root = Path(tmp)
            real_run = subprocess.run

            def git(*args):
                return real_run(["git", *args], cwd=tmp, capture_output=True, text=True, check=True).stdout.strip()

            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (root / "source.txt").write_text("before\n")
            git("add", "source.txt")
            git("commit", "-qm", "base")
            run = root / ".chongdae" / "run-test"
            run.mkdir(parents=True)
            (run / "state.json").write_text(json.dumps({"artifact-type": "chongdae/run@1", "status": "running"}))
            moved = []

            def interleave(argv, *args, **kwargs):
                result = real_run(argv, *args, **kwargs)
                if argv[:2] == ["git", "commit-tree"] and not moved:
                    (root / "source.txt").write_text("another worker's commit\n")
                    git("add", "source.txt")
                    git("commit", "-qm", "source landed meanwhile")
                    moved.append(git("rev-parse", "HEAD"))
                return result

            with mock.patch("subprocess.run", side_effect=interleave), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(chongdae.commit_record(tmp, "run-test", "record"))
            self.assertEqual(len(moved), 1)
            self.assertEqual(git("rev-parse", "HEAD"), moved[0])
            self.assertEqual(git("show", "HEAD:source.txt"), "another worker's commit")
            self.assertTrue((run / "state.json").exists())
            # A later record commit includes the uncommitted judgment without losing the source commit.
            self.assertTrue(chongdae.commit_record(tmp, "run-test", "record again"))
            self.assertEqual(git("show", "HEAD:source.txt"), "another worker's commit")
            self.assertEqual(git("rev-parse", "HEAD^"), moved[0])

    def test_worktree_close_waits_for_destination_before_changing_child(self):
        with tempfile.TemporaryDirectory(prefix="chongdae-landing-lock-") as tmp:
            main, child = Path(tmp) / "main", Path(tmp) / "child"
            main.mkdir()
            run = child / ".chongdae" / "run-test"
            run.mkdir(parents=True)
            state = {"artifact-type": "chongdae/run@1", "status": "running",
                     "worktree": {"main": str(main), "branch": "test"}}
            (run / "state.json").write_text(json.dumps(state))
            (run / "plan.json").write_text(json.dumps({"kind": "session", "tasks": [], "goal": "test"}))
            original = (run / "state.json").read_bytes()
            with chongdae.CommandLock(str(main)) as lock:
                self.assertTrue(lock.acquired)
                done = subprocess.run([sys.executable, chongdae.__file__, "close", "--target", str(child)],
                                      capture_output=True, text=True, timeout=10)
            self.assertEqual(done.returncode, chongdae.WAITING, done.stdout + done.stderr)
            self.assertIn("destination project", done.stdout)
            self.assertEqual((run / "state.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
