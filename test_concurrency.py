"""Subprocess checks for two sessions sharing a project, without live providers.

Run with ``python3 test_concurrency.py``. Workers coordinate through files so the
tests exercise overlap, rather than relying on which subprocess starts first.
"""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ENGINE = Path(__file__).resolve().with_name("chongdae.py")
sys.path.insert(0, str(ENGINE.parent))
import chongdae  # noqa: E402


class CommandFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chongdae-concurrency-")
        self.base = Path(self.temp.name)
        self.processes = []
        self.releases = []
        self.env = dict(os.environ, CHONGDAE_SESSION="parent", CHONGDAE_USER="test",
                        CHONGDAE_WAIT="20")
        self.project = self.make_project("project")

    def tearDown(self):
        children = set()
        for pending in self.base.glob("**/*.pending.json"):
            try:
                pid = json.loads(pending.read_text()).get("pid")
                if isinstance(pid, int):
                    children.add(pid)
            except (OSError, ValueError):
                pass
        for release in self.releases:
            release.touch()
        for proc in self.processes:
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        # A failed assertion may kill run while its detached checker/reviewer
        # is still waiting. Retire those exact test process groups before the
        # synchronization files disappear with the temporary directory.
        for pid in children:
            try:
                if os.name == "nt":
                    os.kill(pid, signal.SIGTERM)
                else:
                    os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.temp.cleanup()

    def make_project(self, name):
        p = self.base / name
        p.mkdir()
        subprocess.run(["git", "init", "-q", str(p)], check=True)
        (p / "hunsu.json").write_text(json.dumps({"settings": {"chongdae": {"commit-records": False}}}))
        self.call("init", "--session", "--goal", "concurrent sessions", project=p, code=0)
        return p

    def argv(self, args, project):
        return [sys.executable, str(ENGINE), *args, "--target", str(project)]

    def call(self, *args, project=None, code=None, env=None):
        p = project or self.project
        result = subprocess.run(self.argv(args, p), env=env or self.env, text=True,
                                capture_output=True, timeout=12)
        if code is not None:
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def start(self, *args, project=None):
        proc = subprocess.Popen(self.argv(args, project or self.project), env=self.env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes.append(proc)
        return proc

    def wait_for(self, path, proc):
        end = time.monotonic() + 10
        while not path.exists():
            self.assertIsNone(proc.poll(), "worker exited before the synchronization point")
            self.assertLess(time.monotonic(), end, "worker never reached the synchronization point")
            time.sleep(0.02)

    def finish(self, proc):
        out, err = proc.communicate(timeout=12)
        self.assertEqual(proc.returncode, 0, out + err)
        return out

    def task(self, tid):
        return json.loads(next((self.project / ".chongdae").glob("run-*/tasks/%s.json" % tid)).read_text())

    def waiting_check(self, tid="a", project=None):
        ready = self.base / (tid + "-ready")
        release = self.base / (tid + "-release")
        self.releases.append(release)
        script = self.base / (tid + "-check.py")
        script.write_text("import pathlib,sys,time\n"
                          "pathlib.Path(sys.argv[1]).touch()\n"
                          "while not pathlib.Path(sys.argv[2]).exists(): time.sleep(.02)\n")
        command = shlex.join([sys.executable, str(script), str(ready), str(release)])
        self.call("add", tid, "--role", "session", "--check", command, project=project, code=0)
        return ready, release


class ConcurrentCommands(CommandFixture):
    def test_check_attachment_is_not_lost_during_another_run(self):
        ready, release = self.waiting_check()
        self.call("add", "b", "--brief", "still being implemented", code=0)
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        check = shlex.join([sys.executable, "-c", "pass"])
        self.call("add", "b", "--check", check, code=4)
        self.assertEqual(self.task("b")["def"]["checks"], [])
        release.touch()
        self.finish(proc)
        self.call("add", "b", "--check", check, code=0)
        # R6: the public record projects a check like every public string; the exact portable argv stays local.
        portable = chongdae.portable_argv([sys.executable, "-c", "pass"])
        public = chongdae.public_projection(portable, str(self.project))[0]
        self.assertEqual(self.task("b")["def"]["checks"], [public])
        run = next((self.project / ".chongdae").glob("run-*/tasks/b.json")).parent.parent
        self.assertEqual(chongdae.load_state(str(run))["tasks"]["b"]["def"]["checks"], [portable])

    def test_second_run_does_not_start_a_second_verifier(self):
        ready, release, calls = (self.base / n for n in ("eyes-ready", "eyes-release", "eyes-calls"))
        self.releases.append(release)
        script = self.base / "eyes.py"
        script.write_text("import pathlib,sys,time,json\n"
                          "with open(sys.argv[5], 'a') as f: f.write('called\\n')\n"
                          "pathlib.Path(sys.argv[3]).touch()\n"
                          "while not pathlib.Path(sys.argv[4]).exists(): time.sleep(.02)\n"
                          "json.dump({'artifact-type':'dwitbuk/review@1','verdict':'accept','findings':[]},open(sys.argv[2],'w'))\n")
        (self.project / "hunsu.lock.json").write_text(json.dumps({"roles": {"verifier": [
            sys.executable, str(script), "{request}", "{response}", str(ready), str(release), str(calls)]}}))
        self.call("add", "a", "--check", shlex.join([sys.executable, "-c", "pass"]), code=0)
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        self.call("run", "a", code=4)
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        release.touch()
        self.finish(proc)
        self.assertEqual(calls.read_text().splitlines(), ["called"])

    def test_another_project_and_readers_still_work(self):
        other = self.make_project("other")
        ready, release = self.waiting_check()
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        self.call("status", code=0)
        self.call("show", code=0)
        self.call("report", code=0)
        self.call("recheck", code=0)
        self.call("add", "independent", "--brief", "another project", project=other, code=0)
        release.touch()
        self.finish(proc)

    def test_killed_command_releases_its_lock_without_killing_checks(self):
        ready, release = self.waiting_check()
        proc = self.start("run", "a")
        self.wait_for(ready, proc)
        proc.kill()
        proc.communicate(timeout=5)
        self.call("add", "b", "--brief", "parent resumed", code=0)
        release.touch()
        # The original checks process is detached: the next run consumes its
        # result, rather than a process lifetime being mistaken for ownership.
        self.call("run", "a", code=0)

    def test_readers_never_observe_half_written_json(self):
        target = self.base / "atomic.json"
        ready = self.base / "writer-ready"
        script = self.base / "write-json.py"
        script.write_text("import sys,pathlib\n"
                          "sys.path.insert(0,sys.argv[1])\n"
                          "import chongdae\n"
                          "p=sys.argv[2]\n"
                          "chongdae.save(p,{'n':0,'payload':'x'*100000})\n"
                          "pathlib.Path(sys.argv[3]).touch()\n"
                          "for n in range(1,201): chongdae.save(p,{'n':n,'payload':'x'*100000})\n")
        proc = subprocess.Popen([sys.executable, str(script), str(ENGINE.parent), str(target), str(ready)],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes.append(proc)
        self.wait_for(ready, proc)
        observed = 0
        end = time.monotonic() + 10
        while proc.poll() is None:
            self.assertLess(time.monotonic(), end)
            data = json.loads(target.read_text())
            self.assertEqual(len(data["payload"]), 100000)
            observed += 1
        self.finish(proc)
        self.assertGreater(observed, 0)
        self.assertEqual(json.loads(target.read_text())["n"], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
