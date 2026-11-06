"""Contract C1: adopt never rewrites a closed task's record — a later adoption is recorded beside it, on the adopting task.

Reproduces the jokbo/dwitbuk case through the CLI: a done task A that changed x.py, then a task B the session adopts x.py
into. A's record (the public tasks/A.json, the local one, the run state) must stay byte-identical; B's adoption carries
`beside`."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_chongdae import Project, run, write
import chongdae as c

FAIL = sys.executable + " -c \"import sys; sys.exit(1)\""


class AdoptRecord(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)

    # -- fixtures ------------------------------------------------------------------------------------------------

    def project(self, pj):
        write(os.path.join(pj.dir, "README.md"), "# r\n")
        subprocess.run(["git", "add", "-A"], cwd=pj.dir, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=pj.dir, check=True)
        code, out = run("init", "--session", "--goal", "adopt record", "--target", pj.dir)
        self.assertEqual(code, 0, out)

    def done_a(self, pj):
        """Task A (no check) changes x.py and is run done; A's record lists x.py."""
        self.project(pj)
        code, out = run("add", "A", "--brief", "write x.py", "--target", pj.dir)
        self.assertEqual(code, 0, out)
        write(os.path.join(pj.dir, "x.py"), "x = 1\n")
        code, out = run("run", "--target", pj.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("done A", out)
        st = pj.state()["tasks"]["A"]
        self.assertEqual(st["status"], "done", st)
        self.assertIn("x.py", st["touched"], st)

    def record_bytes(self, pj, task):
        """Every on-disk form of a task's record: the public tasks/T.json, the local one, and the run state's entry."""
        rd = c.run_dir(pj.dir)
        out = {}
        for rel in (("tasks", task + ".json"), ("local", "tasks", task + ".json")):
            path = os.path.join(rd, *rel)
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    out["/".join(rel)] = fh.read()
        self.assertIn("tasks/" + task + ".json", out, "the public task record exists on disk")
        out["state"] = pj.state()["tasks"][task]
        return out

    def snapshot(self, pj):
        rd = c.run_dir(pj.dir)
        files = {}
        for root, _dirs, names in os.walk(rd):
            for name in names:
                path = os.path.join(root, name)
                with open(path, "rb") as fh:
                    files[os.path.relpath(path, rd)] = fh.read()
        return files

    # -- C1.1 -------------------------------------------------------------------------------------------------------

    def test_C1_1_adopt_leaves_a_done_tasks_record_byte_identical(self):
        with Project() as pj:
            self.done_a(pj)
            self.assertEqual(run("add", "B", "--brief", "own x.py", "--target", pj.dir)[0], 0)
            before = self.record_bytes(pj, "A")
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            after = self.record_bytes(pj, "A")
            self.assertEqual(after["state"], before["state"], "a done task's record is not changed by a later adopt")
            for key in before:
                self.assertEqual(after[key], before[key], "%s changed by the adopt" % key)
            self.assertEqual(after["state"]["touched"], before["state"]["touched"])
            self.assertIn("x.py", after["state"]["touched"])
            self.assertNotIn("gave", after["state"])

    def test_C1_1_adopt_leaves_a_dropped_task_holding_the_file_unchanged(self):
        with Project() as pj:
            self.project(pj)
            self.assertEqual(run("add", "A", "--brief", "try x.py", "--target", pj.dir)[0], 0)
            write(os.path.join(pj.dir, "x.py"), "x = 1\n")
            code, out = run("drop", "A", "--why", "superseded", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            st = pj.state()["tasks"]["A"]
            self.assertEqual(st["status"], "dropped", st)
            self.assertIn("x.py", st.get("touched", []), st)
            self.assertEqual(run("add", "B", "--brief", "own x.py", "--target", pj.dir)[0], 0)
            before = self.record_bytes(pj, "A")
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            after = self.record_bytes(pj, "A")
            self.assertEqual(after, before, "a dropped task's record is not changed by a later adopt")
            entry = pj.state()["tasks"]["B"]["adopted"][-1]
            self.assertEqual(entry.get("beside"), {"A": ["x.py"]}, entry)
            self.assertNotIn("A", entry.get("from") or {}, entry)

    def test_C1_1_an_open_giver_still_loses_the_file_and_gets_gave(self):
        # open-task behaviour unchanged: A is still open (its check fails) when B adopts x.py
        with Project() as pj:
            self.project(pj)
            self.assertEqual(run("add", "A", "--check", FAIL, "--target", pj.dir)[0], 0)
            write(os.path.join(pj.dir, "x.py"), "x = 1\n")
            code, out = run("run", "--target", pj.dir)
            self.assertEqual(code, c.DECISION, out)
            self.assertEqual(pj.state()["tasks"]["A"]["status"], "todo")
            self.assertEqual(run("add", "B", "--target", pj.dir)[0], 0)
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("from A: x.py", out)
            st = pj.state()["tasks"]
            self.assertNotIn("x.py", st["A"].get("touched", []), st["A"])
            self.assertEqual(st["A"]["gave"][-1]["to"], "B", st["A"])
            self.assertEqual(st["A"]["gave"][-1]["files"], ["x.py"], st["A"])
            entry = st["B"]["adopted"][-1]
            self.assertEqual(entry["from"], {"A": ["x.py"]}, entry)
            self.assertFalse(entry.get("beside"), "an open giver is `from`, not `beside`: %r" % entry)

    # -- C1.2 -------------------------------------------------------------------------------------------------------

    def test_C1_2_the_adopting_task_records_beside_the_done_task_not_from(self):
        with Project() as pj:
            self.done_a(pj)
            self.assertEqual(run("add", "B", "--brief", "own x.py", "--target", pj.dir)[0], 0)
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            entry = pj.state()["tasks"]["B"]["adopted"][-1]
            self.assertEqual(entry["files"], ["x.py"], entry)
            self.assertEqual(entry.get("beside"), {"A": ["x.py"]}, entry)
            self.assertNotIn("A", entry.get("from") or {}, "a done task is not one the file moved from: %r" % entry)
            # and the public record of B on disk carries it too
            rec = c.load(os.path.join(c.run_dir(pj.dir), "tasks", "B.json"))
            self.assertEqual(rec["adopted"][-1].get("beside"), {"A": ["x.py"]}, rec.get("adopted"))

    def test_C1_2_adopt_prints_the_beside_files(self):
        with Project() as pj:
            self.done_a(pj)
            self.assertEqual(run("add", "B", "--brief", "own x.py", "--target", pj.dir)[0], 0)
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("beside done A: x.py", out)
            self.assertIn("its record keeps it as judged when it finished", out)
            self.assertNotIn("from A", out)

    # -- C1.3 -------------------------------------------------------------------------------------------------------

    def test_C1_3_a_done_task_of_another_session_does_not_refuse_the_adopt(self):
        with Project() as pj:
            self.done_a(pj)                                    # A is owner-a's
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            self.assertEqual(run("add", "B", "--brief", "own x.py", "--target", pj.dir)[0], 0)
            before = self.record_bytes(pj, "A")
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertNotIn("another session", out)
            self.assertEqual(self.record_bytes(pj, "A"), before, "nothing of the foreign done task changes")
            self.assertEqual(pj.state()["tasks"]["B"]["adopted"][-1].get("beside"), {"A": ["x.py"]})

    def test_C1_3_an_open_task_of_another_session_still_refuses_before_writing(self):
        with Project() as pj:
            self.project(pj)
            self.assertEqual(run("add", "A", "--target", pj.dir)[0], 0)   # owner-a's, still open
            write(os.path.join(pj.dir, "x.py"), "x = 1\n")
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            self.assertEqual(run("add", "B", "--target", pj.dir)[0], 0)
            before = self.snapshot(pj)
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertIn("adopt would also change A", out)
            self.assertEqual(self.snapshot(pj), before, "nothing written")
            self.assertNotIn("adopted", pj.state()["tasks"]["B"])
            # the C1 half: once A is closed (here dropped by its owner), the same adopt goes through and A stays as it was
            os.environ["CHONGDAE_SESSION"] = "owner-a"
            self.assertEqual(run("drop", "A", "--why", "superseded", "--target", pj.dir)[0], 0)
            os.environ["CHONGDAE_SESSION"] = "owner-b"
            before_a = self.record_bytes(pj, "A")
            code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.record_bytes(pj, "A"), before_a)

    # -- C1.4 -------------------------------------------------------------------------------------------------------

    def test_C1_4_adopt_into_a_done_task_is_refused_with_nothing_written(self):
        with Project() as pj:
            self.done_a(pj)
            write(os.path.join(pj.dir, "y.py"), "y = 1\n")
            self.assertEqual(run("add", "B", "--brief", "write y.py", "--target", pj.dir)[0], 0)
            before = self.snapshot(pj)
            code, out = run("adopt", "A", "y.py", "--why", "later work", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertIn("A is done — a closed task's record stands as it was judged; add a task for the later work and adopt into it", out)
            self.assertEqual(self.snapshot(pj), before, "nothing written")

    # -- C1.5 -------------------------------------------------------------------------------------------------------

    def adopted_and_run(self, pj):
        self.done_a(pj)
        self.assertEqual(run("add", "B", "--brief", "own x.py", "--target", pj.dir)[0], 0)
        code, out = run("adopt", "B", "x.py", "--why", "B's work", "--target", pj.dir)
        self.assertEqual(code, 0, out)

    def test_C1_5_show_tells_the_later_adoption_on_the_done_task_and_beside_on_the_adopter(self):
        with Project() as pj:
            self.adopted_and_run(pj)
            code, out = run("show", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            a_block, _, b_block = out.partition("\nB  ")
            self.assertIn("later adopted by B: x.py (B's work) — by ", a_block)
            self.assertNotIn("gave x.py to B", out)
            self.assertIn("touched: x.py", a_block)
            lines = [l for l in b_block.splitlines() if "adopted x.py" in l]
            self.assertEqual(len(lines), 1, b_block)
            self.assertIn("beside", lines[0])
            self.assertIn("A: x.py", lines[0])
            self.assertNotIn("from A", lines[0])

    def test_C1_5_show_path_reads_both_records_and_the_later_task_is_the_last(self):
        with Project() as pj:
            self.adopted_and_run(pj)
            code, out = run("run", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("done B", out)
            code, out = run("show", "--path", "x.py", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("  A  done", out, "the closed task still lists the file")
            self.assertIn("  B  done", out, "the adopter lists it too")
            code, out = run("show", "--path", "x.py", "--brief", "--target", pj.dir)
            lines = out.strip().splitlines()
            self.assertEqual(code, 0, out)
            self.assertEqual(len(lines), 1, out)
            self.assertTrue(lines[0].startswith("last changed in run-"), out)
            self.assertIn("task B: own x.py", lines[0])


if __name__ == "__main__":
    unittest.main()
