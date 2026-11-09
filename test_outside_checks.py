"""Contract C7: a check program outside the project is refused unless allowed, and its content digest recorded.

The defect as a session meets it: `add t --check "<python> /tmp/…/check.py"` is accepted and only the argv is recorded,
so `recheck` and a landing cannot tell whether the program they run is the one that decided the task.
"""
import hashlib
import os
import re
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_chongdae
from test_chongdae import Project, run, write, UNCOMMITTED
import chongdae as c

PY = sys.executable
PASS = shlex.join([PY, "-c", "pass"])
README = os.path.join(test_chongdae.PLUGIN, "README.md")

# the program appends a line to ran.txt beside itself: no machine path in its text, so `did`'s portable content is the text
MARKING = ("import os\n"
           "open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ran.txt'), 'a').write('ran\\n')\n")
FAKE_KEY = "AKIA" + "QWERTYUIOPASDFGH"


def sha(data):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CHONGDAE_SESSION": "owner-a", "CHONGDAE_USER": "alice"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.out = os.path.realpath(tempfile.mkdtemp(prefix="chongdae-c7-outside-"))
        self.addCleanup(shutil.rmtree, self.out, True)

    # -- fixtures --------------------------------------------------------------------------------------------------
    def session(self, pj):
        code, out = run("init", "--session", "--goal", "c7", "--target", pj.dir)
        self.assertEqual(code, 0, out)
        return c.run_dir(pj.dir)

    def outside(self, name, body=MARKING, where=None):
        path = os.path.join(where or self.out, name)
        write(path, body)
        return path

    def ran(self, where=None):
        path = os.path.join(where or self.out, "ran.txt")
        if not os.path.exists(path):
            return 0
        with open(path, encoding="utf-8") as fh:
            return len(fh.read().splitlines())

    def task(self, pj, tid="t"):
        return pj.state()["tasks"][tid]

    def add(self, pj, tid, *extra):
        code, out = run("add", tid, "--why", "a test task: no check decides it", *extra, "--target", pj.dir)
        self.assertEqual(code, 0, out)
        return out

    def assert_allow_outside_exists(self, command):
        code, out = run(command, "--help")
        self.assertEqual(code, 0, out)
        self.assertIn("--allow-outside", out, "`%s` has no --allow-outside" % command)

    def assert_refused(self, pj, argv, name, tid="t"):
        """The command is refused, names the file, says how to keep the check reproducible or allow it, writes nothing."""
        before = pj.state()
        code, out = run(*argv, "--target", pj.dir)
        self.assertNotEqual(code, 0, "an outside check was accepted: %s" % out)
        self.assertIn(name, out)
        self.assertIn("--allow-outside", out)
        self.assertRegex(out, r"(in|into) the project")
        self.assertEqual(pj.state(), before, "the refusal wrote something")
        return out

    def outside_entries(self, pj, tid="t"):
        return self.task(pj, tid)["def"].get("checks-outside")

    def red_line(self, out, tid):
        lines = [ln for ln in out.splitlines() if "RED" in ln and ("/" + tid) in ln]
        self.assertTrue(lines, "no RED line for %s: %s" % (tid, out))
        return lines[0]


class C7_1_Refused(Base):
    def test_C7_1_add_refuses_an_absolute_outside_program_and_writes_nothing(self):
        prog = self.outside("outside_prog.py")
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["add", "t", "--check", shlex.join([PY, prog])], "outside_prog.py")
            self.assertNotIn("t", pj.state().get("tasks", {}))
            self.assertEqual(self.ran(), 0)

    def test_C7_1_add_refuses_a_relative_dotdot_program(self):
        with Project() as pj:
            sibling = tempfile.mkdtemp(prefix="chongdae-c7-sibling-", dir=os.path.dirname(pj.dir))
            self.addCleanup(shutil.rmtree, sibling, True)
            self.outside("sibling_prog.py", where=sibling)
            self.session(pj)
            rel = "../%s/sibling_prog.py" % os.path.basename(sibling)
            self.assertTrue(os.path.isfile(os.path.join(pj.dir, rel)))
            self.assert_refused(pj, ["add", "t", "--check", shlex.join([PY, rel])], "sibling_prog.py")
            self.assertNotIn("t", pj.state().get("tasks", {}))

    def test_C7_1_add_refuses_a_tilde_program(self):
        self.outside("home_prog.py")
        with Project() as pj:
            self.session(pj)
            with patch.dict(os.environ, {"HOME": self.out}):
                self.assert_refused(pj, ["add", "t", "--check", PY + " ~/home_prog.py"], "home_prog.py")
            self.assertNotIn("t", pj.state().get("tasks", {}))

    def test_C7_1_add_refuses_an_outside_file_argument(self):
        data = self.outside("outside_data.json", '{"a": 1}\n')
        with Project() as pj:
            write(os.path.join(pj.dir, "inside.py"), "import sys; open(sys.argv[1]).read()\n")
            self.session(pj)
            self.assert_refused(pj, ["add", "t", "--check", shlex.join([PY, "inside.py", data])], "outside_data.json")
            self.assertNotIn("t", pj.state().get("tasks", {}))

    def test_C7_1_add_refuses_an_outside_shebang_script_run_as_argv0(self):
        prog = self.outside("outside_hashbang", "#!/bin/sh\nexit 0\n")
        os.chmod(prog, 0o755)
        with Project() as pj:
            self.session(pj)
            self.assert_refused(pj, ["add", "t", "--check", shlex.quote(prog)], "outside_hashbang")
            self.assertNotIn("t", pj.state().get("tasks", {}))

    def test_C7_1_attaching_an_outside_check_to_an_open_task_is_refused(self):
        prog = self.outside("outside_prog.py")
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "a task with no check yet")
            self.assertEqual(self.task(pj)["def"]["checks"], [])
            self.assert_refused(pj, ["add", "t", "--check", shlex.join([PY, prog])], "outside_prog.py")
            self.assertEqual(self.task(pj)["def"]["checks"], [])

    def test_C7_1_amend_refuses_an_outside_check(self):
        prog = self.outside("outside_prog.py")
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--check", PASS)
            self.assert_refused(pj, ["amend", "t", "--check", shlex.join([PY, prog]), "--why", "a new check"], "outside_prog.py")
            ts = self.task(pj)
            self.assertEqual(ts["def"]["checks"], [shlex.split(PASS)])
            self.assertFalse(ts.get("amended"))

    def test_C7_1_interpreters_plugin_paths_inline_code_and_project_files_are_accepted(self):
        self.assert_allow_outside_exists("add")
        with Project() as pj:
            write(os.path.join(pj.dir, "inside.py"), "pass\n")
            write(os.path.join(pj.dir, "inside.json"), "{}\n")
            self.session(pj)
            accepted = {
                "inline": PASS,                                                     # argv[0] an interpreter outside: not outside
                "plugin": shlex.join([PY, "{plugin:nosuchplugin}/tool.py"]),       # resolved where it runs
                "inside": shlex.join([PY, "inside.py", "inside.json"]),
                "absinside": shlex.join([PY, os.path.join(pj.dir, "inside.py")]),  # the project's own path, not its real one
                "nofile": shlex.join([PY, "-c", "pass", os.path.join(self.out, "no-such-file.json")]),   # not an existing file
            }
            if os.path.exists("/usr/bin/env"):
                accepted["env"] = shlex.join(["/usr/bin/env", os.path.basename(PY), "-c", "pass"])
            for tid, check in accepted.items():
                code, out = run("add", tid, "--check", check, "--target", pj.dir)
                self.assertEqual(code, 0, (tid, out))
                self.assertEqual(self.task(pj, tid)["def"]["checks"], [shlex.split(check)], tid)
                self.assertFalse(self.outside_entries(pj, tid), tid)


class C7_2_Allowed(Base):
    def test_C7_2_allow_outside_records_the_program_digest_size_and_content(self):
        prog = self.outside("outside_prog.py")
        with Project() as pj:
            self.session(pj)
            check = shlex.join([PY, prog])
            self.add(pj, "t", "--check", PASS, "--check", check, "--allow-outside")
            d = self.task(pj)["def"]
            self.assertEqual(d["checks"], [shlex.split(PASS), [PY, prog]], "the argv is recorded as given")
            entries = d.get("checks-outside")
            self.assertIsInstance(entries, list)
            self.assertEqual(len(entries), 1, entries)
            e = entries[0]
            want = {"check": 1, "arg": 1, "name": "outside_prog.py", "role": "program",
                    "sha256": sha(MARKING), "size": len(MARKING.encode("utf-8")), "content": MARKING}
            self.assertEqual({k: e.get(k) for k in want}, want)
            self.assertEqual(self.ran(), 0, "add runs nothing")

    def test_C7_2_a_file_argument_keeps_its_digest_and_no_content(self):
        body = '{"lexicon": "app.x"}\n'
        data = self.outside("outside_data.json", body)
        with Project() as pj:
            write(os.path.join(pj.dir, "inside.py"), "import sys; open(sys.argv[1]).read()\n")
            self.session(pj)
            self.add(pj, "t", "--check", shlex.join([PY, "inside.py", data]), "--allow-outside")
            entries = self.outside_entries(pj)
            self.assertIsInstance(entries, list)
            self.assertEqual(len(entries), 1, entries)
            e = entries[0]
            want = {"check": 0, "arg": 2, "name": "outside_data.json", "role": "argument",
                    "sha256": sha(body), "size": len(body.encode("utf-8"))}
            self.assertEqual({k: e.get(k) for k in want}, want)
            self.assertNotIn("content", e)

    def test_C7_2_a_secret_looking_program_keeps_no_content(self):
        body = "API_KEY = '%s'\nprint('ok')\n" % FAKE_KEY
        prog = self.outside("deploy.py", body)
        with Project() as pj:
            d = self.session(pj)
            self.add(pj, "t", "--check", shlex.join([PY, prog]), "--allow-outside")
            entries = self.outside_entries(pj)
            self.assertIsInstance(entries, list)
            e = entries[0]
            self.assertEqual((e.get("role"), e.get("name"), e.get("sha256")), ("program", "deploy.py", sha(body)))
            self.assertNotIn("content", e)
            for root, _, files in os.walk(d):
                for name in files:
                    with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                        self.assertNotIn(FAKE_KEY, fh.read(), name)

    def test_C7_2_attaching_with_allow_outside_records_it(self):
        prog = self.outside("outside_prog.py")
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--brief", "no check yet")
            self.add(pj, "t", "--check", shlex.join([PY, prog]), "--allow-outside")
            self.assertEqual(self.task(pj)["def"]["checks"], [[PY, prog]])
            entries = self.outside_entries(pj)
            self.assertIsInstance(entries, list)
            self.assertEqual((entries[0].get("check"), entries[0].get("sha256")), (0, sha(MARKING)))

    def test_C7_2_amend_with_allow_outside_records_it(self):
        self.assert_allow_outside_exists("amend")
        prog = self.outside("outside_prog.py")
        with Project() as pj:
            self.session(pj)
            self.add(pj, "t", "--check", PASS)
            code, out = run("amend", "t", "--check", shlex.join([PY, prog]), "--allow-outside", "--why", "the real check",
                            "--target", pj.dir)
            self.assertEqual(code, 0, out)
            ts = self.task(pj)
            self.assertEqual(ts["def"]["checks"], [[PY, prog]])
            entries = ts["def"].get("checks-outside")
            self.assertIsInstance(entries, list)
            self.assertEqual((entries[0].get("check"), entries[0].get("role"), entries[0].get("sha256")), (0, "program", sha(MARKING)))


class C7_3_Compared(Base):
    def allowed_task(self, pj, name="outside_prog.py"):
        prog = self.outside(name)
        self.session(pj)
        self.add(pj, "t", "--check", shlex.join([PY, prog]), "--allow-outside")
        return prog

    def test_C7_3_run_stops_on_a_changed_outside_program_without_running_it(self):
        with Project() as pj:
            prog = self.allowed_task(pj)
            changed = MARKING + "# changed after add\n"
            write(prog, changed)
            code, out = run("run", "t", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertEqual(self.ran(), 0, "the changed program was run")
            self.assertNotEqual(self.task(pj)["status"], "done", out)
            self.assertIn("outside_prog.py", out)
            self.assertIn("changed since it was recorded", out)
            self.assertIn(sha(MARKING)[:6], out)
            self.assertIn(sha(changed)[:6], out)
            self.assertRegex(out, r"chongdae amend t\b")
            self.assertIn("--allow-outside", out)

    def test_C7_3_run_stops_on_a_missing_outside_program(self):
        with Project() as pj:
            prog = self.allowed_task(pj)
            os.remove(prog)
            code, out = run("run", "t", "--target", pj.dir)
            self.assertNotEqual(code, 0, out)
            self.assertNotEqual(self.task(pj)["status"], "done", out)
            self.assertIn("outside_prog.py", out)
            self.assertRegex(out, r"chongdae amend t\b")

    def test_C7_3_amend_rerecords_the_digest_and_run_decides_the_task(self):
        with Project() as pj:
            prog = self.allowed_task(pj)
            changed = MARKING + "# the new program\n"
            write(prog, changed)
            run("run", "t", "--target", pj.dir)
            self.assertEqual(self.ran(), 0)
            code, out = run("amend", "t", "--check", shlex.join([PY, prog]), "--allow-outside", "--why", "the program changed",
                            "--target", pj.dir)
            self.assertEqual(code, 0, out)
            entries = self.outside_entries(pj)
            self.assertEqual(entries[0]["sha256"], sha(changed))
            code, out = run("run", "t", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj)["status"], "done", out)
            self.assertEqual(self.ran(), 1)

    def test_C7_3_an_unchanged_outside_program_runs_and_rechecks_green(self):
        with Project() as pj:
            self.allowed_task(pj)
            code, out = run("run", "t", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.task(pj)["status"], "done", out)
            self.assertEqual(self.ran(), 1)
            self.assertEqual(run("close", *UNCOMMITTED, "--target", pj.dir)[0], 0)
            code, out = run("recheck", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertIn("still green", out)
            self.assertEqual(self.ran(), 2)

    def test_C7_3_recheck_counts_a_changed_outside_program_red_without_running_it(self):
        with Project() as pj:
            prog = self.allowed_task(pj)
            self.assertEqual(run("run", "t", "--target", pj.dir)[0], 0)
            self.assertEqual(self.ran(), 1)
            self.assertEqual(run("close", *UNCOMMITTED, "--target", pj.dir)[0], 0)
            write(prog, MARKING + "# edited in the scratch directory later\n")
            code, out = run("recheck", "--target", pj.dir)
            self.assertEqual(code, 1, out)
            line = self.red_line(out, "t")
            self.assertIn("outside_prog.py", line)
            self.assertIn("changed since it was recorded", line)
            self.assertEqual(self.ran(), 1, "recheck ran the changed program")

    def test_C7_3_recheck_counts_a_missing_outside_program_red(self):
        with Project() as pj:
            prog = self.allowed_task(pj)
            self.assertEqual(run("run", "t", "--target", pj.dir)[0], 0)
            self.assertEqual(run("close", *UNCOMMITTED, "--target", pj.dir)[0], 0)
            os.remove(prog)
            code, out = run("recheck", "--target", pj.dir)
            self.assertEqual(code, 1, out)
            self.assertIn("outside_prog.py", self.red_line(out, "t"))


class C7_4_AsBefore(Base):
    def test_C7_4_an_older_record_without_checks_outside_rechecks_as_before(self):
        old_dir = os.path.realpath(tempfile.mkdtemp(prefix="chongdae-c7-old-"))
        self.addCleanup(shutil.rmtree, old_dir, True)
        old_prog = self.outside("old_prog.py", where=old_dir)
        with Project() as pj:
            write(os.path.join(pj.dir, "inside.py"), "pass\n")
            d = self.session(pj)
            new_prog = self.outside("new_prog.py")
            self.add(pj, "new", "--check", shlex.join([PY, new_prog]), "--allow-outside")
            self.add(pj, "old", "--check", shlex.join([PY, "inside.py"]))
            code, out = run("run", "--target", pj.dir)
            self.assertEqual(code, 0, out)
            self.assertEqual(run("close", *UNCOMMITTED, "--target", pj.dir)[0], 0)
            # an older record: its check names the outside program and nothing of it is recorded
            state = c.load_state(d)
            state["tasks"]["old"]["def"]["checks"] = [[PY, old_prog]]
            state["tasks"]["old"]["def"].pop("checks-outside", None)
            c.save_state(d, state)
            write(old_prog, MARKING + "# changed: nothing recorded to compare with\n")
            write(new_prog, MARKING + "# changed\n")
            code, out = run("recheck", "--target", pj.dir)
            self.assertEqual(code, 1, out)
            self.assertIn("still green  %s/old" % os.path.basename(d), out)
            self.assertEqual(self.ran(old_dir), 1, "the older record's check runs as before")
            self.assertIn("changed since it was recorded", self.red_line(out, "new"))
            self.assertEqual(self.ran(), 1, "only the run's own check ran the new program")

    def test_C7_4_an_in_project_check_behaves_as_today(self):
        self.assert_allow_outside_exists("add")
        with Project() as pj:
            write(os.path.join(pj.dir, "inside.py"), "pass\n")
            self.session(pj)
            self.add(pj, "t", "--check", shlex.join([PY, "inside.py"]))
            self.assertFalse(self.outside_entries(pj))
            self.assertEqual(run("run", "t", "--target", pj.dir)[0], 0)
            self.assertEqual(run("close", *UNCOMMITTED, "--target", pj.dir)[0], 0)
            write(os.path.join(pj.dir, "inside.py"), "raise SystemExit(2)\n")
            code, out = run("recheck", "--target", pj.dir)
            self.assertEqual(code, 1, out)
            self.assertNotIn("changed since it was recorded", out)


class C7_5_Readme(unittest.TestCase):
    def section(self, heading):
        with open(README, encoding="utf-8") as fh:
            text = fh.read()
        start = text.find("\n" + heading + "\n")
        self.assertNotEqual(start, -1, heading)
        rest = text[start + len(heading) + 2:]
        end = re.search(r"\n#{2,3} ", rest)
        return rest[:end.start()] if end else rest

    def test_C7_5_add_says_the_refusal_and_allow_outside(self):
        sec = self.section("### `/chongdae:add`")
        self.assertIn("--allow-outside", sec)
        self.assertIn("outside the project", sec)

    def test_C7_5_amend_says_the_refusal_and_allow_outside(self):
        sec = self.section("### `/chongdae:amend`")
        self.assertIn("--allow-outside", sec)
        self.assertIn("outside the project", sec)

    def test_C7_5_the_task_record_lists_checks_outside(self):
        self.assertIn("checks-outside", self.section("### `.chongdae/run-<id>/tasks/<id>.json`"))

    def test_C7_5_recheck_says_a_changed_outside_program_is_red(self):
        sec = self.section("### `/chongdae:recheck`")
        self.assertIn("outside", sec)
        self.assertIn("changed", sec)
        self.assertIn("red", sec)

    def test_C7_5_limits_say_plan_files_and_retry_take_checked_are_not_covered(self):
        sec = self.section("## Limits")
        paras = [p for p in re.split(r"\n\s*\n|\n(?=- )", sec) if "outside" in p and "retry" in p and "--checked" in p and "plan" in p]
        self.assertTrue(paras, "Limits does not say plan files and retry/take --checked are not covered by the outside-check refusal")


if __name__ == "__main__":
    unittest.main()
