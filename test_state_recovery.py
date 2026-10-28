"""A run's public records and private witnesses recover as one state generation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import chongdae as c


class StateRecovery(unittest.TestCase):
    def state(self, value):
        return {"status": "running", "tasks": {
            "a": {"status": value, "review-source": {"a.py": value}},
            "b": {"status": value, "after-source": {"b.py": value}},
        }}

    def test_process_death_between_public_and_private_writes_recovers_whole_generation(self):
        with tempfile.TemporaryDirectory() as d:
            c.save_state(d, self.state("todo"))
            script = """
import json, os, sys
import chongdae as c
d = sys.argv[1]
state = c.load_state(d)
for task in state['tasks'].values():
    task['status'] = 'done'
    for key in ('review-source', 'after-source'):
        if key in task:
            task[key] = {p: 'done' for p in task[key]}
save = c.save_changed
def crash(path, data):
    if path == os.path.join(d, 'local', 'tasks', 'a.json'):
        os._exit(77)
    save(path, data)
c.save_changed = crash
c.save_state(d, state)
"""
            proc = subprocess.run([sys.executable, "-c", script, d], cwd=os.path.dirname(c.__file__))
            self.assertEqual(proc.returncode, 77)
            self.assertEqual(c.load(os.path.join(d, "tasks", "a.json"))["status"], "done")
            self.assertEqual(c.load(os.path.join(d, "local", "tasks", "a.json"))["review-source"], {"a.py": "todo"})
            visible = c.load_state(d)
            self.assertEqual(visible["tasks"]["a"]["review-source"], {"a.py": "done"})
            self.assertEqual(visible["tasks"]["b"]["status"], "done")
            c.recover_state(d)
            c.recover_state(d)
            self.assertEqual(c.load_state(d), visible)
            self.assertEqual(c.load(os.path.join(d, "local", "tasks", "a.json"))["review-source"], {"a.py": "done"})
            self.assertEqual(c.load(os.path.join(d, "local", "state-transaction.json"))["phase"], "committed")

    def test_reader_retries_when_a_generation_finishes_between_file_reads(self):
        with tempfile.TemporaryDirectory() as d:
            c.save_state(d, self.state("todo"))
            original = c.load
            fired = []

            def interleave(path):
                result = original(path)
                if path == os.path.join(d, "tasks/a.json") and not fired:
                    fired.append(True)
                    c.save_state(d, self.state("done"))
                return result

            with mock.patch.object(c, "load", side_effect=interleave):
                visible = c.load_state(d)
            self.assertEqual(fired, [True])
            self.assertEqual(visible["tasks"]["a"]["status"], "done")
            self.assertEqual(visible["tasks"]["a"]["review-source"], {"a.py": "done"})
            self.assertEqual(visible["tasks"]["b"]["status"], "done")

    def test_interrupted_overlay_deletion_does_not_restore_stale_witness(self):
        with tempfile.TemporaryDirectory() as d:
            c.save_state(d, self.state("todo"))
            updated = self.state("todo")
            updated["tasks"]["a"].pop("review-source")
            original = os.remove
            overlay = os.path.join(d, "local/tasks/a.json")

            def interrupt(path):
                if path == overlay:
                    raise RuntimeError("interrupted deletion")
                return original(path)

            with mock.patch("os.remove", side_effect=interrupt), self.assertRaises(RuntimeError):
                c.save_state(d, updated)
            self.assertNotIn("review-source", c.load_state(d)["tasks"]["a"])
            c.recover_state(d)
            self.assertFalse(os.path.exists(overlay))

    def test_reader_survives_overlay_deleted_just_before_open(self):
        with tempfile.TemporaryDirectory() as d:
            c.save_state(d, self.state("todo"))
            updated = self.state("done")
            updated["tasks"]["a"].pop("review-source")
            original = c.io.open
            fired = []

            def interleave(path, *args, **kwargs):
                if path == os.path.join(d, "local/tasks/a.json") and not fired:
                    fired.append(True)
                    c.save_state(d, updated)
                return original(path, *args, **kwargs)

            with mock.patch.object(c.io, "open", side_effect=interleave):
                visible = c.load_state(d)
            self.assertEqual(fired, [True])
            self.assertEqual(visible["tasks"]["a"]["status"], "done")
            self.assertNotIn("review-source", visible["tasks"]["a"])

    def test_next_save_preserves_recovered_state_and_unchanged_files(self):
        with tempfile.TemporaryDirectory() as d:
            c.save_state(d, self.state("todo"))
            before = Path(d, "tasks/a.json").stat().st_mtime_ns
            snapshot = c.load_state(d)
            c.save_state(d, snapshot)
            self.assertEqual(Path(d, "tasks/a.json").stat().st_mtime_ns, before)
            original = c.save_changed

            def interrupt(path, data):
                if path == os.path.join(d, "tasks", "b.json"):
                    raise RuntimeError("interrupted second task")
                original(path, data)

            with mock.patch.object(c, "save_changed", side_effect=interrupt), self.assertRaises(RuntimeError):
                c.save_state(d, self.state("done"))
            state = c.load_state(d)
            state["tasks"]["c"] = {"status": "todo"}
            c.save_state(d, state)
            actual = c.load_state(d)
            self.assertEqual(actual["tasks"]["a"]["status"], "done")
            self.assertEqual(actual["tasks"]["b"]["after-source"], {"b.py": "done"})
            self.assertEqual(actual["tasks"]["c"]["status"], "todo")

    def test_next_command_recovers_before_commit_and_keeps_journal_private(self):
        import test_chongdae as fixture
        with fixture.Project() as project:
            target = project.dir
            subprocess.run(["git", "config", "user.name", "Test"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=target, check=True)
            self.assertEqual(fixture.run("init", "--session", "--goal", "recover", "--target", target)[0], 0)
            self.assertEqual(fixture.run("add", "a", "--brief", "a", "--target", target)[0], 0)
            d = c.run_dir(target)
            state = c.load_state(d)
            state["tasks"]["a"]["review-source"] = {"private.py": "private witness"}
            original = c.save_changed

            def interrupt(path, data):
                if path == os.path.join(d, "local", "tasks", "a.json"):
                    raise RuntimeError("interrupt overlay")
                original(path, data)

            with mock.patch.object(c, "save_changed", side_effect=interrupt), self.assertRaises(RuntimeError):
                c.save_state(d, state)
            code, out = fixture.run("add", "b", "--brief", "b", "--target", target)
            self.assertEqual(code, 0, out)
            self.assertEqual(c.load_state(d)["tasks"]["a"]["review-source"], {"private.py": "private witness"})
            self.assertEqual(c.load(os.path.join(d, "local", "state-transaction.json"))["phase"], "committed")
            tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=target, text=True)
            self.assertNotIn("state-transaction.json", tracked)
            self.assertNotIn("/local/", tracked)


if __name__ == "__main__":
    unittest.main()
