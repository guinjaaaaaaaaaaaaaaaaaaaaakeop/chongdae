"""A run's public records are a path-normalized projection; the exact raw values stay in ignored local state."""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import chongdae as c

HERE = os.path.dirname(os.path.abspath(c.__file__))
# The engine runs in a child process with this HOME: a home that is neither the project nor a temporary directory.
HOME = "/home/teujipfixture"
USER = os.path.basename(HOME)
RUN = "run-20261030-000000-abcd"
STAMPS = ("artifact-type", "written_by")


def save_as(d, state, home=HOME):
    """c.save_state(d, state) in a child process whose home directory is `home`."""
    fd, src = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    script = "import json, sys\nimport chongdae as c\nc.save_state(sys.argv[1], json.load(open(sys.argv[2], encoding='utf-8')))\n"
    try:
        proc = subprocess.run([sys.executable, "-c", script, d, src], cwd=HERE, env=dict(os.environ, HOME=home),
                              capture_output=True, text=True)
    finally:
        os.remove(src)
    if proc.returncode:
        raise AssertionError("save_state failed: %s" % proc.stderr)


def unstamped(state):
    out = {k: v for k, v in state.items() if k not in STAMPS}
    out["tasks"] = {t: {k: v for k, v in ts.items() if k not in STAMPS} for t, ts in state.get("tasks", {}).items()}
    return out


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def machine_paths(root):
    tmp = tempfile.gettempdir()
    out = {HOME, tmp, os.path.realpath(tmp), "/tmp/", "/private/tmp", "/var/folders"}
    if root:
        out |= {os.path.abspath(root), os.path.realpath(root)}
    return out


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


class Projection(unittest.TestCase):
    def project(self, parent=None):
        root = tempfile.mkdtemp(prefix=".teujip-projection-" if parent else "projection-", dir=parent)
        self.addCleanup(shutil.rmtree, root, True)
        d = os.path.join(root, c.RUNS, RUN)
        os.makedirs(d)
        return root, d

    def assertNoMachinePath(self, text, root, where):
        for p in machine_paths(root):
            self.assertNotIn(p, text, "%s still holds %r" % (where, p))

    def leaky_task(self, root):
        tmp = tempfile.gettempdir()
        real = os.path.realpath(root)
        return {
            "status": "done", "brief": "set up the environment",
            "added-in": "session-1", "lease-held": "session-1",
            "commands": [root + "/private-command"],
            "summary": "notes in %s/notes/plan.md" % HOME,
            "touched": [root + "/src/a.py", "src/b.py"],
            "stages": {
                "newbie": {"response": {"tried": [{"command": "mktemp -d %s/newbie-environment.XXXXXX" % root, "exit": 0}],
                                        "summary": "worked in %s" % root},
                           "by": {"host": "claude", "model": "opus", "agent": "newbie"}, "when": "after"},
                "verifier": {"failed": [{"response": {"summary": "ran %s/scratch/a.py" % tmp,
                                                      "findings": [{"kind": "bug", "where": "src/a.py:3",
                                                                    "quote": "open('%s/out/y.txt')" % tmp,
                                                                    "why": "writes %s/build/out" % real}]},
                                         "by": {"host": "codex", "model": "gpt"}, "when": "after"}]},
            },
            "response": {"findings": [{"kind": "bug", "where": "src/a.py:3", "quote": "src/a.py:3 reads %s/x" % root,
                                       "why": "see /private/tmp/q and /tmp/r"}],
                         "non-claims": ["cannot see %s/.cache" % HOME]},
            "attempts": [{"summary": "first try under %s/.claude/plugins/cache/mkt/chongdae/1.24.0/chongdae.py" % HOME,
                          "touched": [root + "/src/a.py"]}],
            "review": {"summary": "reviewed /var/folders/zz/abc/T/k.txt"},
            "non-claims": [root],
        }

    def leaky_state(self, root):
        return {"status": "running", "goal": "fix %s/chongdae.py from %s/x" % (root, HOME), "non-claims": [],
                "tasks": {"environment": self.leaky_task(root), "plain": {"status": "todo", "brief": "nothing machine"}}}

    # ---------------------------------------------------------------- P1

    def test_P1_public_task_and_state_files_hold_no_machine_path(self):
        root, d = self.project()
        save_as(d, self.leaky_state(root))
        task_text = read(os.path.join(d, "tasks", "environment.json"))
        self.assertNoMachinePath(task_text, root, "tasks/environment.json")
        self.assertNoMachinePath(read(os.path.join(d, "state.json")), root, "state.json")
        self.assertNotIn("private-command", task_text)   # PRIVATE_KEYS still go to the overlay
        pub = c.load(os.path.join(d, "tasks", "environment.json"))
        self.assertEqual(pub["stages"]["newbie"]["response"]["tried"][0]["command"], "mktemp -d ./newbie-environment.XXXXXX")
        self.assertEqual(pub["stages"]["newbie"]["response"]["summary"], "worked in .")
        self.assertEqual(pub["summary"], "notes in ~/notes/plan.md")
        self.assertEqual(pub["touched"], ["./src/a.py", "src/b.py"])
        self.assertEqual(pub["non-claims"], ["."])
        self.assertEqual(pub["response"]["non-claims"], ["cannot see ~/.cache"])
        self.assertEqual(pub["response"]["findings"][0]["quote"], "src/a.py:3 reads ./x")
        failed = pub["stages"]["verifier"]["failed"][0]["response"]
        self.assertEqual(failed["findings"][0]["why"], "writes ./build/out")   # the project's realpath too
        self.assertIn("<tmp>", failed["findings"][0]["quote"])
        self.assertIn("<tmp>", failed["summary"])
        self.assertIn("<tmp>", pub["review"]["summary"])
        self.assertEqual(pub["attempts"][0]["summary"], "first try under <plugin:chongdae@1.24.0>/chongdae.py")
        self.assertEqual(pub["attempts"][0]["touched"], ["./src/a.py"])
        self.assertEqual(c.load(os.path.join(d, "state.json"))["goal"], "fix ./chongdae.py from ~/x")

    def test_P1_project_under_home_or_temp_becomes_dot(self):
        root, d = self.project()   # the project sits under a temporary directory
        home = os.path.dirname(root)   # ... and the home holds it
        state = {"status": "running", "non-claims": [], "tasks": {"a": {"status": "todo", "summary": root + "/x"}}}
        save_as(d, state, home=home)
        self.assertEqual(c.load(os.path.join(d, "tasks", "a.json"))["summary"], "./x")

    def test_P1_run_outside_chongdae_dir_has_no_project_root(self):
        parent = tempfile.mkdtemp(prefix="projection-")
        self.addCleanup(shutil.rmtree, parent, True)
        d = os.path.join(parent, "runs", RUN)
        os.makedirs(d)
        state = {"status": "running", "non-claims": [], "tasks": {"a": {"status": "todo", "summary": HOME + "/x",
                                                                          "why": parent + "/y"}}}
        save_as(d, state)
        pub = c.load(os.path.join(d, "tasks", "a.json"))
        self.assertEqual(pub["summary"], "~/x")
        self.assertFalse(pub["why"].startswith("."), pub["why"])   # no root: a temp path, not the project
        self.assertNoMachinePath(read(os.path.join(d, "tasks", "a.json")), None, "tasks/a.json")

    # ---------------------------------------------------------------- P2

    def test_P2_only_whole_path_prefixes_and_metadata_unchanged(self):
        # a project neither under the home nor under a temporary directory, so `<root>2/x` is no machine path at all
        root, d = self.project(parent=HERE)
        if any(root.startswith(p) for p in machine_paths(None)):
            self.skipTest("the checkout sits in a temporary directory")
        by = {"host": "claude", "model": "opus", "agent": "teujip", "by": USER, "effort": "high", "at": "2026-10-30T07:00:00Z"}
        keep = {"quote": "src/a.py:3", "rel": "./x", "doc": "README.md#versioning", "sig": "--by " + USER,
                "author": "Author: %s <a@example.invalid>" % USER, "old": HOME + "-old/x", "sibling": root + "2/x",
                "n": 3, "t": True, "z": None, "docs" + root + "/key": "v"}   # R3: a key with the root at a path start is refused; inside another path it stays
        task = {"status": "done", "summary": HOME + "/x", "where": root + "/y", "by": by, "keep": keep,
                "stages": {"newbie": {"response": {"quote": "src/a.py:3"}, "by": by, "when": "after"}},
                "read": [root + "/raw-read"]}
        save_as(d, {"status": "running", "non-claims": [], "tasks": {"a": task}})
        pub = c.load(os.path.join(d, "tasks", "a.json"))
        self.assertEqual(pub["summary"], "~/x")
        self.assertEqual(pub["where"], "./y")
        self.assertEqual(pub["keep"], keep)
        self.assertEqual(pub["by"], by)
        self.assertEqual(pub["stages"]["newbie"]["by"], by)
        self.assertEqual(pub["stages"]["newbie"]["response"], {"quote": "src/a.py:3"})
        self.assertNotIn("read", pub)
        self.assertEqual(c.load(os.path.join(d, c.LOCAL, "tasks", "a.json"))["read"], [root + "/raw-read"])   # unprojected

    def test_P2_root_and_home_end_at_path_boundaries(self):
        root, d = self.project()
        cases = {"semi": "cd %s; make" % root, "alone": root, "paren": "(%s)" % root, "quoted": '"%s"' % root,
                 "colon": root + ":3", "comma": "%s,%s" % (root, HOME), "pipe": "ls %s|wc" % root, "amp": "cd %s&&x" % root,
                 "tick": "`%s`" % root, "single": "'%s'" % HOME, "space": HOME + " and more", "homeend": HOME}
        save_as(d, {"status": "running", "non-claims": [], "tasks": {"a": dict(cases, status="todo")}})
        pub = c.load(os.path.join(d, "tasks", "a.json"))
        self.assertEqual({k: pub[k] for k in cases}, {
            "semi": "cd .; make", "alone": ".", "paren": "(.)", "quoted": '"."', "colon": ".:3", "comma": ".,~",
            "pipe": "ls .|wc", "amp": "cd .&&x", "tick": "`.`", "single": "'~'", "space": "~ and more", "homeend": "~"})

    # ---------------------------------------------------------------- P3

    def test_P3_overlay_mirrors_raw_and_load_state_returns_it(self):
        root, d = self.project()
        given = self.leaky_state(root)
        save_as(d, copy.deepcopy(given))
        pub = c.load(os.path.join(d, "tasks", "environment.json"))
        self.assertNoMachinePath(json.dumps(pub), root, "tasks/environment.json")
        overlay = c.load(os.path.join(d, c.LOCAL, "tasks", "environment.json"))
        merged = c.merge_private(copy.deepcopy(pub), overlay)
        self.assertEqual({k: v for k, v in merged.items() if k not in STAMPS}, given["tasks"]["environment"])
        self.assertIn(root + "/src/a.py", list(strings(overlay)))   # a raw string at a list index
        run_overlay = c.load(os.path.join(d, c.LOCAL, "state.json"))
        self.assertEqual(c.merge_private(c.load(os.path.join(d, "state.json")), run_overlay)["goal"], given["goal"])
        loaded = c.load_state(d)
        self.assertEqual(unstamped(loaded), given)
        self.assertEqual(loaded["tasks"]["environment"]["added-in"], "session-1")
        self.assertEqual(loaded["tasks"]["environment"]["lease-held"], "session-1")
        self.assertEqual(loaded["tasks"]["environment"]["touched"][0], root + "/src/a.py")

    def test_P3_raw_values_survive_a_restart(self):
        root, d = self.project()
        given = self.leaky_state(root)
        save_as(d, copy.deepcopy(given))
        self.assertNoMachinePath(read(os.path.join(d, "tasks", "environment.json")), root, "tasks/environment.json")
        script = "import json, sys\nimport chongdae as c\nprint(json.dumps(c.load_state(sys.argv[1])))\n"
        proc = subprocess.run([sys.executable, "-c", script, d], cwd=HERE, env=dict(os.environ, HOME=HOME),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        restarted = json.loads(proc.stdout)
        self.assertEqual(unstamped(restarted), given)
        self.assertEqual(restarted["tasks"]["environment"]["added-in"], "session-1")
        self.assertEqual(restarted["tasks"]["environment"]["lease-held"], "session-1")
        self.assertEqual(restarted["tasks"]["environment"]["attempts"][0]["touched"], [root + "/src/a.py"])

    def test_P3_process_death_between_public_and_overlay_writes_recovers_both(self):
        root, d = self.project()
        save_as(d, self.leaky_state(root))
        script = """
import json, os, sys
import chongdae as c
d, root = sys.argv[1], sys.argv[2]
state = c.load_state(d)
state['tasks']['environment']['summary'] = 'second pass in %s/again' % root
state['tasks']['environment']['touched'] = [root + '/src/c.py']
save = c.save_changed
def crash(path, data):
    if path == os.path.join(d, 'local', 'tasks', 'environment.json'):
        os._exit(77)
    save(path, data)
c.save_changed = crash
c.save_state(d, state)
"""
        proc = subprocess.run([sys.executable, "-c", script, d, root], cwd=HERE, env=dict(os.environ, HOME=HOME))
        self.assertEqual(proc.returncode, 77)
        public = os.path.join(d, "tasks", "environment.json")
        self.assertNoMachinePath(read(public), root, "tasks/environment.json after the crash")
        c.recover_state(d)
        c.recover_state(d)
        self.assertNoMachinePath(read(public), root, "tasks/environment.json after recovery")
        self.assertEqual(c.load(public)["summary"], "second pass in ./again")
        overlay = list(strings(c.load(os.path.join(d, c.LOCAL, "tasks", "environment.json"))))
        self.assertIn("second pass in %s/again" % root, overlay)
        self.assertIn(root + "/src/c.py", overlay)
        task = c.load_state(d)["tasks"]["environment"]
        self.assertEqual(task["summary"], "second pass in %s/again" % root)
        self.assertEqual(task["touched"], [root + "/src/c.py"])
        self.assertEqual(task["added-in"], "session-1")
        self.assertEqual(c.load(os.path.join(d, c.LOCAL, "state-transaction.json"))["phase"], "committed")

    # ---------------------------------------------------------------- P4

    def test_P4_consumed_response_file_keeps_its_bytes(self):
        root, d = self.project()
        answer = {"summary": "built in %s and %s/notes" % (root, HOME), "touched": [root + "/src/a.py"],
                  "tried": [{"command": "mktemp -d %s/newbie.XXXXXX" % root}],
                  "findings": [{"kind": "bug", "where": "src/a.py:3", "quote": "x = '%s/q'" % tempfile.gettempdir(), "why": "w"}]}
        path = os.path.join(d, c.LOCAL, "environment.response.json")
        request = os.path.join(d, c.LOCAL, "environment.request.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(answer, separators=(",", ":")))   # deliberately not the engine's own formatting
        with open(request, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"target": root, "home": HOME}))
        before, before_request = sha(path), sha(request)
        consumed = c.load(path)
        task = {"status": "done", "response": consumed,
                "stages": {"newbie": {"response": copy.deepcopy(consumed), "by": {"host": "claude"}, "when": "after"}}}
        save_as(d, {"status": "running", "non-claims": [], "tasks": {"environment": task}})
        self.assertEqual(sha(path), before)
        self.assertEqual(sha(request), before_request)
        self.assertNoMachinePath(read(os.path.join(d, "tasks", "environment.json")), root, "tasks/environment.json")
        loaded = c.load_state(d)["tasks"]["environment"]
        self.assertEqual(loaded["response"], answer)
        self.assertEqual(loaded["stages"]["newbie"]["response"], answer)

    # ---------------------------------------------------------------- P5

    def test_P5_old_shape_records_are_not_rewritten_until_changed(self):
        root, d = self.project()
        old_a = {"artifact-type": "chongdae/task@1", "written_by": "chongdae 1.24.0", "status": "doing",
                 "summary": "worked in %s/src and %s/notes" % (root, HOME), "touched": [root + "/src/a.py"]}
        old_b = {"artifact-type": "chongdae/task@1", "written_by": "chongdae 1.24.0", "status": "done", "summary": root + "/b"}
        write_json(os.path.join(d, "tasks", "a.json"), old_a)
        write_json(os.path.join(d, "tasks", "b.json"), old_b)
        write_json(os.path.join(d, "state.json"), {"artifact-type": "chongdae/run@1", "written_by": "chongdae 1.24.0",
                                                   "status": "running", "goal": "g in " + root, "non-claims": []})
        write_json(os.path.join(d, c.LOCAL, "tasks", "a.json"), {"added-in": "session-0"})   # an old overlay: PRIVATE_KEYS only
        files = [os.path.join(d, "tasks", "a.json"), os.path.join(d, "tasks", "b.json"), os.path.join(d, "state.json")]
        before = {p: sha(p) for p in files}
        state = c.load_state(d)
        self.assertEqual(state["tasks"]["a"]["added-in"], "session-0")
        save_as(d, state)
        self.assertEqual({p: sha(p) for p in files}, before)
        state = c.load_state(d)
        state["tasks"]["a"]["status"] = "done"
        save_as(d, state)
        self.assertEqual(sha(files[1]), before[files[1]])
        self.assertNoMachinePath(read(files[0]), root, "tasks/a.json once changed")
        self.assertEqual(c.load(files[0])["touched"], ["./src/a.py"])
        a = c.load_state(d)["tasks"]["a"]
        self.assertEqual(a["summary"], old_a["summary"])
        self.assertEqual(a["touched"], old_a["touched"])
        self.assertEqual(a["added-in"], "session-0")
        self.assertEqual(a["status"], "done")

    # ---------------------------------------------------------------- P6

    def test_P6_record_commit_holds_only_the_projection(self):
        root, d = self.project()
        git = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True).stdout
        git("init", "-q")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.invalid")
        git("config", "commit.gpgsign", "false")
        save_as(d, self.leaky_state(root))
        self.assertTrue(c.commit_record(root, RUN, "projection"))
        shown = git("show", "HEAD:%s/%s/tasks/environment.json" % (c.RUNS, RUN))
        self.assertIn("newbie-environment.XXXXXX", shown)
        self.assertNoMachinePath(shown, root, "the committed tasks/environment.json")
        self.assertNoMachinePath(git("show", "HEAD:%s/%s/state.json" % (c.RUNS, RUN)), root, "the committed state.json")
        tracked = git("ls-tree", "-r", "--name-only", "HEAD").split("\n")
        self.assertEqual([t for t in tracked if "/%s/" % c.LOCAL in t], [])

    # ---------------------------------------------------------------- P7

    def test_P7_public_projection_is_pure_and_merges_back(self):
        root, d = self.project()
        home = os.path.expanduser("~")
        obj = {"summary": "in %s and %s/x" % (root, home), "list": [root + "/a", "src/b", 3, None],
               "nested": {"response": {"tried": [{"command": "mktemp -d %s/n.XXXXXX" % root}]}}, "by": {"host": "claude"}}
        snapshot = copy.deepcopy(obj)
        listing = sorted(os.walk(root))
        public, raws = c.public_projection(obj, root)
        self.assertEqual(obj, snapshot)
        self.assertEqual(sorted(os.walk(root)), listing)
        self.assertEqual(public["summary"], "in . and ~/x")
        self.assertEqual(public["list"], ["./a", "src/b", 3, None])
        self.assertEqual(public["nested"]["response"]["tried"][0]["command"], "mktemp -d ./n.XXXXXX")
        self.assertEqual(public["by"], {"host": "claude"})
        self.assertEqual(c.merge_private(copy.deepcopy(public), copy.deepcopy(raws)), obj)

    def test_P7_public_projection_without_target_has_no_root(self):
        home = os.path.expanduser("~")
        obj = {"a": home + "/x", "b": ["./y", "/tmp/z"]}
        public, raws = c.public_projection(obj, None)
        self.assertEqual(public["a"], "~/x")
        self.assertEqual(public["b"][0], "./y")
        self.assertNotIn("/tmp/", public["b"][1])
        self.assertEqual(c.merge_private(copy.deepcopy(public), raws), {"a": home + "/x", "b": ["./y", "/tmp/z"]})

    def test_P7_save_state_uses_public_projection(self):
        root, d = self.project()
        with mock.patch.object(c, "public_projection", wraps=c.public_projection) as spy:
            c.save_state(d, {"status": "running", "non-claims": [], "tasks": {"a": {"status": "todo", "summary": root + "/x"}}})
        targets = [call.args[1] if len(call.args) > 1 else call.kwargs.get("target") for call in spy.call_args_list]
        self.assertIn(os.path.realpath(root), [os.path.realpath(t) for t in targets if t])


    # ---------------------------------------------------------------- P2-rel

    REL = {"src": "src/tmp/a.py", "dot": "./tmp/out", "fixture": "tests/fixtures/tmp/x.json",
           "build": "build/var/folders/k", "private": "a/private/tmp/b"}
    # an absolute temp path at a path start: what precedes it is kept, the temp prefix becomes <tmp>
    ABS = {"tmp": ("/tmp/x", ""), "see": ("see /private/tmp/q", "see "), "out": ("--out=/tmp/y", "--out="),
           "paren": ("('/var/folders/zz/T/k')", "('"), "path": ("PATH=/usr/bin:/tmp/x", "PATH=/usr/bin:")}

    def assertTmpProjected(self, raw, head, public, where):
        self.assertTrue(public.startswith(head + "<tmp>"), "%s: %r -> %r" % (where, raw, public))
        # the kept head may itself hold a relative tmp segment (cp src/tmp/a.py ...); only the rest is checked
        for p in ("/tmp", "/private/tmp", "/var/folders"):
            self.assertNotIn(p, public[len(head):], "%s: %r -> %r" % (where, raw, public))
        if raw.endswith("')"):
            self.assertTrue(public.endswith("')"), "%s: %r -> %r" % (where, raw, public))

    def rel_task(self):
        rel, ab = self.REL, {k: v[0] for k, v in self.ABS.items()}
        return {"status": "done", "summary": "edited " + rel["src"], "rel": dict(rel), "abs": dict(ab),
                "touched": list(rel.values()), "where": rel["build"],
                "stages": {"newbie": {"response": {"tried": [{"command": "cp %s %s" % (rel["dot"], rel["fixture"])},
                                                             {"command": ab["out"]}]},
                                      "by": {"host": "claude"}, "when": "after"},
                           "verifier": {"failed": [{"response": {"findings": [{"kind": "bug", "where": rel["private"],
                                                                                "quote": rel["src"], "why": ab["see"]}]},
                                                    "by": {"host": "codex"}, "when": "after"}]}},
                "response": {"non-claims": [rel["fixture"], ab["paren"]]},
                "attempts": [{"summary": rel["dot"], "touched": [rel["private"], ab["tmp"]]}]}

    def test_P2_rel_save_state_keeps_relative_tmp_segments(self):
        root, d = self.project()
        task = self.rel_task()
        given = {"status": "running", "goal": "fix " + self.REL["src"], "non-claims": [], "tasks": {"a": copy.deepcopy(task)}}
        save_as(d, copy.deepcopy(given))
        pub = c.load(os.path.join(d, "tasks", "a.json"))
        self.assertEqual(pub["rel"], self.REL)
        self.assertEqual(pub["summary"], "edited src/tmp/a.py")
        self.assertEqual(pub["where"], "build/var/folders/k")
        self.assertEqual(pub["touched"], list(self.REL.values()))
        self.assertEqual(pub["stages"]["newbie"]["response"]["tried"][0]["command"], "cp ./tmp/out tests/fixtures/tmp/x.json")
        finding = pub["stages"]["verifier"]["failed"][0]["response"]["findings"][0]
        self.assertEqual((finding["where"], finding["quote"]), ("a/private/tmp/b", "src/tmp/a.py"))
        self.assertEqual(pub["response"]["non-claims"][0], "tests/fixtures/tmp/x.json")
        self.assertEqual(pub["attempts"][0]["summary"], "./tmp/out")
        self.assertEqual(pub["attempts"][0]["touched"][0], "a/private/tmp/b")
        self.assertEqual(c.load(os.path.join(d, "state.json"))["goal"], "fix src/tmp/a.py")
        self.assertEqual(unstamped(c.load_state(d)), given)

    def test_P2_rel_save_state_absolute_tmp_still_projected(self):
        root, d = self.project()
        task = self.rel_task()
        given = {"status": "running", "goal": "write " + self.ABS["out"][0], "non-claims": [], "tasks": {"a": copy.deepcopy(task)}}
        save_as(d, copy.deepcopy(given))
        pub = c.load(os.path.join(d, "tasks", "a.json"))
        for k, (raw, head) in self.ABS.items():
            self.assertTmpProjected(raw, head, pub["abs"][k], "tasks/a.json abs.%s" % k)
        self.assertTmpProjected(self.ABS["out"][0], "--out=", pub["stages"]["newbie"]["response"]["tried"][1]["command"], "tried[1]")
        self.assertTmpProjected(self.ABS["see"][0], "see ", pub["stages"]["verifier"]["failed"][0]["response"]["findings"][0]["why"], "why")
        self.assertTmpProjected(self.ABS["paren"][0], "('", pub["response"]["non-claims"][1], "non-claims[1]")
        self.assertTmpProjected(self.ABS["tmp"][0], "", pub["attempts"][0]["touched"][1], "attempts touched[1]")
        self.assertTmpProjected(self.ABS["out"][0], "write --out=", c.load(os.path.join(d, "state.json"))["goal"], "goal")
        # ... while the relative ones in the very same file stay as they are
        self.assertEqual(pub["rel"], self.REL)
        self.assertEqual(pub["attempts"][0]["touched"][0], "a/private/tmp/b")
        loaded = c.load_state(d)
        self.assertEqual(unstamped(loaded), given)
        self.assertEqual(loaded["tasks"]["a"]["abs"], {k: v[0] for k, v in self.ABS.items()})

    def test_P2_rel_public_projection_relative_unchanged_absolute_tmp(self):
        obj = {"rel": dict(self.REL), "abs": {k: v[0] for k, v in self.ABS.items()},
               "list": list(self.REL.values()) + [v[0] for v in self.ABS.values()],
               "mixed": "cp src/tmp/a.py /tmp/x"}
        snapshot = copy.deepcopy(obj)
        public, raws = c.public_projection(obj, None)
        self.assertEqual(obj, snapshot)
        self.assertEqual(public["rel"], self.REL)
        self.assertEqual(public["list"][:len(self.REL)], list(self.REL.values()))
        for i, (k, (raw, head)) in enumerate(self.ABS.items()):
            self.assertTmpProjected(raw, head, public["abs"][k], "abs.%s" % k)
            self.assertTmpProjected(raw, head, public["list"][len(self.REL) + i], "list[%d]" % (len(self.REL) + i))
        self.assertTmpProjected("cp src/tmp/a.py /tmp/x", "cp src/tmp/a.py ", public["mixed"], "mixed")
        self.assertEqual(c.merge_private(copy.deepcopy(public), copy.deepcopy(raws)), obj)

    def test_P2_rel_public_projection_with_target_keeps_relative(self):
        root, d = self.project()
        obj = {"rel": dict(self.REL), "abs": {k: v[0] for k, v in self.ABS.items()}, "root": root + "/src/tmp/a.py"}
        public, raws = c.public_projection(copy.deepcopy(obj), root)
        self.assertEqual(public["rel"], self.REL)
        self.assertEqual(public["root"], "./src/tmp/a.py")
        for k, (raw, head) in self.ABS.items():
            self.assertTmpProjected(raw, head, public["abs"][k], "abs.%s" % k)
        self.assertEqual(c.merge_private(copy.deepcopy(public), copy.deepcopy(raws)), obj)

    def test_P2_rel_neutral_path_unchanged(self):
        # neutral_path itself keeps its old behaviour for its callers (portable, asked/); only the projection changes
        self.assertEqual(c.neutral_path("/tmp/x", None), "<tmp>")
        self.assertEqual(c.neutral_path("src/tmp/a.py", None), "src<tmp>")
        public, _ = c.public_projection({"s": "src/tmp/a.py"}, None)
        self.assertEqual(public["s"], "src/tmp/a.py")


# ==================================================================== contract R (a follow-up to P)

ENGINE = os.path.join(HERE, "chongdae.py")
SESSION = "teujip-r-session"
# R1's mocked machine: a home and a project root that are neither under a temporary directory nor each other
R_HOME = "/home/person"
R_ROOT = "/work/project"
PLUGIN = "/.claude/plugins/cache/mkt/chongdae/1.24.0/chongdae.py"


def project_as(obj, target, home):
    """c.public_projection(obj, target) in a child process whose home directory (HOME, as expanduser reads it) is `home`."""
    script = ("import json, sys\nimport chongdae as c\n"
              "pub, raws = c.public_projection(json.loads(sys.argv[1]), sys.argv[2] or None)\n"
              "print(json.dumps([pub, raws]))\n")
    proc = subprocess.run([sys.executable, "-c", script, json.dumps(obj), target or ""], cwd=HERE,
                          env=dict(os.environ, HOME=home), capture_output=True, text=True)
    if proc.returncode:
        raise AssertionError("public_projection failed: %s" % proc.stderr)
    return json.loads(proc.stdout)


def engine_env(**extra):
    """A normal (parent) session's env for an engine subprocess: no AGENT_WORKER inherited from a hired worker."""
    env = dict(os.environ, HOME=HOME, CHONGDAE_SESSION=SESSION, **extra)
    env.pop("AGENT_WORKER", None)
    return env


def cli(*argv, cwd=HERE, timeout=300):
    proc = subprocess.run([sys.executable, ENGINE, *argv], cwd=cwd, env=engine_env(), capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr


def git_repo(prefix):
    root = tempfile.mkdtemp(prefix=prefix)
    git = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True).stdout
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "commit.gpgsign", "false")
    with open(os.path.join(root, "code.py"), "w", encoding="utf-8") as fh:
        fh.write("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    return root, git


def run_dirs(target):
    base = os.path.join(target, c.RUNS)
    return sorted(os.path.join(base, n) for n in os.listdir(base) if n.startswith("run-")) if os.path.isdir(base) else []


def public_files(d):
    """Every file of a run directory outside its local/ part: path -> sha256."""
    out = {}
    for dirpath, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if not (dirpath == d and x == c.LOCAL)]
        for f in files:
            out[os.path.relpath(os.path.join(dirpath, f), d)] = sha(os.path.join(dirpath, f))
    return out


def all_files(d):
    out = {}
    for dirpath, dirs, files in os.walk(d):
        for f in files:
            out[os.path.relpath(os.path.join(dirpath, f), d)] = sha(os.path.join(dirpath, f))
    return out


def keys_of(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from keys_of(v)
    elif isinstance(o, list):
        for v in o:
            yield from keys_of(v)


def projected_literal_dirs(top):
    """Names a projected string would leave behind if the engine used it as a path: `<tmp>`, `~`, `<plugin:...>`, `<root>`."""
    found = []
    for dirpath, dirs, files in os.walk(top):
        dirs[:] = [x for x in dirs if x != ".git"]
        for n in dirs + files:
            if n == "~" or n.startswith("<") or "<tmp>" in n:
                found.append(os.path.join(dirpath, n))
    return found


def load_state_in_child(d):
    script = "import json, sys\nimport chongdae as c\nprint(json.dumps(c.load_state(sys.argv[1])))\n"
    proc = subprocess.run([sys.executable, "-c", script, d], cwd=HERE, env=engine_env(), capture_output=True, text=True)
    if proc.returncode:
        raise AssertionError("load_state failed: %s" % proc.stderr)
    return json.loads(proc.stdout)


def load_plan_in_child(d):
    script = "import json, sys\nimport chongdae as c\nprint(json.dumps(c.load_plan(sys.argv[1])))\n"
    proc = subprocess.run([sys.executable, "-c", script, d], cwd=HERE, env=engine_env(), capture_output=True, text=True)
    if proc.returncode:
        raise AssertionError("load_plan failed: %s" % proc.stderr)
    return json.loads(proc.stdout)


def machine_path_key():
    cls = getattr(c, "MachinePathKey", None)
    if not (isinstance(cls, type) and issubclass(cls, SystemExit)):
        raise AssertionError("chongdae.MachinePathKey is not a SystemExit subclass: %r" % (cls,))
    return cls


class ProjectionR(unittest.TestCase):
    project = Projection.project
    assertNoMachinePath = Projection.assertNoMachinePath
    REL = Projection.REL

    # ---------------------------------------------------------------- R1

    R1_KEEP = ["docs/home/person/readme.md", "x/home/person", "docs/work/project/readme.md", "x/work/project",
               "docs" + R_HOME + PLUGIN, "src/tmp/a.py", "build/var/folders/k", R_HOME + "-old/x", R_ROOT + "2/x"]
    R1_CHANGE = {
        "/home/person/notes": "~/notes", "cd /home/person/x": "cd ~/x", R_HOME: "~",
        "/work/project/src/a.py": "./src/a.py", "cd /work/project": "cd .", R_ROOT: ".",
        # every left boundary R1 names
        "a=/home/person/x": "a=~/x", "(/home/person/x)": "(~/x)", "[/work/project/a]": "[./a]", "a,/home/person/x": "a,~/x",
        "a:/home/person/x": "a:~/x", "a;/work/project/x": "a;./x", "a|/home/person/x": "a|~/x", "a&/home/person/x": "a&~/x",
        "a>/home/person/log": "a>~/log", "'/home/person/x'": "'~/x'", '"/work/project/x"': '"./x"', "`/home/person/x`": "`~/x`",
        "a\t/home/person/x": "a\t~/x",
        # both in one string: only the one at a path start goes
        "see /home/person/x and docs/home/person/y": "see ~/x and docs/home/person/y",
        "cd /work/project; cat docs/work/project/z": "cd .; cat docs/work/project/z",
        # P2's examples still hold
        "cd /work/project; make": "cd .; make", "/work/project:3": ".:3", "/work/project,/home/person": ".,~",
        "ls /work/project|wc": "ls .|wc", "cd /work/project&&x": "cd .&&x", "/home/person and more": "~ and more",
    }

    def test_R1_public_projection_replaces_a_prefix_only_where_a_path_begins(self):
        obj = {"keep": list(self.R1_KEEP), "change": list(self.R1_CHANGE)}
        public, raws = project_as(obj, R_ROOT, R_HOME)
        self.assertEqual(dict(zip(self.R1_KEEP, public["keep"])), {k: k for k in self.R1_KEEP})
        self.assertEqual(dict(zip(self.R1_CHANGE, public["change"])), self.R1_CHANGE)
        self.assertEqual(c.merge_private(copy.deepcopy(public), raws), obj)

    def test_R1_docs_home_and_docs_root_stay_unchanged(self):
        public, _ = project_as({"h": "docs/home/person/readme.md", "r": "docs/work/project/readme.md"}, R_ROOT, R_HOME)
        self.assertEqual(public, {"h": "docs/home/person/readme.md", "r": "docs/work/project/readme.md"})

    def test_R1_plugin_cache_path_only_at_a_path_start(self):
        at_start = R_HOME + PLUGIN
        inside = "docs" + R_HOME + PLUGIN
        codex = "run " + R_HOME + "/.codex/plugins/cache/mkt/chongdae/1.24.0/x.py"
        public, raws = project_as({"a": at_start, "b": inside, "c": codex}, R_ROOT, R_HOME)
        self.assertEqual(public["a"], "<plugin:chongdae@1.24.0>/chongdae.py")
        self.assertEqual(public["b"], inside)
        self.assertTrue(public["c"].startswith("run <plugin:"), public["c"])
        self.assertNotIn(R_HOME, public["c"])
        self.assertEqual(c.merge_private(copy.deepcopy(public), raws), {"a": at_start, "b": inside, "c": codex})

    def test_R1_temp_prefix_rules_still_hold_with_the_mocked_home(self):
        tmp = tempfile.gettempdir()
        public, _ = project_as({"rel": dict(self.REL), "abs": "--out=%s/y" % tmp, "inside": "docs%s/y" % tmp}, R_ROOT, R_HOME)
        self.assertEqual(public["rel"], self.REL)
        self.assertTrue(public["abs"].startswith("--out=<tmp>"), public["abs"])
        self.assertEqual(public["inside"], "docs%s/y" % tmp)

    def test_R1_save_state_keeps_prefixes_inside_another_path(self):
        root, d = self.project()
        real = os.path.realpath(root)
        inside = ["docs%s/readme.md" % HOME, "x" + HOME, "docs%s/readme.md" % root, "build%s/y" % real]
        mixed = "see %s/x and docs%s/y" % (HOME, HOME)
        task = {"status": "done", "summary": "plain",
                "response": {"summary": inside[0], "non-claims": list(inside), "mixed": mixed},
                "stages": {"newbie": {"response": {"summary": inside[2], "tried": [{"command": "cat " + inside[3]}]},
                                      "by": {"host": "claude"}, "when": "after"}},
                "attempts": [{"summary": inside[1], "touched": [inside[2], inside[3]]}]}
        given = {"status": "running", "non-claims": [], "tasks": {"a": copy.deepcopy(task)}}
        save_as(d, copy.deepcopy(given))
        pub = c.load(os.path.join(d, "tasks", "a.json"))
        self.assertEqual(pub["response"]["summary"], inside[0])
        self.assertEqual(pub["response"]["non-claims"], inside)
        self.assertEqual(pub["response"]["mixed"], "see ~/x and docs%s/y" % HOME)
        self.assertEqual(pub["stages"]["newbie"]["response"]["summary"], inside[2])
        self.assertEqual(pub["stages"]["newbie"]["response"]["tried"][0]["command"], "cat " + inside[3])
        self.assertEqual(pub["attempts"][0], {"summary": inside[1], "touched": [inside[2], inside[3]]})
        self.assertEqual(unstamped(c.load_state(d)), given)

    # ---------------------------------------------------------------- R2

    # These are mocked strings on this (macOS) host — HOME set to a Windows-style string in a child process — not a
    # Windows run; they are no evidence for a live Windows host.
    WIN_HOME = "C:\\Users\\person"
    R2 = {"C:\\Users\\person\\private.py": "~\\private.py", "C:\\Users\\person": "~", "see C:\\Users\\person\\a": "see ~\\a",
          "C:\\Users\\personal\\x": "C:\\Users\\personal\\x", "docs\\C:\\Users\\person\\x": "docs\\C:\\Users\\person\\x",
          "C:\\Users\\person\\a b\\c.txt": "~\\a b\\c.txt", "C:\\Users\\person/x": "~/x"}

    def test_R2_backslash_home_is_followed_by_a_backslash_separator(self):
        obj = {"s": list(self.R2)}
        public, raws = project_as(obj, None, self.WIN_HOME)
        self.assertEqual(dict(zip(self.R2, public["s"])), self.R2)
        self.assertEqual(c.merge_private(copy.deepcopy(public), raws), obj)

    def test_R2_case_and_drive_variants_are_not_recognized(self):
        # the stated limit: c:\users\person is not C:\Users\person, and stays as written
        public, _ = project_as({"s": "c:\\users\\person\\x"}, None, self.WIN_HOME)
        self.assertEqual(public["s"], "c:\\users\\person\\x")

    # ---------------------------------------------------------------- R3

    def test_R3_machine_path_key_is_a_systemexit(self):
        self.assertTrue(issubclass(machine_path_key(), SystemExit))

    def test_R3_root_key_at_top_level_is_refused(self):
        refusal = machine_path_key()
        root, d = self.project()
        with self.assertRaises(refusal) as caught:
            c.public_projection({root + "/a": 1, "plain": "x"}, root)
        self.assertIn("./a", str(caught.exception))
        self.assertNotIn(root, str(caught.exception))

    def test_R3_home_key_nested_in_a_list_item_names_its_location(self):
        refusal = machine_path_key()
        root, d = self.project()
        home = os.path.expanduser("~")
        with self.assertRaises(refusal) as caught:
            c.public_projection({"tasks": [{"x": {home + "/k": 1}}]}, root)
        msg = str(caught.exception)
        self.assertIn("tasks[0].x", msg)
        self.assertIn("~/k", msg)

    def test_R3_ordinary_keys_are_accepted_unchanged(self):
        machine_path_key()
        root, d = self.project()
        home = os.path.expanduser("~")
        obj = {"stages": {"newbie": {"by": {"host": "claude"}, "tried": []}, "verifier": {}},
               "src/a.py": 1, "./x": 2, "README.md#versioning": 3, "~/x": 4, "<tmp>": 5,
               "docs" + home + "/k": 6, "docs" + root + "/k": 7}
        public, raws = c.public_projection(copy.deepcopy(obj), root)
        self.assertEqual(sorted(public), sorted(obj))
        self.assertEqual(c.merge_private(copy.deepcopy(public), raws), obj)

    def test_R3_colliding_keys_are_refused_not_merged(self):
        refusal = machine_path_key()
        root, d = self.project()
        with self.assertRaises(refusal):
            c.public_projection({"m": {root + "/a": 1, "./a": 2}}, root)

    def test_R3_save_state_refusal_leaves_every_byte(self):
        refusal = machine_path_key()
        root, d = self.project()
        given = {"status": "running", "goal": "g in " + root, "non-claims": [],
                 "tasks": {"a": {"status": "doing", "added-in": "session-1", "summary": "in %s/x" % root}}}
        c.save_state(d, copy.deepcopy(given))
        state = c.load_state(d)
        state["tasks"]["a"]["summary"] = "second in %s/y" % root
        c.save_state(d, state)   # a previous generation stands before the refused save
        response = os.path.join(d, c.LOCAL, "a.response.json")
        with open(response, "w", encoding="utf-8") as fh:
            fh.write('{"summary":"in %s/x"}' % root)
        for p in ("tasks/a.json", "local/tasks/a.json", "state.json", "local/state-transaction.json"):
            self.assertTrue(os.path.exists(os.path.join(d, p)), p)
        before = all_files(root)
        listing = sorted((p, sorted(ds), sorted(fs)) for p, ds, fs in os.walk(root))
        state = c.load_state(d)
        state["tasks"]["a"]["summary"] = "third"
        state["tasks"]["a"]["notes"] = {root + "/k": "v"}
        with self.assertRaises(refusal):
            c.save_state(d, state)
        self.assertEqual(all_files(root), before)
        self.assertEqual(sorted((p, sorted(ds), sorted(fs)) for p, ds, fs in os.walk(root)), listing)
        self.assertEqual(c.load_state(d)["tasks"]["a"]["summary"], "second in %s/y" % root)

    # ---------------------------------------------------------------- R4a

    def test_R4a_close_waits_on_the_real_main_lock_not_a_projected_one(self):
        main, git = git_repo("teujip-r4a-")
        self.addCleanup(shutil.rmtree, main, True)
        scratch = tempfile.mkdtemp(prefix="teujip-r4a-cwd-")
        self.addCleanup(shutil.rmtree, scratch, True)
        code, out = cli("init", "--session", "--goal", "g", "--worktree", "--target", main)
        self.assertEqual(code, 0, out)
        wt_root = os.path.join(main, c.RUNS, "wt")
        child = os.path.join(wt_root, os.listdir(wt_root)[0])
        with open(os.path.join(child, "code.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 2\n")
        code, out = cli("add", "T1", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", child)
        self.assertEqual(code, 0, out)
        code, out = cli("run", "--target", child)
        self.assertEqual(code, 0, out)
        [d] = run_dirs(child)
        pub_main = c.load(os.path.join(d, "state.json")).get("worktree", {}).get("main")
        raw_main = c.load(os.path.join(d, c.LOCAL, "state.json")).get("worktree", {}).get("main")
        self.assertTrue(pub_main, "public state.json has no worktree.main")
        self.assertNotIn(pub_main, (main, os.path.realpath(main)))
        self.assertIn(raw_main, (main, os.path.realpath(main)))
        before, status = public_files(d), load_state_in_child(d)["status"]
        holder = subprocess.Popen([sys.executable, "-c", "import sys\nimport chongdae as c\nl = c.CommandLock(sys.argv[1])\n"
                                   "l.__enter__()\nprint('held' if l.acquired else 'free', flush=True)\nsys.stdin.read()\n", main],
                                  cwd=HERE, env=engine_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            code, out = cli("close", "--target", child, cwd=scratch, timeout=120)
        finally:
            holder.stdin.close()
            holder.wait()
            holder.stdout.close()
        self.assertEqual(code, c.WAITING, out)
        self.assertTrue(out.lstrip().startswith("still working:"), out)
        self.assertEqual(public_files(d), before)
        after = load_state_in_child(d)
        self.assertEqual(after["status"], status)
        self.assertNotIn("landed", after)
        for top in (child, main, scratch, HERE):
            self.assertEqual(projected_literal_dirs(top) if top != HERE else
                             [p for p in os.listdir(HERE) if p == "~" or p.startswith("<")], [], top)

    # ---------------------------------------------------------------- R4b

    def test_R4b_raw_values_through_the_cli_and_a_reload(self):
        root, git = git_repo("teujip-r4b-")
        self.addCleanup(shutil.rmtree, root, True)
        tmp_path = os.path.join(tempfile.gettempdir(), "teujip-r4b-scratch", "x.txt")
        with open(os.path.join(root, "check.py"), "w", encoding="utf-8") as fh:
            fh.write("raise SystemExit(0)\n")
        git("add", "-A")
        git("commit", "-qm", "check")
        check = c.shlex.join([sys.executable, os.path.join(root, "check.py")])
        brief = "keep %s/data.txt as it is" % root
        answer = {"status": "done", "summary": "built in %s, notes in %s/notes, scratch %s" % (root, HOME, tmp_path),
                  "verified": [{"check": check, "exit": 0}], "decisions": [],
                  "non-claims": ["did not read %s/.cache" % HOME, "src/a.py:3 is quoted as it is"]}
        finding = {"kind": "plan-vs-code", "where": "brief", "record_quote": brief, "tree_quote": "a.py",
                   "why": "data.txt is not kept"}
        review = {"artifact-type": "dwitbuk/review@1", "verdict": "reject", "findings": [finding]}
        answers = os.path.join(root, "answers")
        os.makedirs(answers)
        impl, verdict = os.path.join(answers, "impl.json"), os.path.join(answers, "review.json")
        with open(impl, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(answer, separators=(",", ":")))   # not the engine's own formatting
        with open(verdict, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(review, separators=(",", ":")))
        provider = os.path.join(root, "provider.py")
        with open(provider, "w", encoding="utf-8") as fh:
            fh.write("import json, os, shutil, sys\nanswer, write, request, response = sys.argv[1:5]\n"
                     "if write != '-':\n    open(os.path.join(json.load(open(request))['target'], write), 'w').write('x = 1\\n')\n"
                     "shutil.copyfile(answer, response)\n")
        write_json(os.path.join(root, "hunsu.lock.json"), {"roles": {
            "implementer": [sys.executable, provider, impl, "a.py", "{request}", "{response}"],
            "verifier": [sys.executable, provider, verdict, "-", "{request}", "{response}"]}})
        git("add", "-A")
        git("commit", "-qm", "providers")
        code, out = cli("init", "--session", "--goal", "g", "--target", root)
        self.assertEqual(code, 0, out)
        code, out = cli("add", "build", "--role", "implementer", "--check", check, "--brief", brief, "--target", root)
        self.assertEqual(code, 0, out)
        code, out = cli("run", "--target", root)
        self.assertIn("verifier rejected", out)
        [d] = run_dirs(root)
        shas = [sha(p) for p in glob_responses(d)]
        self.assertIn(sha(impl), shas, "no local/*.response.json keeps the implementer's exact bytes")
        public = read(os.path.join(d, "tasks", "build.json"))
        for p in (root, os.path.realpath(root), HOME, tmp_path, os.path.dirname(tmp_path)):
            self.assertNotIn(p, public, "tasks/build.json holds %r" % p)
        for argv in (("status", "--target", root), ("show", "--target", root)):
            code, out = cli(*argv)
            self.assertEqual(code, 0, out)
        ts = load_state_in_child(d)["tasks"]["build"]
        held = list(strings(ts))
        for s in (answer["summary"], answer["non-claims"][0], answer["non-claims"][1], check, brief):
            self.assertIn(s, held, "the reloaded task lacks the raw %r" % s)
        self.assertEqual(ts.get("added-in"), SESSION)
        self.assertNotIn("overruled", list(keys_of(ts)), ts.get("overruled"))
        self.assertNotIn("overruled", out)

    # ---------------------------------------------------------------- R6

    def test_R6_checks_are_projected_publicly_and_exact_locally(self):
        root, d = self.project()
        link = os.path.join(tempfile.mkdtemp(prefix="teujip-r6-py-"), "python3")
        argv = [link, os.path.join(root, "check.py"), "--home", HOME + "/x"]
        task = {"status": "done", "def": {"id": "a", "checks": [list(argv)]}, "checks": [list(argv)]}
        given = {"status": "running", "non-claims": [], "tasks": {"a": copy.deepcopy(task)}}
        save_as(d, copy.deepcopy(given))
        text = read(os.path.join(d, "tasks", "a.json"))
        self.assertNoMachinePath(text, root, "tasks/a.json")
        self.assertNotIn(os.path.dirname(link), text)
        overlay = list(strings(c.load(os.path.join(d, c.LOCAL, "tasks", "a.json"))))
        for s in argv:
            if s != "--home":
                self.assertIn(s, overlay)
        loaded = c.load_state(d)["tasks"]["a"]
        self.assertEqual(loaded["def"]["checks"], [argv])
        self.assertEqual(loaded["checks"], [argv])

    def test_R6_landed_worktree_run_keeps_its_raw_argv_in_main(self):
        main, git = git_repo("teujip-r6-main-")
        self.addCleanup(shutil.rmtree, main, True)
        # a completed run already in main, with its own overlay of raw strings
        code, out = cli("init", "--session", "--goal", "earlier work in %s/x" % main, "--target", main)
        self.assertEqual(code, 0, out)
        code, out = cli("add", "T0", "--brief", "read %s/notes" % main, "--check", sys.executable + " -c 'raise SystemExit(0)'",
                        "--target", main)
        self.assertEqual(code, 0, out)
        code, out = cli("run", "--target", main)
        self.assertEqual(code, 0, out)
        code, out = cli("close", "--target", main)
        self.assertEqual(code, 0, out)
        [pre] = run_dirs(main)
        pre_overlay = all_files(os.path.join(pre, c.LOCAL))
        self.assertTrue(pre_overlay, "the earlier run has no overlay")
        git("add", "-A")
        git("commit", "-qm", "the earlier run", "--allow-empty")
        # the worktree run whose check's interpreter is a link under a temporary directory
        code, out = cli("init", "--session", "--goal", "g", "--worktree", "--target", main)
        self.assertEqual(code, 0, out)
        wt_root = os.path.join(main, c.RUNS, "wt")
        child = os.path.join(wt_root, os.listdir(wt_root)[0])
        pydir = tempfile.mkdtemp(prefix="teujip-r6-py-")
        self.addCleanup(shutil.rmtree, pydir, True)
        link = os.path.join(pydir, "python3")
        os.symlink(sys.executable, link)
        argv = [link, "-c", "import sys; raise SystemExit(0 if sys.argv[1:] else 3)", child]
        with open(os.path.join(child, "code.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 2\n")
        code, out = cli("add", "T1", "--check", c.shlex.join(argv), "--target", child)
        self.assertEqual(code, 0, out)
        code, out = cli("run", "--target", child)
        self.assertEqual(code, 0, out)
        [child_d] = [x for x in run_dirs(child) if os.path.basename(x) != os.path.basename(pre)]   # main's runs come along in the branch
        name = os.path.basename(child_d)
        code, out = cli("close", "--target", child)
        self.assertEqual(code, 0, out)
        landing = os.path.join(main, c.RUNS, name)
        self.assertTrue(os.path.isdir(landing), out)
        # no public JSON of either run holds an actual machine path, keys included
        leaks = {pydir, os.path.realpath(pydir), link, main, os.path.realpath(main), child, os.path.realpath(child), HOME,
                 tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir()), "/var/folders", "/private/var"}
        for d in (pre, landing):
            for rel in public_files(d):
                if rel.endswith(".json"):
                    text = read(os.path.join(d, rel))
                    for p in leaks:
                        self.assertNotIn(p, text, "%s/%s holds %r" % (os.path.basename(d), rel, p))
        # the landing run's minimal raw overlay in main
        local = os.path.join(landing, c.LOCAL)
        self.assertTrue(os.path.isdir(local), "the landing run has no overlay in main")
        names = list(all_files(local))
        for n in names:
            low = n.lower()
            for bad in ("request", "response", "pending", "transcript", "journal", "launch", ".log"):
                self.assertNotIn(bad, low, "the landing overlay copied %s" % n)
        task_overlay = c.load(os.path.join(local, "tasks", "T1.json"))
        self.assertIn(link, list(strings(task_overlay)))
        for n in names:
            if n.endswith(".json") and n != "state-transaction.json":
                held = set(keys_of(c.load(os.path.join(local, n))))
                self.assertEqual([k for k in held if k in c.PRIVATE_KEYS or k.startswith("lease-")], [], n)
        # a new process in main: recheck runs the original argv, the merged view holds the raw strings
        code, out = cli("recheck", "--target", main)
        self.assertEqual(code, 0, out)
        merged = load_state_in_child(landing)
        self.assertIn("landed", merged)
        self.assertIn(link, list(strings(merged["tasks"]["T1"])))
        self.assertIn(child, list(strings(merged["tasks"]["T1"])))
        self.assertEqual(all_files(os.path.join(pre, c.LOCAL)), pre_overlay)


    # ---------------------------------------------------------------- R3a

    def test_R3a_refused_save_recovers_the_prior_generation_and_publishes_none_of_its_own(self):
        refusal = machine_path_key()
        root, d = self.project()
        first = {"status": "running", "goal": "g in " + root, "non-claims": [],
                 "tasks": {"a": {"status": "todo", "summary": "first in %s/x" % root, "review-source": {"a.py": "todo"}}}}
        c.save_state(d, copy.deepcopy(first))
        # a prior generation left prepared (as test_state_recovery builds one): the process dies between public and local writes
        script = """
import os, sys
import chongdae as c
d, root = sys.argv[1:3]
state = c.load_state(d)
state['tasks']['a'].update(status='done', summary='prior in %s/y' % root, **{'review-source': {'a.py': 'done'}})
save = c.save_changed
def crash(path, data):
    if path == os.path.join(d, 'local', 'tasks', 'a.json'):
        os._exit(77)
    save(path, data)
c.save_changed = crash
c.save_state(d, state)
"""
        proc = subprocess.run([sys.executable, "-c", script, d, root], cwd=HERE, env=engine_env())
        self.assertEqual(proc.returncode, 77)
        journal = os.path.join(d, c.LOCAL, "state-transaction.json")
        self.assertEqual(c.load(journal)["phase"], "prepared")
        prior = c.load_state(d)
        self.assertEqual(prior["tasks"]["a"]["summary"], "prior in %s/y" % root)
        state = copy.deepcopy(prior)
        state["tasks"]["a"]["summary"] = "refused-generation in %s/z" % root
        state["tasks"]["a"]["notes"] = {root + "/k": "v"}
        state["tasks"]["z"] = {"status": "todo", "brief": "refused-generation task"}
        state["goal"] = "refused-generation goal"
        with mock.patch.object(c, "CommandLock", side_effect=AssertionError("save_state took a new lock")):
            with self.assertRaises(refusal):
                c.save_state(d, state)
        # the prior generation was recovered and is what load_state returns
        self.assertEqual(c.load(journal).get("phase"), "committed")
        self.assertEqual(c.load_state(d), prior)
        self.assertEqual(c.load(os.path.join(d, c.LOCAL, "tasks", "a.json"))["review-source"], {"a.py": "done"})
        self.assertEqual(c.load(os.path.join(d, "tasks", "a.json"))["status"], "done")
        # nothing of the refused generation exists on disk: no public file, overlay or prepared journal
        for p in ("tasks/z.json", "local/tasks/z.json"):
            self.assertFalse(os.path.exists(os.path.join(d, p)), p)
        for rel in all_files(d):
            with open(os.path.join(d, rel), "rb") as fh:
                self.assertNotIn(b"refused-generation", fh.read(), rel)

    def r3a_launch(self, root, d):
        """A task whose completed launch is retained, its acknowledgement queued (as test_completion_recovery's runs leave it)."""
        c.save_state(d, {"status": "running", "non-claims": [],
                         "tasks": {"a": {"status": "doing", "added-in": "session-1", "summary": "in %s/x" % root}}})
        name = "a.verify.pending.json"
        path = c.work_path(d, name)
        token = "teujip-r3a-token"
        write_json(path, {"launch": {"token": token}, "argv": [sys.executable, "-c", "pass"]})
        payload = {"artifact-type": "dwitbuk/review@1", "verdict": "accept", "findings": []}
        c.retain_completion(d, "a", path, c.load(path), "verify", payload)
        self.assertEqual(c.completed_payload(c.load(path), "verify"), payload)
        return name, path, token, payload

    def assertNoDurableAck(self, d, path, name, token):
        acks = c.load_state(d)["tasks"]["a"].get("completion-acks") or {}
        self.assertNotIn(name, acks)
        for rel in all_files(d):
            if os.path.join(d, rel) != path:
                with open(os.path.join(d, rel), "rb") as fh:
                    self.assertNotIn(token.encode(), fh.read(), "%s holds the acknowledgement of a refused save" % rel)

    def test_R3a_refused_save_keeps_the_completed_launch_and_acknowledges_nothing(self):
        refusal = machine_path_key()
        root, d = self.project()
        name, path, token, payload = self.r3a_launch(root, d)
        state = c.load_state(d)
        state["tasks"]["a"]["status"] = "done"
        state["tasks"]["a"]["notes"] = {root + "/k": "v"}
        with self.assertRaises(refusal):
            c.save_state(d, state)
        self.assertTrue(os.path.exists(path), "the refused save removed the completed launch record")
        self.assertEqual(c.load(path)["completed"]["payload"], payload)
        self.assertEqual(c.completed_payload(c.load(path), "verify"), payload)   # can still be consumed
        self.assertNoDurableAck(d, path, name, token)
        self.assertEqual(c.load_state(d)["tasks"]["a"]["status"], "doing")

    def test_R3a_later_save_records_the_ack_then_removes_the_launch_record_once(self):
        refusal = machine_path_key()
        root, d = self.project()
        name, path, token, payload = self.r3a_launch(root, d)
        state = c.load_state(d)
        state["tasks"]["a"]["status"] = "done"
        state["tasks"]["a"]["notes"] = {root + "/k": "v"}
        with self.assertRaises(refusal):
            c.save_state(d, copy.deepcopy(state))
        self.assertNoDurableAck(d, path, name, token)
        # the same outcome, consumed again by a save of that task without the offending key
        del state["tasks"]["a"]["notes"]
        seen = []
        real_remove, real_unlink = os.remove, os.unlink

        def watch(real):
            def remove(p, *a, **kw):
                if os.path.abspath(p) == os.path.abspath(path):
                    txn = c.load(os.path.join(d, c.LOCAL, "state-transaction.json"))
                    overlay = c.load(os.path.join(d, c.LOCAL, "tasks", "a.json"))
                    seen.append((txn.get("phase"), (overlay.get("completion-acks") or {}).get(name)))
                return real(p, *a, **kw)
            return remove

        with mock.patch("os.remove", side_effect=watch(real_remove)), mock.patch("os.unlink", side_effect=watch(real_unlink)):
            c.save_state(d, state)
        self.assertFalse(os.path.exists(path), "the acknowledged launch record was not removed")
        self.assertEqual(len(seen), 1, seen)
        self.assertEqual(seen[0], ("committed", token), "the launch record was removed before its ack was durable")
        self.assertEqual(c.load_state(d)["tasks"]["a"]["status"], "done")
        self.assertEqual(c.load_state(d)["tasks"]["a"]["completion-acks"].get(name), token)
        self.assertFalse(os.path.exists(path))   # consumed once: nothing is left to apply a second time
        c.save_state(d, c.load_state(d))
        self.assertFalse(os.path.exists(path))

    def test_R3a_refused_save_in_a_run_does_not_relaunch_the_completed_worker(self):
        refusal = machine_path_key()
        root, git = git_repo("teujip-r3a-run-")
        self.addCleanup(shutil.rmtree, root, True)
        write_json(os.path.join(root, "hunsu.json"), {"settings": {"chongdae": {"commit-records": False}}})
        outside = tempfile.mkdtemp(prefix="teujip-r3a-calls-")
        self.addCleanup(shutil.rmtree, outside, True)
        calls = os.path.join(outside, "calls.txt")   # outside the project: the check changes no source
        worker = os.path.join(root, "worker.py")
        with open(worker, "w", encoding="utf-8") as fh:
            fh.write("import sys\nopen(sys.argv[1], 'a').write('called\\n')\n")
        git("add", "-A")
        git("commit", "-qm", "worker")
        self.assertEqual(cli("init", "--session", "--goal", "g", "--target", root)[0], 0)
        code, out = cli("add", "a", "--role", "session", "--check", c.shlex.join([sys.executable, worker, calls]), "--target", root)
        self.assertEqual(code, 0, out)
        # every save of this process that carries a queued acknowledgement also carries a machine-path key: refused
        injector = ("import os, sys\nsys.path.insert(0, sys.argv[1])\nimport chongdae as c\n"
                    "original = c.save_state\n"
                    "def save_state(d, state, *a, **kw):\n"
                    "    if c._COMPLETION_ACK_QUEUE.get(os.path.realpath(d)) and 'a' in state.get('tasks', {}):\n"
                    "        state['tasks']['a']['notes'] = {sys.argv[2] + '/k': 'v'}\n"
                    "    return original(d, state, *a, **kw)\n"
                    "c.save_state = save_state\n"
                    "sys.exit(c.main(['run', 'a', '--target', sys.argv[2]]))\n")
        proc = subprocess.run([sys.executable, "-c", injector, HERE, root], cwd=HERE, env=engine_env(),
                              capture_output=True, text=True, timeout=120)
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("./k", proc.stdout + proc.stderr)   # the refusal names the key in its projected form
        self.assertNotIn(refusal.__name__ + "(", proc.stderr)
        with open(calls, encoding="utf-8") as fh:
            self.assertEqual(fh.read().splitlines(), ["called"])
        [d] = run_dirs(root)
        [pending] = [os.path.join(d, c.LOCAL, n) for n in os.listdir(os.path.join(d, c.LOCAL)) if n.startswith("a.") and n.endswith(".pending.json")]
        record = c.load(pending)
        self.assertTrue(record.get("completed", {}).get("token"), record)
        self.assertNotIn(os.path.basename(pending), load_state_in_child(d)["tasks"]["a"].get("completion-acks") or {})
        code, out = cli("run", "a", "--target", root)
        self.assertEqual(code, 0, out)
        with open(calls, encoding="utf-8") as fh:
            self.assertEqual(fh.read().splitlines(), ["called"], "the completed worker was launched again")
        self.assertEqual(load_state_in_child(d)["tasks"]["a"]["status"], "done")
        self.assertFalse(os.path.exists(pending))

    # ---------------------------------------------------------------- R7

    def assertPublicPlanProjected(self, d, leaks):
        with open(os.path.join(d, "plan.json"), "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8")
        for p in leaks:
            self.assertNotIn(p, text, "public plan.json holds %r" % p)
            self.assertNotIn(json.dumps(p)[1:-1], text, "public plan.json holds %r (escaped)" % p)
        return json.loads(text)

    def r7_leaks(self, root, *more):
        tmp = tempfile.gettempdir()
        out = {root, os.path.realpath(root), HOME, tmp, os.path.realpath(tmp), "/var/folders", "/private/var", "/private/tmp"}
        for m in more:
            out |= {m, os.path.realpath(m)}
        return out

    def test_R7_session_goal_is_projected_publicly_and_raw_locally(self):
        root, git = git_repo("teujip-r7-session-")
        self.addCleanup(shutil.rmtree, root, True)
        scratch = os.path.join(tempfile.gettempdir(), "teujip-r7-scratch", "s.txt")
        goal = "fix %s/code.py, notes in %s/notes, scratch %s" % (root, HOME, scratch)
        code, out = cli("init", "--session", "--goal", goal, "--target", root)
        self.assertEqual(code, 0, out)
        [d] = run_dirs(root)
        public = self.assertPublicPlanProjected(d, self.r7_leaks(root))
        self.assertIn("./code.py", public.get("goal", ""))
        self.assertIn("~/notes", public.get("goal", ""))
        local = os.path.join(d, c.LOCAL, "plan.json")
        self.assertTrue(os.path.exists(local), "no local/plan.json")
        self.assertIn(goal, list(strings(c.load(local))))
        self.assertEqual(load_plan_in_child(d)["goal"], goal)
        for argv in (("status", "--target", root), ("show", "--target", root)):
            code, out = cli(*argv)
            self.assertEqual(code, 0, out)
        self.assertEqual(load_plan_in_child(d)["goal"], goal)

    def test_R7_plan_file_is_kept_and_its_check_runs_its_original_argv(self):
        root, git = git_repo("teujip-r7-plan-")
        self.addCleanup(shutil.rmtree, root, True)
        write_json(os.path.join(root, "hunsu.json"), {"settings": {"chongdae": {"commit-records": False}}})
        git("add", "-A")
        git("commit", "-qm", "settings")
        pydir = tempfile.mkdtemp(prefix="teujip-r7-py-")
        self.addCleanup(shutil.rmtree, pydir, True)
        link = os.path.join(pydir, "python3")
        os.symlink(sys.executable, link)
        marker = os.path.join(pydir, "argv.json")
        code_arg = ("import json, sys; open(sys.argv[2], 'w').write(json.dumps(sys.argv[1:])); "
                    "raise SystemExit(0 if sys.argv[1] == %r else 3)" % root)
        argv = [link, "-c", code_arg, root, marker]
        plan = {"artifact-type": "chongdae/plan@1", "goal": "keep %s/code.py" % root, "providers": {"implementer": "session"},
                "tasks": [{"id": "S1", "role": "implementer", "checks": [argv]}]}
        holder = tempfile.mkdtemp(prefix="teujip-r7-planfile-")
        self.addCleanup(shutil.rmtree, holder, True)
        plan_file = os.path.join(holder, "plan.json")
        write_json(plan_file, plan)
        before = sha(plan_file)
        code, out = cli("init", "--plan", plan_file, "--target", root)
        self.assertEqual(code, 0, out)
        self.assertEqual(sha(plan_file), before, "the input plan file was written")
        [d] = run_dirs(root)
        self.assertPublicPlanProjected(d, self.r7_leaks(root, pydir, link, holder))
        local = os.path.join(d, c.LOCAL, "plan.json")
        self.assertTrue(os.path.exists(local), "no local/plan.json")
        held = list(strings(c.load(local)))
        for s in (link, code_arg, root, marker):
            self.assertIn(s, held)
        loaded = load_plan_in_child(d)
        self.assertEqual([t.get("checks") for t in loaded["tasks"]], [[argv]])
        self.assertEqual(loaded["goal"], plan["goal"])
        outs = []
        for _ in range(3):
            code, out = cli("run", "--target", root)
            outs.append(out)
            if os.path.exists(marker):
                break
        self.assertTrue(os.path.exists(marker), "the plan run's check never ran: %s" % "\n".join(outs))
        with open(marker, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), [root, marker])
        self.assertEqual(sha(plan_file), before)
        self.assertFalse(projected_literal_dirs(root), projected_literal_dirs(root))

    def test_R7_landed_worktree_run_keeps_its_raw_goal_in_main(self):
        main, git = git_repo("teujip-r7-main-")
        self.addCleanup(shutil.rmtree, main, True)
        code, out = cli("init", "--session", "--goal", "earlier work in %s/x" % main, "--target", main)
        self.assertEqual(code, 0, out)
        code, out = cli("add", "T0", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", main)
        self.assertEqual(code, 0, out)
        self.assertEqual(cli("run", "--target", main)[0], 0)
        self.assertEqual(cli("close", "--target", main)[0], 0)
        [pre] = run_dirs(main)
        pre_overlay = all_files(os.path.join(pre, c.LOCAL))
        self.assertTrue(pre_overlay, "the earlier run has no overlay")
        git("add", "-A")
        git("commit", "-qm", "the earlier run", "--allow-empty")
        goal = "land %s/code.py and %s/notes" % (main, HOME)
        code, out = cli("init", "--session", "--goal", goal, "--worktree", "--target", main)
        self.assertEqual(code, 0, out)
        wt_root = os.path.join(main, c.RUNS, "wt")
        child = os.path.join(wt_root, os.listdir(wt_root)[0])
        with open(os.path.join(child, "code.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 2\n")
        code, out = cli("add", "T1", "--check", sys.executable + " -c 'raise SystemExit(0)'", "--target", child)
        self.assertEqual(code, 0, out)
        self.assertEqual(cli("run", "--target", child)[0], 0)
        [child_d] = [x for x in run_dirs(child) if os.path.basename(x) != os.path.basename(pre)]
        code, out = cli("close", "--target", child)
        self.assertEqual(code, 0, out)
        landing = os.path.join(main, c.RUNS, os.path.basename(child_d))
        self.assertTrue(os.path.isdir(landing), out)
        public = self.assertPublicPlanProjected(landing, self.r7_leaks(main, child))
        self.assertIn("./code.py", public.get("goal", ""))
        local = os.path.join(landing, c.LOCAL, "plan.json")
        self.assertTrue(os.path.exists(local), "main has no local/plan.json for the landed run")
        self.assertIn(goal, list(strings(c.load(local))))
        self.assertEqual(load_plan_in_child(landing)["goal"], goal)
        self.assertEqual(all_files(os.path.join(pre, c.LOCAL)), pre_overlay)



# ==================================================================== contract M (a follow-up to R)

def child_env(home):
    """A normal (parent) session's env with `home` as its home directory: no AGENT_WORKER inherited from a worker."""
    env = dict(os.environ, HOME=home, CHONGDAE_SESSION=SESSION)
    env.pop("AGENT_WORKER", None)
    return env


def neutral_as(texts, target, home):
    """[c.neutral_path(t, target) for t in texts] in a child process whose home directory is `home`."""
    script = ("import json, sys\nimport chongdae as c\n"
              "print(json.dumps([c.neutral_path(t, sys.argv[2] or None) for t in json.loads(sys.argv[1])]))\n")
    proc = subprocess.run([sys.executable, "-c", script, json.dumps(texts), target or ""], cwd=HERE,
                          env=child_env(home), capture_output=True, text=True)
    if proc.returncode:
        raise AssertionError("neutral_path failed: %s" % proc.stderr)
    return json.loads(proc.stdout)


class ProjectionM(unittest.TestCase):
    project = Projection.project

    # every M1 example, with its complete expected output (home /home/person, project root /work/project)
    M1 = {
        "- **/tmp/cd-py311/bin/python3 (outside HOME):** fails.": "- **<tmp> (outside HOME):** fails.",
        "**/tmp/x**": "**<tmp>**",
        "see **/tmp/x** now": "see **<tmp>** now",
        "**/home/person/notes**": "**~/notes**",
        "**/home/person**": "**~**",
        "**/work/project/src/a.py**": "**./src/a.py**",
        "**/work/project**": "**.**",
    }

    def assertProjects(self, cases, target=R_ROOT):
        raw = list(cases)
        public, raws = project_as({"s": raw}, target, R_HOME)
        self.assertEqual(dict(zip(raw, public["s"])), cases)
        self.assertEqual(c.merge_private(copy.deepcopy(public), copy.deepcopy(raws)), {"s": raw})
        return public, raws

    # ---------------------------------------------------------------- M1

    def test_M1_observed_worker_summary_is_projected(self):
        raw = "- **/tmp/cd-py311/bin/python3 (outside HOME):** fails."
        public, _ = project_as({"summary": raw}, R_ROOT, R_HOME)
        self.assertEqual(public["summary"], "- **<tmp> (outside HOME):** fails.")

    def test_M1_every_example_projects_to_its_exact_string(self):
        raw = list(self.M1)
        public, _ = project_as({"m%d" % i: k for i, k in enumerate(raw)}, R_ROOT, R_HOME)
        for i, k in enumerate(raw):
            self.assertEqual(public["m%d" % i], self.M1[k], "%r" % k)

    def test_M1_temp_wrapper_with_this_hosts_temp_dir(self):
        tmp = tempfile.gettempdir()
        real = os.path.realpath(tmp)
        self.assertProjects({"**%s/y**" % tmp: "**<tmp>**", "see **%s/cd-py/bin/python3** now" % real: "see **<tmp>** now",
                             "**/tmp/x**": "**<tmp>**"})

    def test_M1_wrapper_after_every_r1_left_boundary(self):
        self.assertProjects({
            "a=**/tmp/x**": "a=**<tmp>**", "(**/home/person/x**)": "(**~/x**)", "[**/work/project/a**]": "[**./a**]",
            "a,**/home/person/x**": "a,**~/x**", "a:**/home/person/x**": "a:**~/x**", "a;**/work/project/x**": "a;**./x**",
            "a|**/home/person/x**": "a|**~/x**", "a&**/home/person/x**": "a&**~/x**", "a>**/home/person/log**": "a>**~/log**",
            "'**/home/person/x**'": "'**~/x**'", '"**/work/project/x**"': '"**./x**"', "`**/home/person/x**`": "`**~/x**`",
            "a\t**/home/person/x**": "a\t**~/x**", "**/tmp/x**,**/tmp/y**": "**<tmp>**,**<tmp>**",
        })

    def test_M1_wrapped_prefix_still_needs_r1_right_boundary(self):
        # the wrapper opens a path; it does not make /home/person-old a home path
        self.assertProjects({"**/home/person-old/x** and **/home/person/x**": "**/home/person-old/x** and **~/x**",
                             "**/work/project2/x** and **/work/project/x**": "**/work/project2/x** and **./x**"})

    # ---------------------------------------------------------------- M2

    def test_M2_closing_wrapper_is_kept_byte_for_byte(self):
        public, _ = self.assertProjects(dict(self.M1))
        for got in public["s"]:
            self.assertEqual(got.count("**"), 2, got)

    def test_M2_temp_whole_path_stops_before_the_closing_wrapper(self):
        self.assertProjects({"**/tmp/x/y.txt** then": "**<tmp>** then", "**/tmp/x**.": "**<tmp>**.",
                             "**/home/person/a/b**:": "**~/a/b**:", "**/work/project/src**)": "**./src**)"})

    def test_M2_unwrapped_paths_keep_todays_behavior_beside_a_wrapped_one(self):
        # today: /tmp/x** -> <tmp> (whole path), /home/person/x** -> ~/x**, /work/project/x** -> ./x**
        self.assertProjects({"/tmp/x** and **/tmp/y**": "<tmp> and **<tmp>**",
                             "/home/person/x** and **/home/person/y**": "~/x** and **~/y**",
                             "/work/project/x** **/work/project/y**": "./x** **./y**"})

    # ---------------------------------------------------------------- M3

    def test_M3_wrapper_not_at_a_path_start_opens_nothing(self):
        self.assertProjects({"src**/tmp/a **/tmp/b**": "src**/tmp/a **<tmp>**",
                             "a**/tmp/b** **/tmp/c**": "a**/tmp/b** **<tmp>**",
                             "docs**/home/person/x **/home/person/x**": "docs**/home/person/x **~/x**",
                             "docs**/work/project/x **/work/project/x**": "docs**/work/project/x **./x**"})

    def test_M3_the_four_guard_strings_alone_stay_unchanged(self):
        guards = ["src**/tmp/a", "a**/tmp/b**", "docs**/home/person/x", "docs**/work/project/x"]
        public, raws = project_as({"g": guards, "w": "**/tmp/x**"}, R_ROOT, R_HOME)
        self.assertEqual(public["g"], guards)
        self.assertEqual(public["w"], "**<tmp>**")

    def test_M3_single_star_and_other_markup_keep_todays_behavior(self):
        # today's outputs of these strings, each beside a ** wrapper that M1 projects
        self.assertProjects({"*/tmp/x* and **/tmp/y**": "*/tmp/x* and **<tmp>**",
                             "see */tmp/x* now **/tmp/y**": "see */tmp/x* now **<tmp>**",
                             "__/tmp/x__ and **/tmp/y**": "__/tmp/x__ and **<tmp>**",
                             "_/tmp/x_ and **/tmp/y**": "_/tmp/x_ and **<tmp>**",
                             "<b>/tmp/x</b> and **/tmp/y**": "<b><tmp> and **<tmp>**",
                             "\x1b[1m/tmp/x\x1b[0m and **/tmp/y**": "\x1b[1m/tmp/x\x1b[0m and **<tmp>**",
                             "`/tmp/x`** and **/tmp/y**": "`<tmp>`** and **<tmp>**"})

    def test_M3_unwrapped_path_ending_in_stars_keeps_todays_behavior(self):
        self.assertProjects({"/tmp/x**": "<tmp>", "/tmp/x** then **/tmp/y**": "<tmp> then **<tmp>**",
                             "/home/person/x**": "~/x**", "**/home/person/x**": "**~/x**"})

    # ---------------------------------------------------------------- M4

    def test_M4_merge_private_returns_each_original_exactly(self):
        raw = list(self.M1)
        public, raws = project_as({"s": raw, "one": raw[0], "nested": [{"why": raw[2]}]}, R_ROOT, R_HOME)
        self.assertEqual(public["s"], [self.M1[k] for k in raw])
        merged = c.merge_private(copy.deepcopy(public), copy.deepcopy(raws))
        self.assertEqual(merged, {"s": raw, "one": raw[0], "nested": [{"why": raw[2]}]})

    def m4_state(self, root):
        tmp = tempfile.gettempdir()
        summary = "- **/tmp/cd-py311/bin/python3 (outside HOME):** fails; **%s/src/a.py** built" % root
        finding = "see **%s/notes** and **%s/scratch-m4/out.txt** now" % (R_HOME, tmp)
        nonclaim = "**%s** was not read; **%s**" % (R_HOME + "/.cache", os.path.realpath(tmp) + "/scratch-m4")
        task = {"status": "done", "summary": summary,
                "stages": {"verifier": {"response": {"findings": [{"kind": "bug", "where": "src/a.py", "why": finding}]},
                                        "by": {"host": "codex"}, "when": "after"}},
                "response": {"summary": summary, "non-claims": [nonclaim]}}
        return {"status": "running", "non-claims": [], "tasks": {"a": task}}, [summary, finding, nonclaim]

    def m4_leaks(self, root):
        tmp = tempfile.gettempdir()
        return {R_HOME, root, os.path.realpath(root), tmp, os.path.realpath(tmp), "/tmp/", "/private/tmp", "/var/folders"}

    def test_M4_save_state_public_file_holds_no_wrapped_machine_path(self):
        root, d = self.project()
        state, raw = self.m4_state(root)
        save_as(d, copy.deepcopy(state), home=R_HOME)
        with open(os.path.join(d, "tasks", "a.json"), "rb") as fh:
            data = fh.read().decode("utf-8")
        for p in self.m4_leaks(root):
            self.assertNotIn(p, data, "tasks/a.json still holds %r" % p)
        pub = c.load(os.path.join(d, "tasks", "a.json"))
        self.assertEqual(pub["summary"], "- **<tmp> (outside HOME):** fails; **./src/a.py** built")
        self.assertEqual(pub["stages"]["verifier"]["response"]["findings"][0]["why"], "see **~/notes** and **<tmp>** now")
        self.assertEqual(pub["response"]["non-claims"], ["**~/.cache** was not read; **<tmp>**"])

    def test_M4_local_overlay_and_reload_hold_the_exact_raws(self):
        root, d = self.project()
        state, raw = self.m4_state(root)
        save_as(d, copy.deepcopy(state), home=R_HOME)
        held = []
        for dirpath, _, files in os.walk(os.path.join(d, c.LOCAL)):
            for f in files:
                if f.endswith(".json"):
                    held += list(strings(c.load(os.path.join(dirpath, f))))
        with open(os.path.join(d, "tasks", "a.json"), "rb") as fh:
            public = fh.read().decode("utf-8")
        for s in raw:
            self.assertIn(s, held, "the local overlay lacks %r" % s)
            self.assertNotIn(json.dumps(s)[1:-1], public)
        script = "import json, sys\nimport chongdae as c\nprint(json.dumps(c.load_state(sys.argv[1])))\n"
        proc = subprocess.run([sys.executable, "-c", script, d], cwd=HERE, env=child_env(R_HOME),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(unstamped(json.loads(proc.stdout)), state)
        self.assertEqual(unstamped(c.load_state(d)), state)

    # ---------------------------------------------------------------- M5

    def test_M5_neutral_path_keeps_todays_output_on_wrapped_temp_paths(self):
        tmp = tempfile.gettempdir()
        texts = ["**/tmp/x**", "**%s/y**" % tmp, "see **/tmp/x** now"]
        # neutral_path (narrow=False) today: the whole path under a temp dir goes, the closing ** with it
        self.assertEqual(neutral_as(texts, None, R_HOME), ["**<tmp>", "**<tmp>", "see **<tmp> now"])
        self.assertEqual(neutral_as(texts, R_ROOT, R_HOME), ["**<tmp>", "**<tmp>", "see **<tmp> now"])
        self.assertEqual(c.neutral_path("**/tmp/x**", None), "**<tmp>")
        # ... while the narrow public projection of the very same strings keeps the closing markup
        public, _ = project_as({"s": texts}, R_ROOT, R_HOME)
        self.assertEqual(public["s"], ["**<tmp>**", "**<tmp>**", "see **<tmp>** now"])


def glob_responses(d):
    local = os.path.join(d, c.LOCAL)
    return [os.path.join(local, n) for n in os.listdir(local) if n.endswith(".response.json")]


if __name__ == "__main__":
    unittest.main()
