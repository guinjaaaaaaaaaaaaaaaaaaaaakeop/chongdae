"""Packaging suite for contract K: chongdae's installable plugin is the standalone payload in `plugin/`.

  python3 test_payload.py        (from the repository root; also run by test_chongdae.py)

Everything this suite creates lives in fresh temporary directories outside the repository and is removed afterwards.
The main proof (K3) copies only `plugin/` somewhere no git repository contains and drives the CLI and the hooks there.
Offline and deterministic: local git only, no network, no model call. A test that cannot run here fails; none skips.
Only lasting properties of the layout are tested here: what the move itself left unchanged (the moved files' bytes, the
manifest fields beyond the version, the development pins) is a fact about one commit, checked when it was built.
"""
import fnmatch
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.abspath(__file__))
REPO_REAL = os.path.realpath(REPO)
PLUGIN = os.path.join(REPO, "plugin")
HOME_DIR = os.path.expanduser("~")

COMMANDS = sorted("accept add adopt amend claim close confirm delegate did dispute drop init recheck report retry run show status take unstage".split())
HOOK_FILES = ("hooks.json", "codex.json", "pre_bash.py", "pre_write.py", "session_start.py")
MANIFESTS = ("plugin.json", os.path.join(".claude-plugin", "plugin.json"), os.path.join(".codex-plugin", "plugin.json"))
K1_FILES = (["chongdae.py", "pluginroot.py", "README.md", "LICENSE", os.path.join("skills", "run", "SKILL.md")] + list(MANIFESTS)
            + [os.path.join("hooks", h) for h in HOOK_FILES] + [os.path.join("commands", c + ".md") for c in COMMANDS])
DEV_NAMES = ("test_*.py", "*_test.py", "tests", "AGENTS.md", "CLAUDE.md", "SELFHOSTING.md", "hunsu.json", "hunsu.lock.json",
             "hunsu.local.json", "hunsu-judgments.json", "hunsu-conflicts.md", ".chongdae", "reviews", ".dwitbuk", ".jokbo",
             ".mangsang", ".hunsu-bootstrap", ".claude", ".codex", ".hypothesis", ".git", "marketplace.json")
# the hooks are silent under AGENT_WORKER=1 by design; a hired worker's process carries it, so the suite's children never do
STRIP = ("AGENT_WORKER", "PYTHONPATH", "CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT", "CODEX_THREAD_ID", "PWD", "OLDPWD")
IDENTITY = {"GIT_AUTHOR_NAME": "payload test", "GIT_AUTHOR_EMAIL": "payload@test.invalid",
            "GIT_COMMITTER_NAME": "payload test", "GIT_COMMITTER_EMAIL": "payload@test.invalid"}
# C9: plugin/pluginroot.py is the plugin family's shared resolver, vendored byte-identical from dwitbuk 2.2.1
PLUGINROOT = os.path.join(PLUGIN, "pluginroot.py")
PLUGINROOT_SHA256 = "6318838886010a99b209728af9368d4a7c816bd7b4266fb69bef3d36e23eb35e"
MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def inside(path, root):
    p, r = os.path.realpath(path), os.path.realpath(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if isinstance(text, str) else json.dumps(text, indent=1))


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def plugin_manifest(directory, name, version=None):
    """A plugin manifest (`.claude-plugin/plugin.json`) in `directory` naming `name`: a directory a catalog selects is a
    plugin the shared resolver can read (its catalog rule takes only manifest-bearing directories)."""
    write(os.path.join(directory, ".claude-plugin", "plugin.json"), dict({"name": name}, **({"version": version} if version else {})))


def walk_payload(root):
    """Every entry under root, links not followed, `__pycache__` directories ignored: (path, is_dir)."""
    for d, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for x in dirs:
            yield os.path.join(d, x), True
        for x in files:
            yield os.path.join(d, x), False


def payload_files(root):
    return [p for p, is_dir in walk_payload(root) if not is_dir]


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def has_key(o, key):
    if isinstance(o, dict):
        return key in o or any(has_key(v, key) for v in o.values())
    if isinstance(o, list):
        return any(has_key(v, key) for v in o)
    return False


def chongdae_entry(catalog):
    found = [p for p in catalog.get("plugins", []) if p.get("name") == "chongdae"]
    assert len(found) == 1, catalog
    return found[0]


AUDIT_WRAPPER = r'''
import json, os, runpy, sys
LOG, REPO, ENGINE = sys.argv[1], sys.argv[2], sys.argv[3]
REPO_ABS = os.path.abspath(REPO)
hits, busy = [], [False]

def under(s):
    if isinstance(s, int) or s is None:
        return False
    try:
        s = os.fsdecode(s)
    except TypeError:
        return False
    if REPO in s or REPO_ABS in s:
        return True
    try:
        r = os.path.realpath(os.path.abspath(s))
    except Exception:
        return False
    return r == REPO or r.startswith(REPO + os.sep)

def flat(x):
    if isinstance(x, (list, tuple)):
        for y in x:
            yield from flat(y)
    else:
        yield x

def audit(event, args):
    if busy[0]:
        return
    busy[0] = True
    try:
        if event == "open":
            if args and under(args[0]):
                hits.append([event, os.fsdecode(args[0])])
        elif event == "subprocess.Popen":
            exe, argv, cwd = args[0], args[1], args[2]
            for s in [exe, cwd] + list(flat(argv)):
                if under(s):
                    hits.append([event, repr(args[:3])])
                    break
        elif event.startswith("os.exec") or event == "os.posix_spawn" or event.startswith("os.spawn"):
            for s in [args[0]] + list(flat(args[1] if len(args) > 1 else [])):
                if under(s):
                    hits.append([event, repr(args[:2])])
                    break
    except Exception as err:
        hits.append(["audit-error", repr(err)])
    finally:
        busy[0] = False

sys.addaudithook(audit)
sys.argv = [ENGINE] + sys.argv[4:]
sys.path[0] = os.path.dirname(ENGINE)   # as `python3 ENGINE ...` would have it
code = 0
try:
    runpy.run_path(ENGINE, run_name="__main__")
except SystemExit as err:
    code = err.code if isinstance(err.code, int) else (0 if err.code is None else 1)
    if not isinstance(err.code, int) and err.code is not None:
        sys.stderr.write(str(err.code) + "\n")
finally:
    busy[0] = True
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and under(f):
            hits.append(["import", name + " " + f])
    with open(LOG, "w", encoding="utf-8") as fh:
        json.dump(hits, fh)
sys.exit(code)
'''


class Payload(unittest.TestCase):
    maxDiff = None

    # ---------- support ----------

    def tmp(self, prefix="chongdae-payload-"):
        d = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, d, True)
        self.assertFalse(inside(d, REPO_REAL), "a temporary directory inside the repository: %s" % d)
        return d

    def env(self, **extra):
        home = self.tmp("chongdae-payload-home-")
        claude = os.path.join(home, ".claude")
        os.makedirs(claude)
        env = {k: v for k, v in os.environ.items() if k not in STRIP}
        env.update(IDENTITY, AGENT_HOST="claude-code", HOME=home, HUNSU_CLAUDE_DIR=claude, CLAUDE_CONFIG_DIR=claude,
                   PYTHONDONTWRITEBYTECODE="1")
        env.update(extra)
        return env

    def sh(self, argv, cwd, env, stdin=None, timeout=300):
        return subprocess.run(argv, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)

    def git(self, cwd, env, *args):
        done = self.sh(["git"] + list(args), cwd, env)
        self.assertEqual(done.returncode, 0, ("git", args, done.stdout, done.stderr))
        return done.stdout.strip()

    def need_payload(self):
        self.assertTrue(os.path.isdir(PLUGIN), "no plugin/ payload directory in the repository")
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "chongdae.py")), "no plugin/chongdae.py")

    def version(self, root=PLUGIN):
        return load(os.path.join(root, ".claude-plugin", "plugin.json"))["version"]

    def copy_payload(self):
        """Only plugin/, into a fresh directory outside the repository that no git repository contains."""
        self.need_payload()
        holder = self.tmp("chongdae-payload-copy-")
        dst = os.path.join(holder, "chongdae")
        shutil.copytree(PLUGIN, dst, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
        probe = self.sh(["git", "rev-parse", "--show-toplevel"], dst, self.env())
        self.assertNotEqual(probe.returncode, 0, "the copy is inside a git repository: %s" % probe.stdout)
        return dst

    def fixture(self, env):
        proj = self.tmp("chongdae-payload-project-")
        self.git(proj, env, "init", "-q")
        write(os.path.join(proj, "README.md"), "a fixture project\n")
        self.git(proj, env, "add", "-A")
        self.git(proj, env, "commit", "-qm", "base")
        return proj, self.git(proj, env, "rev-parse", "HEAD")

    def assert_no_repo(self, text, what):
        for p in {REPO, REPO_REAL}:
            self.assertNotIn(p, text, "%s names the repository" % what)

    def workflow(self, prefix, proj, base, env):
        """init --session, add, a change, run until done, status, show, report, commit as run says, close. Returns outputs."""
        outs = []

        def cli(*args):
            done = self.sh(prefix() + list(args), proj, env)
            outs.append(done.stdout + done.stderr)
            return done

        d = cli("init", "--session", "--goal", "the payload copy works alone")
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        d = cli("add", "T1", "--check", shlex.join([sys.executable, "-c", "pass"]))
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        write(os.path.join(proj, "work.txt"), "the work of T1\n")
        said = ""
        for _ in range(15):
            d = cli("run")
            said += d.stdout
            if d.returncode != 4:
                break
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertIn("done T1", said)
        for args in (("status",), ("show",)):
            d = cli(*args)
            self.assertEqual(d.returncode, 0, (args, d.stdout, d.stderr))
        d = cli("report", "--since", base)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertEqual(json.loads(d.stdout)["artifact-type"], "dwitbuk/findings@1")
        lines = [ln.strip() for ln in said.splitlines() if ln.strip().startswith(("git add ", "git commit "))]
        self.assertTrue(any(ln.startswith("git commit ") for ln in lines), said)
        for ln in lines:
            g = self.sh(shlex.split(ln), proj, env)
            self.assertEqual(g.returncode, 0, (ln, g.stdout, g.stderr))
        d = cli("close")
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        return outs

    def records(self, proj):
        runs = glob.glob(os.path.join(proj, ".chongdae", "run-*", "state.json"))
        self.assertEqual(len(runs), 1, os.listdir(proj))
        texts = {}
        for d, _, files in os.walk(os.path.join(proj, ".chongdae")):
            for f in files:
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    texts[os.path.join(d, f)] = fh.read()
        return load(runs[0]), texts

    def engine_of(self, engine_dir, env, cwd):
        """chongdae.engine() of the engine imported from engine_dir, in a new process (engine() caches)."""
        d = self.sh([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import chongdae; print(chongdae.engine())",
                     engine_dir], cwd, env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        return d.stdout.strip()

    def plugin_root(self, target, name, env, engine_dir=PLUGIN):
        self.need_payload()
        d = self.sh([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import chongdae; "
                     "print(chongdae.plugin_root(sys.argv[2], sys.argv[3]))", engine_dir, target, name], self.tmp(), env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        return os.path.realpath(d.stdout.strip())

    # ---------- K1 layout ----------

    def test_k1_every_payload_file_exists(self):
        self.need_payload()
        missing = [f for f in K1_FILES if not os.path.isfile(os.path.join(PLUGIN, f))]
        self.assertEqual(missing, [])

    def test_k1_the_commands_are_exactly_the_nineteen(self):
        self.need_payload()
        got = sorted(os.listdir(os.path.join(PLUGIN, "commands")))
        self.assertEqual(got, [c + ".md" for c in COMMANDS])

    def test_k1_license_is_byte_identical_to_the_root_license(self):
        self.need_payload()
        with open(os.path.join(REPO, "LICENSE"), "rb") as a, open(os.path.join(PLUGIN, "LICENSE"), "rb") as b:
            root, payload = a.read(), b.read()
        self.assertTrue(root, "the root LICENSE stays")
        self.assertEqual(payload, root)

    def test_k1_manifests_keep_their_relative_paths(self):
        self.need_payload()
        self.assertEqual(load(os.path.join(PLUGIN, "plugin.json"))["extensions"]["com.openai"]["hooks"], "./hooks/codex.json")
        self.assertEqual(load(os.path.join(PLUGIN, ".codex-plugin", "plugin.json"))["skills"], "./skills/")
        for m in MANIFESTS:
            for key, argv in load(os.path.join(PLUGIN, m))["reads"].items():
                self.assertEqual(argv[1], "{plugin:chongdae}/chongdae.py", (m, key))

    def test_k1_the_root_no_longer_holds_the_runtime(self):
        self.need_payload()
        present = [p for p in ("hooks", "commands", "skills", "plugin.json", os.path.join(".claude-plugin", "plugin.json"), ".codex-plugin")
                   if os.path.lexists(os.path.join(REPO, p))]
        self.assertEqual(present, [])

    # ---------- K2 catalogs ----------

    def test_k2_claude_catalog_selects_the_payload(self):
        self.need_payload()
        cat = load(os.path.join(REPO, ".claude-plugin", "marketplace.json"))
        entry = chongdae_entry(cat)
        self.assertEqual(entry["source"], "./plugin")
        root = os.path.join(REPO, entry["source"])
        self.assertEqual(os.path.realpath(root), os.path.realpath(PLUGIN))
        manifest = load(os.path.join(root, ".claude-plugin", "plugin.json"))
        self.assertEqual((manifest["name"], manifest["version"]), ("chongdae", entry["version"]))

    def test_k2_codex_catalog_selects_the_payload_without_a_version(self):
        self.need_payload()
        cat = load(os.path.join(REPO, ".agents", "plugins", "marketplace.json"))
        entry = chongdae_entry(cat)
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugin"})
        root = os.path.join(REPO, entry["source"]["path"])
        self.assertEqual(os.path.realpath(root), os.path.realpath(PLUGIN))
        self.assertTrue(os.path.isfile(os.path.join(root, ".codex-plugin", "plugin.json")))
        self.assertFalse(has_key(cat, "version"), "the Codex catalog gained a version")

    def test_k2_no_catalog_inside_the_payload(self):
        self.need_payload()
        found = [p for p, _ in walk_payload(PLUGIN) if os.path.basename(p) == "marketplace.json"]
        self.assertEqual(found, [])

    # ---------- K3 self-contained ----------

    def test_k3_nothing_in_the_payload_is_a_symlink(self):
        self.need_payload()
        self.assertFalse(os.path.islink(PLUGIN))
        links = []
        for d, dirs, files in os.walk(PLUGIN, followlinks=False):
            links += [os.path.join(d, x) for x in dirs + files if os.path.islink(os.path.join(d, x))]
        self.assertEqual(links, [])

    def test_k3_no_development_state_in_the_payload(self):
        self.need_payload()
        bad = [os.path.relpath(p, PLUGIN) for p, _ in walk_payload(PLUGIN)
               if any(fnmatch.fnmatchcase(os.path.basename(p), pat) for pat in DEV_NAMES)]
        self.assertEqual(bad, [])

    def test_k3_no_payload_file_names_this_machine_or_leaves_the_payload(self):
        self.need_payload()
        found = []
        for f in payload_files(PLUGIN):
            with open(f, "rb") as fh:
                data = fh.read()
            for needle in {REPO, REPO_REAL, HOME_DIR, os.path.realpath(HOME_DIR)}:
                if needle.encode() in data:
                    found.append((os.path.relpath(f, PLUGIN), needle))
            # C9: the vendored resolver's docstring cites a parent-directory path from a review; its bytes are the
            # vendored digest instead (test_k3_the_vendored_resolver_is_byte_identical); the machine-path rules above still apply
            if b"../" in data and os.path.realpath(f) != os.path.realpath(PLUGINROOT):
                found.append((os.path.relpath(f, PLUGIN), "../"))
        self.assertEqual(found, [])

    def test_k3_the_vendored_resolver_is_byte_identical(self):
        """K3/C9.1: plugin/pluginroot.py, exempt from the `../` text rule, is the vendored file (its sha256)."""
        self.need_payload()
        import hashlib
        self.assertTrue(os.path.isfile(PLUGINROOT), "no plugin/pluginroot.py")
        with open(PLUGINROOT, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PLUGINROOT_SHA256)

    def test_k3_copy_runs_outside_the_repository(self):
        copy = self.copy_payload()
        env = self.env()
        proj, base = self.fixture(env)
        engine = os.path.join(copy, "chongdae.py")
        outs = self.workflow(lambda: [sys.executable, engine], proj, base, env)
        for o in outs:
            self.assert_no_repo(o, "the copied engine's output")
        state, texts = self.records(proj)
        want = "chongdae %s" % self.version(copy)
        self.assertEqual(state["written_by"], want)
        for path, text in texts.items():
            self.assert_no_repo(text, path)
            for v in re.findall(r"chongdae \d+\.\d+\.\d+\S*", text):
                self.assertNotIn("+g", v, (path, v))
        tasks = glob.glob(os.path.join(proj, ".chongdae", "run-*", "tasks", "T1.json"))
        self.assertEqual(len(tasks), 1)
        self.assertEqual(load(tasks[0])["written_by"], want)

    def test_k3_copy_imports_opens_and_executes_nothing_from_the_repository(self):
        copy = self.copy_payload()
        env = self.env()
        proj, base = self.fixture(env)
        engine = os.path.join(copy, "chongdae.py")
        wrapper = os.path.join(self.tmp("chongdae-payload-audit-"), "audited.py")
        write(wrapper, AUDIT_WRAPPER)
        logs = self.tmp("chongdae-payload-logs-")
        made = []

        def prefix():
            made.append(os.path.join(logs, "audit-%d.json" % len(made)))
            return [sys.executable, wrapper, made[-1], REPO_REAL, engine]

        outs = self.workflow(prefix, proj, base, env)
        for o in outs:
            self.assert_no_repo(o, "the audited engine's output")
        self.assertTrue(made)
        hits = []
        for log in made:
            self.assertTrue(os.path.isfile(log), "the audited run left no log: %s" % log)
            hits += load(log)
        self.assertEqual(hits, [])

    # ---------- K1/K3 hooks and command files ----------

    def hook_commands(self, root, name, var):
        cmds = []
        for event, groups in load(os.path.join(root, "hooks", name))["hooks"].items():
            for g in groups:
                for h in g["hooks"]:
                    cmds.append((event, h["command"]))
        self.assertTrue(cmds, name)
        return [(event, cmd, shlex.split(cmd), var) for event, cmd in cmds]

    def test_k1_k3_hook_commands_name_files_inside_the_payload(self):
        self.need_payload()
        for name, var in (("hooks.json", "${CLAUDE_PLUGIN_ROOT}"), ("codex.json", "${PLUGIN_ROOT}")):
            for event, cmd, argv, var in self.hook_commands(PLUGIN, name, var):
                rooted = [a for a in argv if var in a]
                self.assertTrue(rooted, (name, cmd))
                for a in argv:
                    self.assertFalse(os.path.isabs(a), (name, a))
                    self.assertNotIn("..", a.replace("\\", "/").split("/"), (name, a))
                for a in rooted:
                    path = a.replace(var, PLUGIN)
                    self.assertTrue(os.path.isfile(path) and inside(path, PLUGIN), (name, a))

    def test_k1_k3_command_files_name_files_inside_the_payload(self):
        self.need_payload()
        seen = 0
        for md in sorted(glob.glob(os.path.join(PLUGIN, "commands", "*.md"))):
            with open(md, encoding="utf-8") as fh:
                text = fh.read()
            for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)", text):
                seen += 1
                path = os.path.join(PLUGIN, rel)
                self.assertTrue(os.path.exists(path) and inside(path, PLUGIN), (os.path.basename(md), rel))
        self.assertGreater(seen, 0)

    def test_k3_markdown_links_stay_inside_the_payload(self):
        self.need_payload()
        docs = [os.path.join(PLUGIN, "README.md")] + glob.glob(os.path.join(PLUGIN, "skills", "**", "SKILL.md"), recursive=True) \
            + glob.glob(os.path.join(PLUGIN, "commands", "*.md"))
        bad = []
        for md in docs:
            with open(md, encoding="utf-8") as fh:
                text = fh.read()
            for link in MD_LINK.findall(text):
                if re.match(r"(?i)(https?:|mailto:)", link) or link.startswith("#"):
                    continue
                rel = link.split("#", 1)[0]
                path = os.path.normpath(os.path.join(os.path.dirname(md), rel))
                if not (os.path.isfile(path) and inside(path, PLUGIN)):
                    bad.append((os.path.relpath(md, PLUGIN), link))
        self.assertEqual(bad, [])

    def test_k1_k3_copied_hooks_work_outside_the_repository(self):
        copy = self.copy_payload()
        engine = os.path.join(copy, "chongdae.py")
        for name, var, envvar in (("hooks.json", "${CLAUDE_PLUGIN_ROOT}", "CLAUDE_PLUGIN_ROOT"), ("codex.json", "${PLUGIN_ROOT}", "PLUGIN_ROOT")):
            env = self.env(**{envvar: copy})
            proj, _ = self.fixture(env)
            by_script = {}
            for event, cmd, argv, _ in self.hook_commands(copy, name, var):
                argv = [a.replace(var, copy) for a in argv]
                if argv[0] in ("python3", "python"):
                    argv[0] = sys.executable
                by_script[os.path.basename(argv[-1])] = argv
            self.assertEqual(sorted(by_script), ["pre_bash.py", "pre_write.py", "session_start.py"], name)

            def fire(script, payload):
                d = self.sh(by_script[script], proj, env, stdin=json.dumps(payload))
                self.assert_no_repo(d.stdout + d.stderr, "%s %s" % (name, script))
                return d

            write_payload = {"cwd": proj, "tool_name": "Write", "tool_input": {"file_path": os.path.join(proj, "new.py"), "content": "x"}}
            d = fire("session_start.py", {"cwd": proj, "session_id": "payload-s1", "source": "startup"})
            self.assertEqual(d.returncode, 0, (name, d.stdout, d.stderr))
            self.assertIn(engine, json.loads(d.stdout)["hookSpecificOutput"]["additionalContext"], name)
            d = fire("pre_write.py", write_payload)
            self.assertEqual(d.returncode, 2, (name, d.stdout, d.stderr))
            self.assertIn(engine, d.stdout + d.stderr, name)
            d = fire("pre_bash.py", {"cwd": proj, "tool_name": "Bash", "tool_input": {"command": "git status"}})
            self.assertEqual(d.returncode, 0, (name, d.stdout, d.stderr))
            started = self.sh([sys.executable, engine, "init", "--session", "--goal", "hooks"], proj, env)
            self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
            d = fire("pre_write.py", write_payload)
            self.assertEqual(d.returncode, 0, (name, d.stdout, d.stderr))

    # ---------- K4 the root shim ----------

    def test_k4_shim_gives_the_payload_engines_help_and_errors(self):
        self.need_payload()
        env, cwd = self.env(), self.tmp()
        for args in (["--help"], ["definitely-not-a-command"]):
            via_shim = self.sh([sys.executable, os.path.join(REPO, "chongdae.py")] + args, cwd, env)
            direct = self.sh([sys.executable, os.path.join(PLUGIN, "chongdae.py")] + args, cwd, env)
            self.assertEqual((via_shim.returncode, via_shim.stdout, via_shim.stderr), (direct.returncode, direct.stdout, direct.stderr), args)
        self.assertEqual(direct.returncode, 2)
        self.assertTrue(direct.stderr.strip())

    def test_k4_importing_the_shim_yields_the_one_payload_module(self):
        self.need_payload()
        script = ("import json, os, sys, chongdae\n"
                  "eng = os.path.realpath(sys.argv[1])\n"
                  "same = [m for m in {id(m): m for m in list(sys.modules.values())}.values()\n"
                  "        if getattr(m, '__file__', None) and os.path.realpath(m.__file__) == eng]\n"
                  "print(json.dumps({'file': os.path.realpath(chongdae.__file__), 'is': sys.modules['chongdae'] is chongdae,\n"
                  "                  'one': len(same) == 1 and same[0] is chongdae, 'main': callable(getattr(chongdae, 'main', None))}))\n")
        d = self.sh([sys.executable, "-c", script, os.path.join(PLUGIN, "chongdae.py")], REPO, self.env())
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertEqual(json.loads(d.stdout), {"file": os.path.realpath(os.path.join(PLUGIN, "chongdae.py")), "is": True, "one": True, "main": True})

    def test_k4_shim_runs_the_checkouts_payload(self):
        self.need_payload()
        env = self.env()
        proj, _ = self.fixture(env)
        d = self.sh([sys.executable, os.path.join(REPO, "chongdae.py"), "init", "--session", "--goal", "through the shim"], proj, env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        state, _ = self.records(proj)
        self.assertTrue(state["written_by"].startswith("chongdae %s+g" % self.version()), state["written_by"])

    def test_k4_shim_reexecutions_name_the_payload_not_the_shim(self):
        self.need_payload()
        env = self.env()
        proj, _ = self.fixture(env)
        shim = os.path.realpath(os.path.join(REPO, "chongdae.py"))
        wrapper = os.path.join(self.tmp(), "spy.py")
        write(wrapper, "import json, os, runpy, sys\nLOG, SHIM = sys.argv[1], sys.argv[2]\nhits = []\n"
                       "def flat(x):\n    return [z for y in x for z in flat(y)] if isinstance(x, (list, tuple)) else [x]\n"
                       "def audit(ev, args):\n"
                       "    if ev == 'subprocess.Popen' or ev.startswith('os.exec') or ev == 'os.posix_spawn':\n"
                       "        for s in flat(args[1]) + [args[0]]:\n"
                       "            if isinstance(s, (str, bytes)) and os.fsdecode(s).endswith('chongdae.py') and os.path.realpath(os.fsdecode(s)) == SHIM:\n"
                       "                hits.append(repr(args[:2]))\n"
                       "sys.addaudithook(audit)\nsys.argv = [SHIM] + sys.argv[3:]\nsys.path[0] = os.path.dirname(SHIM)\ncode = 0\n"
                       "try:\n    runpy.run_path(SHIM, run_name='__main__')\n"
                       "except SystemExit as e:\n    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)\n"
                       "finally:\n    json.dump(hits, open(LOG, 'w'))\nsys.exit(code)\n")
        log = os.path.join(self.tmp(), "spy.json")
        for args in (["init", "--session", "--goal", "spy"], ["add", "T1", "--check", shlex.join([sys.executable, "-c", "pass"])], ["run"]):
            write(os.path.join(proj, "work.txt"), "w\n")
            d = self.sh([sys.executable, wrapper, log, shim] + args, proj, env)
            self.assertIn(d.returncode, (0, 4), (args, d.stdout, d.stderr))
            self.assertEqual(load(log), [], args)

    def test_k4_shim_is_a_few_lines_without_engine_logic(self):
        self.need_payload()
        shim = os.path.join(REPO, "chongdae.py")
        self.assertTrue(os.path.isfile(shim) and not os.path.islink(shim), "the root chongdae.py is a regular file")
        with open(shim, encoding="utf-8") as fh:
            src = fh.read()
        self.assertLessEqual(len(src.splitlines()), 40)
        self.assertEqual(re.findall(r"(?m)^\s*def\s+(main|cmd_\w*|plugin_root|source_revision)\b", src), [])

    # ---------- K5 working-checkout identity ----------

    def checkout(self, env, source="./plugin"):
        """A repository like this one: plugin/ (a copy of the payload) and a root catalog selecting `source`."""
        self.need_payload()
        top = self.tmp("chongdae-payload-checkout-")
        shutil.copytree(PLUGIN, os.path.join(top, "plugin"), ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(top, "other"))
        write(os.path.join(top, "other", "keep.txt"), "x\n")
        write(os.path.join(top, ".claude-plugin", "marketplace.json"),
              {"name": "chongdae", "plugins": [{"name": "chongdae", "source": source, "version": self.version()}]})
        write(os.path.join(top, ".gitignore"), "__pycache__/\n")
        write(os.path.join(top, "README.md"), "a checkout\n")
        self.git(top, env, "init", "-q")
        self.git(top, env, "add", "-A")
        self.git(top, env, "commit", "-qm", "base")
        return top, self.git(top, env, "rev-parse", "--short", "HEAD")

    def test_k5_a_clean_checkout_payload_is_unreleased(self):
        env = self.env()
        top, sha = self.checkout(env)
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))

    def test_k5_trailing_slash_source_selects_the_same_directory(self):
        env = self.env()
        top, sha = self.checkout(env, source="./plugin/")
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))

    def test_k5_engine_reached_through_a_symlink_compares_by_realpath(self):
        env = self.env()
        top, sha = self.checkout(env)
        alias = os.path.join(self.tmp(), "alias")
        os.symlink(top, alias)
        self.assertEqual(self.engine_of(os.path.join(alias, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))

    def test_k5_changes_outside_the_payload_do_not_make_it_dirty(self):
        env = self.env()
        top, sha = self.checkout(env)
        write(os.path.join(top, "untracked.txt"), "x\n")
        write(os.path.join(top, ".chongdae", "run-x", "state.json"), "{}\n")
        write(os.path.join(top, "reviews", "r.json"), "{}\n")
        with open(os.path.join(top, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("changed\n")
        write(os.path.join(top, "plugin", "__pycache__", "ignored.pyc"), "ignored\n")
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))

    def test_k5_changes_inside_the_payload_make_it_dirty(self):
        env = self.env()
        top, sha = self.checkout(env)
        want = "chongdae %s+g%s-dirty" % (self.version(), sha)
        p = os.path.join(top, "plugin")

        def reset():
            self.git(top, env, "reset", "-q", "--hard")
            self.git(top, env, "clean", "-qfd", "--", "plugin")
            self.assertEqual(self.engine_of(p, env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))

        def modify():
            with open(os.path.join(p, "README.md"), "a", encoding="utf-8") as fh:
                fh.write("changed\n")

        def stage():
            write(os.path.join(p, "staged.txt"), "x\n")
            self.git(top, env, "add", "--", "plugin/staged.txt")

        def delete():
            os.remove(os.path.join(p, "LICENSE"))

        def untracked():
            write(os.path.join(p, "new.txt"), "x\n")

        for change in (modify, stage, delete, untracked):
            change()
            self.assertEqual(self.engine_of(p, env, self.tmp()), want, change.__name__)
            reset()

    def test_k5_a_catalog_that_selects_another_directory_gives_no_revision(self):
        env = self.env()
        top, _ = self.checkout(env, source="./other")
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s" % self.version())

    def test_k5_payload_at_the_top_level_is_unchanged(self):
        self.need_payload()
        env = self.env()
        top = self.tmp("chongdae-payload-toplevel-")
        shutil.copytree(PLUGIN, top, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        self.git(top, env, "init", "-q")
        self.git(top, env, "add", "-A")
        self.git(top, env, "commit", "-qm", "base")
        sha = self.git(top, env, "rev-parse", "--short", "HEAD")
        self.assertEqual(self.engine_of(top, env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))
        write(os.path.join(top, "anything.txt"), "x\n")
        self.assertEqual(self.engine_of(top, env, self.tmp()), "chongdae %s+g%s-dirty" % (self.version(), sha))

    # ---------- K6 plugin_root through catalogs ----------

    def linked(self, env, build):
        """A target whose hunsu.local.json links plugin `w` to a directory D that `build(D)` fills."""
        d = os.path.join(self.tmp("chongdae-payload-linked-"), "D")   # its parent is this test's own: `../x` lands there
        os.makedirs(d)
        build(d)
        target = self.tmp("chongdae-payload-target-")
        write(os.path.join(target, "hunsu.local.json"), {"links": {"w": d}})
        return d, self.plugin_root(target, "w", env)

    def test_k6_link_follows_the_claude_catalog(self):
        env = self.env()

        def build(d):
            os.makedirs(os.path.join(d, "plugin"))
            plugin_manifest(os.path.join(d, "plugin"), "w")
            os.makedirs(os.path.join(d, "w"))   # the catalog wins over the old D/name rule
            write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": "w", "source": "./plugin"}]})
        d, got = self.linked(env, build)
        self.assertEqual(got, os.path.realpath(os.path.join(d, "plugin")))

    def test_k6_link_follows_the_codex_catalog(self):
        env = self.env()

        def build(d):
            os.makedirs(os.path.join(d, "plugin"))
            plugin_manifest(os.path.join(d, "plugin"), "w")
            write(os.path.join(d, ".agents", "plugins", "marketplace.json"),
                  {"name": "m", "plugins": [{"name": "w", "source": {"source": "local", "path": "./plugin"}}]})
        d, got = self.linked(env, build)
        self.assertEqual(got, os.path.realpath(os.path.join(d, "plugin")))

    def test_k6_codex_catalog_when_the_claude_catalog_lacks_the_name(self):
        env = self.env()

        def build(d):
            os.makedirs(os.path.join(d, "plugin"))
            plugin_manifest(os.path.join(d, "plugin"), "w")
            os.makedirs(os.path.join(d, "elsewhere"))
            write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": "other", "source": "./elsewhere"}]})
            write(os.path.join(d, ".agents", "plugins", "marketplace.json"),
                  {"name": "m", "plugins": [{"name": "w", "source": {"source": "local", "path": "./plugin"}}]})
        d, got = self.linked(env, build)
        self.assertEqual(got, os.path.realpath(os.path.join(d, "plugin")))

    def test_k6_without_a_catalog_entry_the_existing_link_rules_apply(self):
        env = self.env()

        def no_entry(d):
            os.makedirs(os.path.join(d, "w"))
            os.makedirs(os.path.join(d, "plugin"))
            write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": "other", "source": "./plugin"}]})
        d, got = self.linked(env, no_entry)
        self.assertEqual(got, os.path.realpath(os.path.join(d, "w")))
        d, got = self.linked(env, lambda d: None)
        self.assertEqual(got, os.path.realpath(d))

    def test_k6_sources_that_leave_d_or_are_remote_are_ignored(self):
        env = self.env()
        outside = self.tmp("chongdae-payload-outside-")
        sources = ["../x", "./plugin/../../x", outside, {"source": "local", "path": "../x"}, {"source": "local", "path": outside},
                   {"source": "github", "repo": "someone/w"}, {"source": "url", "url": "https://example.invalid/w.git"}, {"path": "./plugin"}]
        for source in sources:
            for with_w in (True, False):
                def build(d, source=source, with_w=with_w):
                    os.makedirs(os.path.join(d, "plugin"))
                    os.makedirs(os.path.join(os.path.dirname(d), "x"))
                    if with_w:
                        os.makedirs(os.path.join(d, "w"))
                    write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": "w", "source": source}]})
                d, got = self.linked(env, build)
                self.assertEqual(got, os.path.realpath(os.path.join(d, "w") if with_w else d), (source, with_w))

    def directory_marketplace(self, env, build):
        d = self.tmp("chongdae-payload-devmarket-")
        build(d)
        write(os.path.join(env["HUNSU_CLAUDE_DIR"], "plugins", "known_marketplaces.json"), {"devm": {"source": {"source": "directory", "path": d}}})
        target = self.tmp("chongdae-payload-target-")
        write(os.path.join(target, "hunsu.json"), {"plugins": {"w": {"marketplace": "devm"}}})
        return d, self.plugin_root(target, "w", env)

    def test_k6_directory_marketplace_follows_its_catalog(self):
        env = self.env()

        def build(d):
            os.makedirs(os.path.join(d, "plugin"))
            plugin_manifest(os.path.join(d, "plugin"), "w")
            write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "devm", "plugins": [{"name": "w", "source": "./plugin"}]})
        d, got = self.directory_marketplace(env, build)
        self.assertEqual(got, os.path.realpath(os.path.join(d, "plugin")))

    def test_k6_directory_marketplace_without_a_catalog_is_unchanged(self):
        env = self.env()
        d, got = self.directory_marketplace(env, lambda d: os.makedirs(os.path.join(d, "w")))
        self.assertEqual(got, os.path.realpath(os.path.join(d, "w")))

    def test_k6_chongdae_without_a_link_is_the_payload_directory(self):
        env = self.env()
        target = self.tmp("chongdae-payload-target-")
        self.assertEqual(self.plugin_root(target, "chongdae", env), os.path.realpath(PLUGIN))
        copy = self.copy_payload()
        self.assertEqual(self.plugin_root(target, "chongdae", env, engine_dir=copy), os.path.realpath(copy))

    def test_k6_no_product_is_named_in_the_resolution(self):
        """The catalog rule is generic: a plugin named anything resolves the same way."""
        env = self.env()
        d = self.tmp("chongdae-payload-linked-")
        os.makedirs(os.path.join(d, "pkg"))
        plugin_manifest(os.path.join(d, "pkg"), "zz-anything")
        write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": "zz-anything", "source": "./pkg"}]})
        target = self.tmp("chongdae-payload-target-")
        write(os.path.join(target, "hunsu.local.json"), {"links": {"zz-anything": d}})
        self.assertEqual(self.plugin_root(target, "zz-anything", env), os.path.realpath(os.path.join(d, "pkg")))

    # ---------- L1 working source through either catalog, for the plugin itself ----------

    def l1_repo(self, env, claude=None, codex=None, vendor=False, nameless=False):
        """A repository holding plugin/ (a copy of the payload), optionally vendor/chongdae/ (a second copy), and only the
        catalogs given (`claude`: plugins[] of .claude-plugin/marketplace.json, `codex`: of .agents/plugins/marketplace.json)."""
        self.need_payload()
        top = self.tmp("chongdae-payload-l1-")
        copies = [os.path.join(top, "plugin")] + ([os.path.join(top, "vendor", "chongdae")] if vendor else [])
        for c in copies:
            shutil.copytree(PLUGIN, c, ignore=shutil.ignore_patterns("__pycache__"))
            if nameless:
                for m in MANIFESTS:
                    data = load(os.path.join(c, m))
                    data.pop("name", None)
                    write(os.path.join(c, m), data)
        write(os.path.join(top, "other", "keep.txt"), "x\n")
        if claude is not None:
            write(os.path.join(top, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": claude})
        if codex is not None:
            write(os.path.join(top, ".agents", "plugins", "marketplace.json"), {"name": "m", "plugins": codex})
        write(os.path.join(top, ".gitignore"), "__pycache__/\n")
        write(os.path.join(top, "README.md"), "a checkout\n")
        self.git(top, env, "init", "-q")
        self.git(top, env, "add", "-A")
        self.git(top, env, "commit", "-qm", "base")
        return top, self.git(top, env, "rev-parse", "--short", "HEAD")

    CODEX_SELF = [{"name": "chongdae", "source": {"source": "local", "path": "./plugin"}}]

    def test_l1_codex_only_catalog_names_the_payload_working_source(self):
        """L1: a repository with only the Codex catalog, entry `chongdae` local ./plugin, makes plugin/ working source."""
        env = self.env()
        top, sha = self.l1_repo(env, codex=self.CODEX_SELF)
        self.assertFalse(os.path.exists(os.path.join(top, ".claude-plugin")))
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))

    def test_l1_codex_only_dirty_counts_inside_the_engine_directory_only(self):
        """L1/K5: through the Codex catalog, a change outside plugin/ leaves it clean, a change inside makes it -dirty."""
        env = self.env()
        top, sha = self.l1_repo(env, codex=self.CODEX_SELF)
        p = os.path.join(top, "plugin")
        write(os.path.join(top, "untracked.txt"), "x\n")
        with open(os.path.join(top, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("changed\n")
        write(os.path.join(top, ".chongdae", "run-x", "state.json"), "{}\n")
        self.assertEqual(self.engine_of(p, env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha))
        with open(os.path.join(p, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("changed\n")
        self.assertEqual(self.engine_of(p, env, self.tmp()), "chongdae %s+g%s-dirty" % (self.version(), sha))

    def test_l1_codex_entry_under_another_name_is_not_working_source(self):
        """L1: the Codex entry must carry the plugin's own manifest name; `other` pointing at ./plugin selects nothing for it."""
        env = self.env()
        top, sha = self.l1_repo(env, codex=self.CODEX_SELF)
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha),
                         "control: the same repository with the entry named chongdae is working source")
        top, _ = self.l1_repo(env, codex=[{"name": "other", "source": {"source": "local", "path": "./plugin"}}])
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s" % self.version())

    def test_l1_claude_entry_under_another_name_is_not_working_source(self):
        """L1: a Claude catalog whose only entry is `other` with source ./plugin does not make plugin/ working source."""
        env = self.env()
        top, _ = self.l1_repo(env, claude=[{"name": "other", "source": "./plugin"}])
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s" % self.version())

    def test_l1_an_unrelated_nested_copy_is_not_working_source(self):
        """L1: the catalog selects ./plugin for chongdae; an engine running from vendor/chongdae/ is not working source."""
        env = self.env()
        for kind in ("codex", "claude"):
            if kind == "codex":
                top, sha = self.l1_repo(env, codex=self.CODEX_SELF, vendor=True)
            else:
                top, sha = self.l1_repo(env, claude=[{"name": "chongdae", "source": "./plugin"}], vendor=True)
            self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha),
                             (kind, "control: the selected copy is working source"))
            self.assertEqual(self.engine_of(os.path.join(top, "vendor", "chongdae"), env, self.tmp()), "chongdae %s" % self.version(), kind)

    def test_l1_a_remote_source_is_not_working_source(self):
        """L1: an entry `chongdae` with a remote source ({"source": "github", ...}) does not make plugin/ working source."""
        env = self.env()
        top, sha = self.l1_repo(env, codex=self.CODEX_SELF)
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s+g%s" % (self.version(), sha),
                         "control: the local Codex entry is working source")
        remote = {"source": "github", "repo": "x/chongdae"}
        for kw in ({"codex": [{"name": "chongdae", "source": remote}]}, {"claude": [{"name": "chongdae", "source": remote}]}):
            top, _ = self.l1_repo(env, **kw)
            self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s" % self.version(), kw)

    def test_l1_an_engine_directory_without_a_manifest_name_is_not_working_source(self):
        """L1: with no `name` in any manifest of the engine directory, no catalog entry can select it for the plugin."""
        env = self.env()
        top, _ = self.l1_repo(env, claude=[{"name": "chongdae", "source": "./plugin"}], nameless=True)
        self.assertEqual(self.engine_of(os.path.join(top, "plugin"), env, self.tmp()), "chongdae %s" % self.version())

    # ---------- L2 a string source is a local path only ----------

    def link_to(self, env, name, build):
        """A target whose hunsu.local.json links plugin `name` to a directory D that `build(D)` fills; (D, plugin_root)."""
        d = os.path.join(self.tmp("chongdae-payload-linked-"), "D")
        os.makedirs(d)
        build(d)
        target = self.tmp("chongdae-payload-target-")
        write(os.path.join(target, "hunsu.local.json"), {"links": {name: d}})
        return d, self.plugin_root(target, name, env)

    def market_to(self, env, name, build):
        """A target declaring plugin `name` from a Claude `directory` marketplace D that `build(D)` fills; (D, plugin_root)."""
        d = os.path.join(self.tmp("chongdae-payload-devmarket-"), "D")
        os.makedirs(d)
        build(d)
        write(os.path.join(env["HUNSU_CLAUDE_DIR"], "plugins", "known_marketplaces.json"), {"devm": {"source": {"source": "directory", "path": d}}})
        target = self.tmp("chongdae-payload-target-")
        write(os.path.join(target, "hunsu.json"), {"plugins": {name: {"marketplace": "devm"}}})
        return d, self.plugin_root(target, name, env)

    URI_LOOKALIKES = [("https://example.invalid/probe", os.path.join("https:", "example.invalid", "probe")),
                      ("git+ssh://example.invalid/probe", os.path.join("git+ssh:", "example.invalid", "probe")),
                      ("file:plugin", "file:plugin"),
                      ("git@example.invalid:probe", "git@example.invalid:probe")]

    def l2_case(self, env, source, lookalike, codex, with_probe):
        def build(d):
            os.makedirs(os.path.join(d, lookalike))
            if with_probe:
                os.makedirs(os.path.join(d, "probe"))
            if codex:
                write(os.path.join(d, ".agents", "plugins", "marketplace.json"),
                      {"name": "m", "plugins": [{"name": "probe", "source": {"source": "local", "path": source}}]})
            else:
                write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": "probe", "source": source}]})
        d, got = self.link_to(env, "probe", build)
        self.assertTrue(os.path.isdir(os.path.join(d, lookalike)))
        self.assertNotEqual(got, os.path.realpath(os.path.join(d, lookalike)), (source, codex, with_probe, "the lookalike was taken"))
        self.assertEqual(got, os.path.realpath(os.path.join(d, "probe") if with_probe else d), (source, codex, with_probe))

    def test_l2_https_string_source_selects_nothing_despite_a_lookalike(self):
        """L2: Claude source "https://example.invalid/probe" with D/https:/example.invalid/probe existing → D (legacy), or D/probe."""
        env = self.env()
        for with_probe in (False, True):
            self.l2_case(env, "https://example.invalid/probe", os.path.join("https:", "example.invalid", "probe"), False, with_probe)

    def test_l2_codex_local_path_with_a_scheme_selects_nothing(self):
        """L2: the `path` of a Codex {"source": "local"} object carrying a URI scheme is not a path, even with a lookalike."""
        env = self.env()
        for with_probe in (False, True):
            self.l2_case(env, "https://example.invalid/probe", os.path.join("https:", "example.invalid", "probe"), True, with_probe)

    def test_l2_file_and_git_ssh_scheme_sources_select_nothing(self):
        """L2: `file:plugin` (with D/file:plugin existing) and `git+ssh://…` (with its lookalike) select nothing."""
        env = self.env()
        for source, lookalike in self.URI_LOOKALIKES[1:3]:
            for codex in (False, True):
                for with_probe in (False, True):
                    self.l2_case(env, source, lookalike, codex, with_probe)

    def test_l2_scp_style_source_selects_nothing(self):
        """L2: an scp-style `git@example.invalid:probe` is not a path, even when D/git@example.invalid:probe exists."""
        env = self.env()
        source, lookalike = self.URI_LOOKALIKES[3]
        for codex in (False, True):
            for with_probe in (False, True):
                self.l2_case(env, source, lookalike, codex, with_probe)

    def test_l2_uri_sources_select_nothing_for_a_directory_marketplace(self):
        """L2: through a Claude directory marketplace D, a URI source with a lookalike gives D/probe, never the lookalike."""
        env = self.env()
        for source, lookalike in self.URI_LOOKALIKES:
            def build(d, source=source, lookalike=lookalike):
                os.makedirs(os.path.join(d, lookalike))
                os.makedirs(os.path.join(d, "probe"))
                write(os.path.join(d, ".claude-plugin", "marketplace.json"), {"name": "devm", "plugins": [{"name": "probe", "source": source}]})
            d, got = self.market_to(self.env(), "probe", build)
            self.assertEqual(got, os.path.realpath(os.path.join(d, "probe")), source)

    def test_l2_symlink_leaving_d_stays_rejected(self):
        """L2/K6: a symlink inside D selected by the catalog whose target lies outside D is rejected (D, or D/probe)."""
        env = self.env()
        outside = self.tmp("chongdae-payload-outside-")
        for source in ("./plugin", {"source": "local", "path": "./plugin"}):
            for with_probe in (False, True):
                def build(d, source=source, with_probe=with_probe):
                    os.symlink(outside, os.path.join(d, "plugin"))
                    if with_probe:
                        os.makedirs(os.path.join(d, "probe"))
                    cat = (".claude-plugin", "marketplace.json") if isinstance(source, str) else (".agents", "plugins", "marketplace.json")
                    write(os.path.join(d, *cat), {"name": "m", "plugins": [{"name": "probe", "source": source}]})
                d, got = self.link_to(env, "probe", build)
                self.assertNotEqual(got, os.path.realpath(outside), (source, with_probe))
                self.assertEqual(got, os.path.realpath(os.path.join(d, "probe") if with_probe else d), (source, with_probe))

    # ---------- L3 one level of checkouts ----------

    def resolvers(self):
        return (("link", self.link_to), ("directory marketplace", self.market_to))

    def child(self, b, name, claude=None, codex=None, dirs=("plugin",)):
        """B/name: a checkout holding the given catalogs (plugins[] lists) and directories. When an entry for `name` selects
        ./plugin, plugin/ holds a manifest naming `name`, as a real payload does; no other selected directory gets one."""
        c = os.path.join(b, name)
        os.makedirs(c, exist_ok=True)
        for x in dirs:
            os.makedirs(os.path.join(c, x), exist_ok=True)
        for entry in (claude or []) + (codex or []):
            src = entry.get("source")
            if entry.get("name") == name and src in ("./plugin", {"source": "local", "path": "./plugin"}) and os.path.isdir(os.path.join(c, "plugin")):
                plugin_manifest(os.path.join(c, "plugin"), name)
        if claude is not None:
            write(os.path.join(c, ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": claude})
        if codex is not None:
            write(os.path.join(c, ".agents", "plugins", "marketplace.json"), {"name": "m", "plugins": codex})
        return c

    def test_l3_child_claude_catalog_is_followed(self):
        """L3: B has no catalog; B/<name>/.claude-plugin/marketplace.json selects ./plugin → B/<name>/plugin (link and directory marketplace)."""
        for how, resolve in self.resolvers():
            for name in ("probe", "zz-tool"):
                d, got = resolve(self.env(), name, lambda b, name=name: self.child(b, name, claude=[{"name": name, "source": "./plugin"}]))
                self.assertEqual(got, os.path.realpath(os.path.join(d, name, "plugin")), (how, name))

    def test_l3_child_codex_only_catalog_is_followed(self):
        """L3: a Codex-only child catalog (local path ./plugin) → B/<name>/plugin."""
        for how, resolve in self.resolvers():
            for name in ("probe", "zz-tool"):
                d, got = resolve(self.env(), name, lambda b, name=name: self.child(
                    b, name, codex=[{"name": name, "source": {"source": "local", "path": "./plugin"}}]))
                self.assertEqual(got, os.path.realpath(os.path.join(d, name, "plugin")), (how, name))

    def test_l3_the_folders_own_catalog_wins_over_the_childs(self):
        """L3: order — B's own catalog selecting ./direct beats the child's catalog; without it the child's catalog decides."""
        for how, resolve in self.resolvers():
            for name in ("probe", "zz-tool"):
                def build(b, name=name, direct=False):
                    self.child(b, name, claude=[{"name": name, "source": "./plugin"}])
                    if direct:
                        os.makedirs(os.path.join(b, "direct"))
                        plugin_manifest(os.path.join(b, "direct"), name)
                        write(os.path.join(b, ".claude-plugin", "marketplace.json"), {"name": "devm", "plugins": [{"name": name, "source": "./direct"}]})
                d, got = resolve(self.env(), name, build)
                self.assertEqual(got, os.path.realpath(os.path.join(d, name, "plugin")), (how, name, "child only"))
                d, got = resolve(self.env(), name, lambda b, name=name: build(b, name, True))
                self.assertEqual(got, os.path.realpath(os.path.join(d, "direct")), (how, name, "both"))

    def test_l3_a_child_catalog_that_selects_nothing_falls_back_to_the_child(self):
        """L3: a child catalog without an entry for the name, selecting a missing directory, or a remote/URI/escaping source → B/<name>."""
        outside = self.tmp("chongdae-payload-outside-")
        for how, resolve in self.resolvers():
            for name in ("probe", "zz-tool"):
                d, got = resolve(self.env(), name, lambda b, name=name: self.child(b, name, claude=[{"name": name, "source": "./plugin"}]))
                self.assertEqual(got, os.path.realpath(os.path.join(d, name, "plugin")), (how, name, "control"))
                cases = [("no entry", {"claude": [{"name": "other", "source": "./plugin"}]}),
                         ("missing", {"claude": [{"name": name, "source": "./absent"}]}),
                         ("remote", {"claude": [{"name": name, "source": {"source": "github", "repo": "x/" + name}}]}),
                         ("url", {"claude": [{"name": name, "source": {"source": "url", "url": "https://example.invalid/x.git"}}]}),
                         ("uri", {"claude": [{"name": name, "source": "https://example.invalid/x"}]}),
                         ("escape", {"claude": [{"name": name, "source": "../" + name + "-sib"}]}),
                         ("escape-codex", {"codex": [{"name": name, "source": {"source": "local", "path": "../" + name + "-sib"}}]}),
                         ("absolute", {"claude": [{"name": name, "source": outside}]})]
                for label, cat in cases:
                    def build(b, name=name, cat=cat):
                        c = self.child(b, name, **cat)
                        os.makedirs(os.path.join(c, "https:", "example.invalid", "x"))
                        os.makedirs(os.path.join(b, name + "-sib"))
                    d, got = resolve(self.env(), name, build)
                    self.assertEqual(got, os.path.realpath(os.path.join(d, name)), (how, name, label))

    def test_l3_a_grandchild_catalog_is_not_followed(self):
        """L3: only one level — B/<name>/plugin/.claude-plugin/marketplace.json selecting ./deeper is not read → B/<name>/plugin."""
        for how, resolve in self.resolvers():
            for name in ("probe", "zz-tool"):
                def build(b, name=name):
                    c = self.child(b, name, claude=[{"name": name, "source": "./plugin"}])
                    os.makedirs(os.path.join(c, "plugin", "deeper"))
                    write(os.path.join(c, "plugin", ".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": name, "source": "./deeper"}]})
                d, got = resolve(self.env(), name, build)
                self.assertEqual(got, os.path.realpath(os.path.join(d, name, "plugin")), (how, name))

    def test_l3_no_second_level_of_children(self):
        """L3: a child with no catalog but a B/<name>/<name>/ directory resolves to B/<name>, not deeper."""
        for how, resolve in self.resolvers():
            for name in ("probe", "zz-tool"):
                d, got = resolve(self.env(), name, lambda b, name=name: self.child(b, name, claude=[{"name": name, "source": "./plugin"}]))
                self.assertEqual(got, os.path.realpath(os.path.join(d, name, "plugin")), (how, name, "control"))
                d, got = resolve(self.env(), name, lambda b, name=name: self.child(b, name, dirs=("plugin", name)))
                self.assertEqual(got, os.path.realpath(os.path.join(d, name)), (how, name))

    def test_l3_flat_link_and_direct_catalog_resolve_as_before(self):
        """L3: a flat link (B is the plugin itself, no catalog, no B/<name>) → B; a direct catalog in B → its selection."""
        env = self.env()
        d, got = self.link_to(env, "probe", lambda b: self.child(b, "nested", claude=[{"name": "probe", "source": "./plugin"}]))
        self.assertEqual(got, os.path.realpath(d), "a flat link with an unrelated child checkout")
        d, got = self.link_to(env, "probe", lambda b: self.child(b, "probe", claude=[{"name": "probe", "source": "./plugin"}]))
        self.assertEqual(got, os.path.realpath(os.path.join(d, "probe", "plugin")), "control: the child named for the plugin is followed")

    def test_l3_a_name_that_is_not_one_segment_is_not_a_child(self):
        """L3: `name` is a child only when it is one path segment: `sub/probe` never follows B/sub/probe's catalog."""
        env = self.env()
        d, got = self.link_to(env, "probe", lambda b: self.child(b, "probe", claude=[{"name": "probe", "source": "./plugin"}]))
        self.assertEqual(got, os.path.realpath(os.path.join(d, "probe", "plugin")), "control: a one-segment name is followed")
        name = "sub/probe"
        d, got = self.link_to(env, name, lambda b: self.child(b, name, claude=[{"name": name, "source": "./plugin"}]))
        self.assertNotEqual(got, os.path.realpath(os.path.join(d, "sub", "probe", "plugin")))

    def l3_workflow(self, env, proj, name):
        """The payload engine: init --session, add T1 with a check running {plugin:<name>}/tool.py, a change, run until done."""
        engine = [sys.executable, os.path.join(PLUGIN, "chongdae.py")]
        d = self.sh(engine + ["init", "--session", "--goal", "a folder of checkouts"], proj, env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        d = self.sh(engine + ["add", "T1", "--check", "%s {plugin:%s}/tool.py" % (shlex.quote(sys.executable), name)], proj, env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        write(os.path.join(proj, "work.txt"), "the work of T1\n")
        said = ""
        for _ in range(15):
            d = self.sh(engine + ["run"], proj, env)
            said += d.stdout + d.stderr
            if d.returncode != 4:
                break
        return d, said

    def l3_folder(self, name):
        """A folder of checkouts B: B/<name>/.claude-plugin/marketplace.json selects ./plugin, B/<name>/plugin/tool.py writes a marker."""
        b = os.path.join(self.tmp("chongdae-payload-market-"), "B")
        marker = os.path.join(self.tmp("chongdae-payload-marker-"), "ran.txt")
        self.child(b, name, claude=[{"name": name, "source": "./plugin"}])
        write(os.path.join(b, name, "plugin", "tool.py"),
              "import os\nopen(%r, 'w').write(os.path.realpath(os.path.dirname(os.path.abspath(__file__))))\n" % marker)
        self.assertFalse(os.path.exists(os.path.join(b, name, "tool.py")))
        return b, marker

    def test_l3_cli_check_through_a_linked_folder_runs_the_childs_plugin(self):
        """L3: a check `{plugin:probe}/tool.py` in a project linking probe to a folder of checkouts runs B/probe/plugin/tool.py; T1 done."""
        self.need_payload()
        env = self.env()
        b, marker = self.l3_folder("probe")
        proj = self.tmp("chongdae-payload-project-")
        self.git(proj, env, "init", "-q")
        write(os.path.join(proj, "README.md"), "a fixture project\n")
        write(os.path.join(proj, "hunsu.local.json"), {"links": {"probe": b}})
        self.git(proj, env, "add", "-A")
        self.git(proj, env, "commit", "-qm", "base")
        d, said = self.l3_workflow(env, proj, "probe")
        self.assertTrue(os.path.isfile(marker), "the tool never ran from B/probe/plugin: exit %s\n%s" % (d.returncode, said))
        with open(marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), os.path.realpath(os.path.join(b, "probe", "plugin")))
        self.assertEqual(d.returncode, 0, said)
        self.assertIn("done T1", said)

    def test_l3_cli_check_through_a_directory_marketplace_runs_the_childs_plugin(self):
        """L3: the same with zz-tool declared in hunsu.json from a Claude directory marketplace B → B/zz-tool/plugin/tool.py runs."""
        self.need_payload()
        env = self.env()
        b, marker = self.l3_folder("zz-tool")
        write(os.path.join(env["HUNSU_CLAUDE_DIR"], "plugins", "known_marketplaces.json"), {"devm": {"source": {"source": "directory", "path": b}}})
        proj = self.tmp("chongdae-payload-project-")
        self.git(proj, env, "init", "-q")
        write(os.path.join(proj, "README.md"), "a fixture project\n")
        write(os.path.join(proj, "hunsu.json"), {"plugins": {"zz-tool": {"marketplace": "devm"}}})
        self.git(proj, env, "add", "-A")
        self.git(proj, env, "commit", "-qm", "base")
        d, said = self.l3_workflow(env, proj, "zz-tool")
        self.assertTrue(os.path.isfile(marker), "the tool never ran from B/zz-tool/plugin: exit %s\n%s" % (d.returncode, said))
        with open(marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), os.path.realpath(os.path.join(b, "zz-tool", "plugin")))
        self.assertEqual(d.returncode, 0, said)
        self.assertIn("done T1", said)

    # ---------- M1 the named child stays inside the folder before its catalog is read ----------

    M1_CATALOGS = (("claude", (".claude-plugin", "marketplace.json"), {"name": "m", "plugins": [{"name": "probe", "source": "./plugin"}]}),
                   ("codex-only", (".agents", "plugins", "marketplace.json"),
                    {"name": "m", "plugins": [{"name": "probe", "source": {"source": "local", "path": "./plugin"}}]}))

    def raw_plugin_root(self, target, name, env):
        """plugin_root as the engine prints it, not realpathed (M/probe is a symlink: its realpath is elsewhere)."""
        self.need_payload()
        d = self.sh([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import chongdae; "
                     "print(chongdae.plugin_root(sys.argv[2], sys.argv[3]))", PLUGIN, target, name], self.tmp(), env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        return d.stdout.strip()

    def raw_resolvers(self):
        """(how, resolve(env, build) -> (M, raw plugin_root of `probe`)) for a hunsu.local.json link and a directory marketplace."""
        def link(env, build):
            m = os.path.join(self.tmp("chongdae-payload-linked-"), "M")
            os.makedirs(m)
            build(m)
            target = self.tmp("chongdae-payload-target-")
            write(os.path.join(target, "hunsu.local.json"), {"links": {"probe": m}})
            return m, self.raw_plugin_root(target, "probe", env)

        def market(env, build):
            m = os.path.join(self.tmp("chongdae-payload-devmarket-"), "M")
            os.makedirs(m)
            build(m)
            write(os.path.join(env["HUNSU_CLAUDE_DIR"], "plugins", "known_marketplaces.json"),
                  {"devm": {"source": {"source": "directory", "path": m}}})
            target = self.tmp("chongdae-payload-target-")
            write(os.path.join(target, "hunsu.json"), {"plugins": {"probe": {"marketplace": "devm"}}})
            return m, self.raw_plugin_root(target, "probe", env)
        return (("link", link), ("directory marketplace", market))

    def m1_escape(self, m, style, catalogs):
        """M/probe leaves M: `relative` ../outside, `absolute` /…/outside, `dotdot` .. (the folder's parent is the outside),
        `chain` M/hop -> ../outside and M/probe -> hop. The outside holds the given catalogs selecting ./plugin, and plugin/.
        Returns the outside directory."""
        parent = os.path.dirname(m)
        outside = parent if style == "dotdot" else os.path.join(parent, "outside")
        os.makedirs(os.path.join(outside, "plugin"), exist_ok=True)
        # a plugin manifest naming probe: the directory the escaping catalog selects would be taken if that catalog were read
        write(os.path.join(outside, "plugin", ".claude-plugin", "plugin.json"), {"name": "probe", "version": "1.0.0"})
        for _label, rel, body in catalogs:
            write(os.path.join(outside, *rel), body)
        if style == "relative":
            os.symlink(os.path.join("..", "outside"), os.path.join(m, "probe"))
        elif style == "absolute":
            os.symlink(outside, os.path.join(m, "probe"))
        elif style == "dotdot":
            os.symlink("..", os.path.join(m, "probe"))
        elif style == "chain":
            os.symlink(os.path.join("..", "outside"), os.path.join(m, "hop"))
            os.symlink("hop", os.path.join(m, "probe"))
        else:
            raise AssertionError(style)
        self.assertTrue(os.path.isdir(os.path.join(m, "probe")), "fixture: M/probe is not a directory")
        self.assertFalse(inside(os.path.join(m, "probe"), m), "fixture: M/probe does not leave M")
        return outside

    def assert_m1_legacy(self, m, outside, got, what):
        sel = os.path.join(outside, "plugin")
        self.assertIsInstance(got, str, (what, got))
        self.assertNotEqual(got, sel, (what, "the escaping child's catalog was read"))
        self.assertFalse(inside(got, sel), (what, "a result at or under outside/plugin", got))
        self.assertFalse(got.startswith(sel), (what, "a result naming outside/plugin", got))
        self.assertEqual(got, os.path.join(m, "probe"), (what, "the legacy child as named"))

    def m1_cases(self, styles=("relative",)):
        for style in styles:
            for cat in self.M1_CATALOGS:
                yield style, cat[0], (cat,)

    def test_m1_reproducer_link_and_directory_marketplace_give_the_child_as_named(self):
        """M1: the reproducer (M/probe -> ../outside, outside's Claude catalog selects ./plugin) → M/probe, never outside/plugin."""
        for how, resolve in self.raw_resolvers():
            env = self.env()
            box = {}
            m, got = resolve(env, lambda m: box.update(outside=self.m1_escape(m, "relative", self.M1_CATALOGS[:1])))
            self.assert_m1_legacy(m, box["outside"], got, (how, "relative", "claude"))

    def test_m1_codex_only_catalog_outside_is_not_read(self):
        """M1: the same with only a Codex catalog in outside/ (local path ./plugin) → M/probe."""
        for how, resolve in self.raw_resolvers():
            env = self.env()
            box = {}
            m, got = resolve(env, lambda m: box.update(outside=self.m1_escape(m, "relative", self.M1_CATALOGS[1:])))
            self.assert_m1_legacy(m, box["outside"], got, (how, "relative", "codex-only"))

    def test_m1_both_catalogs_outside_select_nothing(self):
        """M1: neither its Claude nor its Codex-only catalog selects anything — both present in outside/ → M/probe."""
        for how, resolve in self.raw_resolvers():
            env = self.env()
            box = {}
            m, got = resolve(env, lambda m: box.update(outside=self.m1_escape(m, "relative", self.M1_CATALOGS)))
            self.assert_m1_legacy(m, box["outside"], got, (how, "relative", "both"))

    def test_m1_absolute_symlink_target_is_not_followed_into_its_catalog(self):
        """M1: M/probe -> /abs/outside (absolute target), Claude or Codex-only catalog there → M/probe."""
        for how, resolve in self.raw_resolvers():
            for style, label, cats in self.m1_cases(("absolute",)):
                env = self.env()
                box = {}
                m, got = resolve(env, lambda m, cats=cats: box.update(outside=self.m1_escape(m, style, cats)))
                self.assert_m1_legacy(m, box["outside"], got, (how, style, label))

    def test_m1_symlink_to_dotdot_and_through_a_chain_leave_the_folder(self):
        """M1: M/probe -> .. (the folder's parent holds the catalog), and M/probe -> M/hop -> ../outside → M/probe."""
        for how, resolve in self.raw_resolvers():
            for style, label, cats in self.m1_cases(("dotdot", "chain")):
                env = self.env()
                box = {}
                m, got = resolve(env, lambda m, style=style, cats=cats: box.update(outside=self.m1_escape(m, style, cats)))
                self.assert_m1_legacy(m, box["outside"], got, (how, style, label))

    CHECKOUT_PROBE = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import chongdae
opened = []
def hook(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes)):
        opened.append(os.fsdecode(args[0]))
sys.addaudithook(hook)
root = chongdae.checkout_root(sys.argv[2], sys.argv[3])
sys.stdout.write(json.dumps({"root": root, "opened": opened}))
'''

    def checkout_probe(self, m, env):
        self.need_payload()
        d = self.sh([sys.executable, "-c", self.CHECKOUT_PROBE, PLUGIN, m, "probe"], self.tmp(), env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        return json.loads(d.stdout)

    def test_m1_checkout_root_does_not_read_an_escaping_childs_catalog(self):
        """M1: checkout_root(M, "probe") in the payload engine, every escape style and catalog kind → M/probe, and no
        marketplace.json outside M is opened at all."""
        for style, label, cats in self.m1_cases(("relative", "absolute", "dotdot", "chain")):
            env = self.env()
            m = os.path.join(self.tmp("chongdae-payload-folder-"), "M")
            os.makedirs(m)
            outside = self.m1_escape(m, style, cats)
            out = self.checkout_probe(m, env)
            read = [p for p in out["opened"] if os.path.basename(p) == "marketplace.json" and not inside(p, m)]
            self.assertEqual(read, [], (style, label, "the escaping child's catalog was opened"))
            self.assert_m1_legacy(m, outside, out["root"], ("checkout_root", style, label))

    def test_m1_inside_symlink_child_is_still_followed(self):
        """M1 control: M/probe -> checkouts/probe (relative or absolute, inside M), its catalog selecting ./plugin →
        M/checkouts/probe/plugin, for a link, a directory marketplace and checkout_root. Already right at eac5c6a."""
        for style in ("relative", "absolute"):
            for _label, rel, body in self.M1_CATALOGS:
                def build(m, style=style, rel=rel, body=body):
                    real = os.path.join(m, "checkouts", "probe")
                    os.makedirs(os.path.join(real, "plugin"))
                    plugin_manifest(os.path.join(real, "plugin"), "probe")
                    write(os.path.join(real, *rel), body)
                    os.symlink(os.path.join("checkouts", "probe") if style == "relative" else real, os.path.join(m, "probe"))
                for how, resolve in self.raw_resolvers():
                    m, got = resolve(self.env(), build)
                    self.assertEqual(os.path.realpath(got), os.path.realpath(os.path.join(m, "checkouts", "probe", "plugin")),
                                     (how, style, _label))
                m = os.path.join(self.tmp("chongdae-payload-folder-"), "M")
                os.makedirs(m)
                build(m)
                out = self.checkout_probe(m, self.env())
                self.assertEqual(os.path.realpath(out["root"]), os.path.realpath(os.path.join(m, "checkouts", "probe", "plugin")),
                                 ("checkout_root", style, _label))

    # ---------- C9 `{plugin:NAME}` through the vendored resolver ----------

    C9_PROBE = r'''
import json, os, sys
where, target, name, calls, versions = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5] == "1"
sys.path.insert(0, where)   # plugin/ (as a hook or a test has it) or the repository root (the shim only)
import chongdae
out = {"roots": [], "error": None}
try:
    for _ in range(calls):
        out["roots"].append(chongdae.plugin_root(target, name))
except SystemExit as err:
    out["error"] = "" if err.code is None else str(err.code)
if versions:
    out["versions"] = chongdae.plugin_versions(target, ["{plugin:%s}/x" % name])
out["engine"] = os.path.realpath(chongdae.__file__)
out["resolvers"] = sorted({os.path.realpath(m.__file__) for m in list(sys.modules.values())
                           if getattr(m, "__file__", None) and os.path.basename(m.__file__).startswith("pluginroot")})
sys.stdout.write(json.dumps(out))
'''

    def c9_env(self, host="claude-code", **extra):
        """A stripped environment with its own (empty) Claude and Codex homes; host None leaves AGENT_HOST unset."""
        env = self.env(**extra)
        for k in ("HUNSU_CODEX_DIR", "AGENT_CODEX_HOME"):
            env.pop(k, None)
        env["CODEX_HOME"] = os.path.join(env["HOME"], ".codex")
        os.makedirs(env["CODEX_HOME"], exist_ok=True)
        if host is None:
            env.pop("AGENT_HOST", None)
        else:
            env["AGENT_HOST"] = host
        return env

    def c9_codex_install(self, env, market, name, version, enabled=True):
        """A Codex install: config.toml [plugins."NAME@MARKET"] enabled, and its cache copy with a Codex manifest."""
        home = env["CODEX_HOME"]
        root = os.path.join(home, "plugins", "cache", market, name, version)
        write(os.path.join(root, ".codex-plugin", "plugin.json"), {"name": name, "version": version})
        config = os.path.join(home, "config.toml")
        text = open(config, encoding="utf-8").read() if os.path.isfile(config) else ""
        write(config, text + '[plugins."%s@%s"]\nenabled = %s\n\n' % (name, market, "true" if enabled else "false"))
        return root

    def c9_claude_install(self, env, market, name, version):
        """A Claude Code user-scope install: installed_plugins.json NAME@MARKET with an existing installPath."""
        root = os.path.join(self.tmp("chongdae-payload-claude-cache-"), market, name, version)
        write(os.path.join(root, ".claude-plugin", "plugin.json"), {"name": name, "version": version})
        reg = os.path.join(env["HUNSU_CLAUDE_DIR"], "plugins", "installed_plugins.json")
        doc = load(reg) if os.path.isfile(reg) else {"version": 2, "plugins": {}}
        doc["plugins"].setdefault("%s@%s" % (name, market), []).append(
            {"scope": "user", "installPath": root, "version": version, "installedAt": "2026-11-06T00:00:00.000Z"})
        write(reg, doc)
        return root

    def c9_target(self, plugins=None, local=None):
        target = self.tmp("chongdae-payload-target-")
        if plugins is not None:
            write(os.path.join(target, "hunsu.json"), {"plugins": plugins})
        if local is not None:
            write(os.path.join(target, "hunsu.local.json"), local)
        return target

    def c9_probe(self, target, name, env, where=PLUGIN, calls=1, versions=False):
        """plugin_root (calls times) and optionally plugin_versions in one fresh process: (result dict, stderr)."""
        self.need_payload()
        d = self.sh([sys.executable, "-c", self.C9_PROBE, where, target, name, str(calls), "1" if versions else "0"], self.tmp(), env)
        self.assertEqual(d.returncode, 0, ("the probe itself failed", d.stdout, d.stderr))
        return json.loads(d.stdout), d.stderr

    def assert_c9_root(self, out, err, want, what):
        self.assertIsNone(out["error"], (what, "plugin_root raised", out["error"], err))
        self.assertTrue(out["roots"], (what, out))
        self.assertEqual(os.path.realpath(out["roots"][0]), os.path.realpath(want), (what, out, err))

    def assert_c9_fails(self, out, err, what, *needles):
        self.assertFalse(out["roots"], (what, "a root was returned", out, err))
        self.assertIsNotNone(out["error"], (what, out, err))
        said = out["error"] + "\n" + err
        for n in needles:
            self.assertIn(n, said, (what, said))
        return said

    W_DECL = {"w": {"marketplace": "m", "version": "1.0.0"}}

    def test_C9_2_codex_only_reproducer_resolves_to_the_cache_copy(self):
        """Log 48 finding 1: w@m declared, installed only on Codex (config.toml enabled, cache m/w/1.0.0), AGENT_HOST=codex →
        the cache directory; today 'declared for this project but not installed for it here'."""
        env = self.c9_env("codex")
        cache = self.c9_codex_install(env, "m", "w", "1.0.0")
        out, err = self.c9_probe(self.c9_target(self.W_DECL), "w", env)
        self.assert_c9_root(out, err, cache, "codex-only")
        self.assertNotIn("note:", err, "the copy is the pin: no note")

    def test_C9_2_codex_only_check_runs_the_codex_copy_through_the_cli(self):
        """C9.2 as a session meets it: a check `{plugin:w}/tool.py` in a project declaring w@m, w installed only on Codex,
        AGENT_HOST=codex, the payload engine's init/add/run → the cache copy's tool runs and T1 is done."""
        self.need_payload()
        env = self.c9_env("codex")
        cache = self.c9_codex_install(env, "m", "w", "1.0.0")
        marker = os.path.join(self.tmp("chongdae-payload-marker-"), "ran.txt")
        write(os.path.join(cache, "tool.py"),
              "import os\nopen(%r, 'w').write(os.path.realpath(os.path.dirname(os.path.abspath(__file__))))\n" % marker)
        proj = self.tmp("chongdae-payload-project-")
        self.git(proj, env, "init", "-q")
        write(os.path.join(proj, "README.md"), "a fixture project\n")
        write(os.path.join(proj, "hunsu.json"), {"plugins": self.W_DECL})
        self.git(proj, env, "add", "-A")
        self.git(proj, env, "commit", "-qm", "base")
        d, said = self.l3_workflow(env, proj, "w")
        self.assertNotIn("not installed for it here", said)
        self.assertTrue(os.path.isfile(marker), "the tool never ran from the Codex cache: exit %s\n%s" % (d.returncode, said))
        with open(marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), os.path.realpath(cache))
        self.assertEqual(d.returncode, 0, said)
        self.assertIn("done T1", said)

    def test_C9_2_codex_host_never_takes_the_claude_copy(self):
        """C9.2: w@m installed only for Claude Code; AGENT_HOST=codex → no root, the reason says not installed here and names
        the host — never the other host's copy."""
        env = self.c9_env("codex")
        claude = self.c9_claude_install(env, "m", "w", "1.0.0")
        out, err = self.c9_probe(self.c9_target(self.W_DECL), "w", env)
        said = self.assert_c9_fails(out, err, "claude copy under codex", "not installed for it here", "codex")
        self.assertFalse(any(os.path.realpath(r) == os.path.realpath(claude) for r in out["roots"]))

    def test_C9_2_claude_only_install_still_resolves(self):
        """C9.2: w@m installed only for Claude Code (user scope), AGENT_HOST=claude-code or unset → its installPath."""
        for host in ("claude-code", None):
            env = self.c9_env(host)
            claude = self.c9_claude_install(env, "m", "w", "1.0.0")
            out, err = self.c9_probe(self.c9_target(self.W_DECL), "w", env)
            self.assert_c9_root(out, err, claude, ("claude-only", host))
            self.assertIn(os.path.realpath(PLUGINROOT), out["resolvers"], ("claude-only", host, "the vendored resolver is not what ran"))

    def test_C9_2_installed_on_both_hosts_resolves_to_the_selected_hosts_copy(self):
        """C9.2: w@m on both hosts → AGENT_HOST=codex gives the Codex cache copy; no AGENT_HOST (and claude-code) gives Claude's."""
        for host in ("codex", None, "claude-code"):
            env = self.c9_env(host)
            cache = self.c9_codex_install(env, "m", "w", "1.0.0")
            claude = self.c9_claude_install(env, "m", "w", "1.0.0")
            out, err = self.c9_probe(self.c9_target(self.W_DECL), "w", env)
            self.assert_c9_root(out, err, cache if host == "codex" else claude, ("both hosts", host))

    def test_C9_2_the_same_name_in_two_marketplaces(self):
        """C9.2: w in marketplaces m and n on the selected host → the declared one; undeclared → fails naming both."""
        for host in ("codex", "claude-code"):
            env = self.c9_env(host)
            install = self.c9_codex_install if host == "codex" else self.c9_claude_install
            in_m, in_n = install(env, "m", "w", "1.0.0"), install(env, "n", "w", "1.0.0")
            for market, want in (("m", in_m), ("n", in_n)):
                out, err = self.c9_probe(self.c9_target({"w": {"marketplace": market, "version": "1.0.0"}}), "w", env)
                self.assert_c9_root(out, err, want, (host, "declared", market))
            for plugins in ({"w": {"version": "1.0.0"}}, None):
                out, err = self.c9_probe(self.c9_target(plugins), "w", env)
                said = self.assert_c9_fails(out, err, (host, "undeclared", plugins), "m, n")
                self.assertIn("marketplace", said)
                self.assertIn(host, said, (host, "the reason names the host"))

    def test_C9_3_a_copy_off_the_pin_resolves_with_one_note_on_stderr(self):
        """C9.3: the Codex copy is 1.1.0, the pin 1.0.0 → the copy, and `note: <note>` on stderr exactly once in a process
        that resolves it twice; the same for a Claude copy."""
        for host in ("codex", "claude-code"):
            env = self.c9_env(host)
            root = (self.c9_codex_install if host == "codex" else self.c9_claude_install)(env, "m", "w", "1.1.0")
            out, err = self.c9_probe(self.c9_target(self.W_DECL), "w", env, calls=2)
            self.assert_c9_root(out, err, root, (host, "off the pin"))
            notes = [ln for ln in err.splitlines() if ln.startswith("note: ")]
            self.assertEqual(len(notes), 1, (host, err))
            self.assertIn("hunsu.json declares w 1.0.0", notes[0], host)
            self.assertIn("1.1.0", notes[0], host)
            self.assertIn(host, notes[0], host)

    def c9_note_texts(self, versions):
        notes = versions.get("notes")
        if isinstance(notes, dict):
            return [v for v in strings(notes)]
        if isinstance(notes, list):
            return list(strings(notes))
        return [] if notes is None else [str(notes)]

    def test_C9_3_plugin_versions_carries_the_note_without_machine_paths(self):
        """C9.3: plugin_versions(target, ["{plugin:w}/x"]) carries the off-pin note under `notes`, this machine's paths
        taken out; still one `note:` line on stderr for the process."""
        env = self.c9_env("codex")
        cache = self.c9_codex_install(env, "m", "w", "1.1.0")
        target = self.c9_target(self.W_DECL)
        out, err = self.c9_probe(target, "w", env, calls=1, versions=True)
        self.assert_c9_root(out, err, cache, "off the pin")
        texts = self.c9_note_texts(out["versions"])
        self.assertTrue(any("hunsu.json declares w 1.0.0" in t and "1.1.0" in t for t in texts), out["versions"])
        blob = json.dumps(out["versions"].get("notes"))
        for p in {cache, os.path.realpath(cache), env["HOME"], os.path.realpath(env["HOME"]), env["CODEX_HOME"], target}:
            self.assertNotIn(p, blob, ("a machine path in notes", p))
        self.assertEqual(len([ln for ln in err.splitlines() if ln.startswith("note: ")]), 1, err)

    def test_C9_3_no_note_when_the_copy_is_the_pin_or_the_call_names_another_plugin(self):
        """C9.3 control: a copy at the pin gives no note anywhere; an argv not naming the off-pin plugin carries none of its notes."""
        env = self.c9_env("codex")
        cache = self.c9_codex_install(env, "m", "w", "1.0.0")
        out, err = self.c9_probe(self.c9_target(self.W_DECL), "w", env, versions=True)
        self.assert_c9_root(out, err, cache, "at the pin")
        self.assertNotIn("note:", err)
        self.assertEqual(self.c9_note_texts(out["versions"]), [])
        self.assertEqual(out["versions"]["used"].get("w", "").split("+")[0], "1.0.0", out["versions"])
        env = self.c9_env("codex")
        self.c9_codex_install(env, "m", "w", "1.1.0")
        self.c9_codex_install(env, "m", "v", "1.0.0")
        target = self.c9_target({"w": {"marketplace": "m", "version": "1.0.0"}, "v": {"marketplace": "m", "version": "1.0.0"}})
        out, err = self.c9_probe(target, "v", env, versions=True)
        self.assertIsNone(out["error"], (out, err))
        self.assertFalse(any("declares w" in t for t in self.c9_note_texts(out["versions"])), out["versions"])
        self.assertNotIn("declares w", err)
        self.assertIn(os.path.realpath(PLUGINROOT), out["resolvers"], "the vendored resolver is not what ran")

    def test_C9_2_a_link_to_a_missing_directory_fails_with_its_reason(self):
        """C9.2: hunsu.local.json links w to a directory that does not exist → no root, the resolver's reason (link
        directory is missing, naming it) — no fallback to an install, even one at the pin."""
        for host in ("codex", "claude-code"):
            env = self.c9_env(host)
            (self.c9_codex_install if host == "codex" else self.c9_claude_install)(env, "m", "w", "1.0.0")
            gone = os.path.join(self.tmp("chongdae-payload-gone-"), "absent")
            out, err = self.c9_probe(self.c9_target(self.W_DECL, {"links": {"w": gone}}), "w", env)
            self.assert_c9_fails(out, err, (host, "missing link"), "link directory is missing", gone)

    def test_C9_2_a_link_wins_over_an_install_on_codex(self):
        """C9.2 order: a hunsu.local.json link for w first, before the Codex install."""
        env = self.c9_env("codex")
        self.c9_codex_install(env, "m", "w", "1.0.0")
        d = self.tmp("chongdae-payload-linked-")
        write(os.path.join(d, ".codex-plugin", "plugin.json"), {"name": "w", "version": "1.0.0"})
        out, err = self.c9_probe(self.c9_target(self.W_DECL, {"links": {"w": d}}), "w", env)
        self.assert_c9_root(out, err, d, "link first")
        self.assertIn(os.path.realpath(PLUGINROOT), out["resolvers"], "the vendored resolver is not what ran")

    def test_C9_1_the_shim_imports_the_vendored_module_not_a_sibling(self):
        """C9.1: the engine loaded through the root shim (the payload directory not on sys.path), with a decoy
        `pluginroot.py` first on PYTHONPATH, resolves the Codex-only reproducer through plugin/pluginroot.py."""
        decoy = self.tmp("chongdae-payload-decoy-")
        write(os.path.join(decoy, "pluginroot.py"), "raise ImportError('the decoy pluginroot was imported')\n")
        env = self.c9_env("codex", PYTHONPATH=decoy)
        cache = self.c9_codex_install(env, "m", "w", "1.0.0")
        out, err = self.c9_probe(self.c9_target(self.W_DECL), "w", env, where=REPO)
        self.assertEqual(out["engine"], os.path.realpath(os.path.join(PLUGIN, "chongdae.py")))
        self.assertEqual(out["resolvers"], [os.path.realpath(PLUGINROOT)], (out, err))
        self.assert_c9_root(out, err, cache, "through the shim")

    def test_C9_1_the_shim_cli_resolves_through_the_vendored_module(self):
        """C9.1: `python3 <repo>/chongdae.py --help` loads plugin/pluginroot.py (and nothing named pluginroot elsewhere),
        and a run started through the shim resolves a Codex-only `{plugin:w}`."""
        self.need_payload()
        decoy = self.tmp("chongdae-payload-decoy-")
        write(os.path.join(decoy, "pluginroot.py"), "raise ImportError('the decoy pluginroot was imported')\n")
        env = self.c9_env("codex", PYTHONPATH=decoy)
        cache = self.c9_codex_install(env, "m", "w", "1.0.0")
        shim = os.path.join(REPO, "chongdae.py")
        spy = os.path.join(self.tmp(), "spy.py")
        log = os.path.join(self.tmp(), "spy.json")
        write(spy, "import json, os, runpy, sys\nLOG, SHIM = sys.argv[1], sys.argv[2]\nsys.argv = [SHIM] + sys.argv[3:]\n"
                   "sys.path[0] = os.path.dirname(SHIM)\ncode = 0\n"
                   "try:\n    runpy.run_path(SHIM, run_name='__main__')\n"
                   "except SystemExit as e:\n    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)\n"
                   "finally:\n    json.dump(sorted({os.path.realpath(m.__file__) for m in list(sys.modules.values()) if getattr(m, '__file__', None)"
                   " and os.path.basename(m.__file__).startswith('pluginroot')}), open(LOG, 'w'))\nsys.exit(code)\n")
        d = self.sh([sys.executable, spy, log, shim, "--help"], self.tmp(), env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertEqual(load(log), [os.path.realpath(PLUGINROOT)], "--help through the shim")
        proj = self.tmp("chongdae-payload-project-")
        self.git(proj, env, "init", "-q")
        write(os.path.join(proj, "README.md"), "a fixture project\n")
        write(os.path.join(proj, "hunsu.json"), {"plugins": self.W_DECL})
        self.git(proj, env, "add", "-A")
        self.git(proj, env, "commit", "-qm", "base")
        marker = os.path.join(self.tmp("chongdae-payload-marker-"), "ran.txt")
        write(os.path.join(cache, "tool.py"), "open(%r, 'w').write('ran')\n" % marker)
        said = ""
        for args in (["init", "--session", "--goal", "through the shim on codex"],
                     ["add", "T1", "--check", "%s {plugin:w}/tool.py" % shlex.quote(sys.executable)]):
            d = self.sh([sys.executable, shim] + args, proj, env)
            said += d.stdout + d.stderr
            self.assertEqual(d.returncode, 0, said)
        write(os.path.join(proj, "work.txt"), "the work of T1\n")
        for _ in range(15):
            d = self.sh([sys.executable, spy, log, shim, "run"], proj, env)
            said += d.stdout + d.stderr
            if d.returncode != 4:
                break
        self.assertNotIn("not installed for it here", said)
        self.assertTrue(os.path.isfile(marker), "the shim's run never ran the Codex copy: exit %s\n%s" % (d.returncode, said))
        self.assertEqual(d.returncode, 0, said)
        self.assertIn("done T1", said)
        self.assertEqual(load(log), [os.path.realpath(PLUGINROOT)], "run through the shim")

    C9_WRAPPER_PROBE = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import chongdae
m, kind = sys.argv[2], sys.argv[3]
mods = [x for x in list(sys.modules.values()) if getattr(x, "__file__", None)
        and os.path.realpath(x.__file__) == os.path.realpath(os.path.join(sys.argv[1], "pluginroot.py"))]
out = {"resolver": bool(mods)}
if mods:
    pr = mods[0]
    sentinel = os.path.join(m, "SENTINEL")
    calls = []
    def fake(directory, name, errors=None):
        calls.append([directory, name])
        return sentinel
    if kind == "sentinel":
        pr.in_place = fake
        pr.catalog_source = fake
    out["calls"] = calls
out["checkout"] = {n: chongdae.checkout_root(m, n) for n in ("probe", "sub/probe", "absent")}
out["catalog_root"] = hasattr(chongdae, "catalog_root")
if out["catalog_root"] and kind == "sentinel":
    out["catalog"] = chongdae.catalog_root(m, "probe")
sys.stdout.write(json.dumps(out))
'''

    def test_C9_4_checkout_root_is_the_resolvers_in_place_then_the_legacy_child(self):
        """C9.4: checkout_root(root, name) is a thin wrapper — whatever the resolver's in_place returns wins (a sentinel
        stands in for it); with in_place giving nothing, the one-component child that is a directory, else None; and
        catalog_root is gone or only a call into the resolver."""
        self.need_payload()
        m = os.path.join(self.tmp("chongdae-payload-folder-"), "M")
        os.makedirs(os.path.join(m, "probe"))
        os.makedirs(os.path.join(m, "sub", "probe"))
        env = self.env()
        d = self.sh([sys.executable, "-c", self.C9_WRAPPER_PROBE, PLUGIN, m, "sentinel"], self.tmp(), env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        out = json.loads(d.stdout)
        self.assertTrue(out["resolver"], "the engine did not load plugin/pluginroot.py")
        self.assertEqual(out["checkout"]["probe"], os.path.join(m, "SENTINEL"), out)
        if out["catalog_root"]:
            self.assertEqual(out["catalog"], os.path.join(m, "SENTINEL"), "catalog_root kept its own catalog reading")
        d = self.sh([sys.executable, "-c", self.C9_WRAPPER_PROBE, PLUGIN, m, "real"], self.tmp(), env)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        out = json.loads(d.stdout)
        self.assertEqual(out["checkout"], {"probe": os.path.join(m, "probe"), "sub/probe": None, "absent": None}, out)

    def test_C9_4_an_escaping_child_with_a_manifest_outside_is_still_taken_as_named(self):
        """C9.4/M1 through the resolver: outside/plugin holds a manifest naming probe, every escape style and catalog kind,
        a link and a directory marketplace on either host → M/probe; and the resolver is what ran."""
        for how, resolve in self.raw_resolvers():
            for style, label, cats in self.m1_cases(("relative", "absolute", "dotdot", "chain")):
                env = self.env()
                box = {}
                m, got = resolve(env, lambda m, style=style, cats=cats: box.update(outside=self.m1_escape(m, style, cats)))
                self.assertTrue(os.path.isfile(os.path.join(box["outside"], "plugin", ".claude-plugin", "plugin.json")))
                self.assert_m1_legacy(m, box["outside"], got, (how, style, label))
        m = os.path.join(self.tmp("chongdae-payload-linked-"), "M")
        os.makedirs(m)
        self.m1_escape(m, "relative", self.M1_CATALOGS)
        out, err = self.c9_probe(self.c9_target(None, {"links": {"probe": m}}), "probe", self.c9_env("codex"))
        self.assertEqual(out["roots"], [os.path.join(m, "probe")], (out, err))
        self.assertIn(os.path.realpath(PLUGINROOT), out["resolvers"], "the vendored resolver is not what ran")

    def test_C9_5_the_documents_stop_sending_codex_only_installs_to_links(self):
        """C9.5: README's host entry points and Limits, and SELFHOSTING's observed limits, no longer say Codex-only installs
        need local links; README names plugin/pluginroot.py as the family's shared file, vendored byte-identical."""
        with open(os.path.join(PLUGIN, "README.md"), encoding="utf-8") as fh:
            readme = re.sub(r"\s+", " ", fh.read())
        with open(os.path.join(REPO, "SELFHOSTING.md"), encoding="utf-8") as fh:
            selfhosting = re.sub(r"\s+", " ", fh.read())
        for stale in ("Codex-only installations need local links", "installed only in Codex, provide their actual roots",
                      "does not switch plugin-path lookup to the Codex registry"):
            self.assertNotIn(stale, readme)
        self.assertNotIn("Codex-only installs need", selfhosting)
        self.assertIn("pluginroot.py", readme)
        self.assertRegex(readme, r"(?i)byte-identical")
        self.assertIn("pluginroot.py", re.search(r"## Limits(.*?)(## |$)", readme).group(1)
                      + re.search(r"## Shared instructions and host entry points(.*?)## ", readme).group(1))

    # ---------- K7 version ----------

    def test_k7_five_version_fields_agree_on_a_minor_release(self):
        self.need_payload()
        cat = load(os.path.join(REPO, ".claude-plugin", "marketplace.json"))
        versions = [cat["metadata"]["version"], chongdae_entry(cat)["version"]]
        for m in MANIFESTS:
            data = load(os.path.join(PLUGIN, m))
            self.assertEqual(data["name"], "chongdae", m)
            self.assertEqual(data["engines"]["python"], ">=3.11", m)
            versions.append(data["version"])
        self.assertEqual(len(set(versions)), 1, versions)
        parts = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", versions[0])
        self.assertTrue(parts, versions[0])
        nums = tuple(int(x) for x in parts.groups())
        self.assertEqual(nums[0], 2)
        self.assertGreater(nums, (2, 0, 0))

    # ---------- K8 the root tests test the payload ----------

    def test_k8_root_suites_load_the_payload(self):
        self.need_payload()
        script = ("import json, os, sys\nsys.argv = ['probe']\nimport test_chongdae, test_concurrency\n"
                  "print(json.dumps([os.path.realpath(test_chongdae.chongdae.__file__), os.path.realpath(str(test_concurrency.ENGINE)),"
                  " os.path.realpath(test_concurrency.chongdae.__file__)]))\n")
        d = self.sh([sys.executable, "-c", script], REPO, self.env())
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertEqual(json.loads(d.stdout.strip().splitlines()[-1]), [os.path.realpath(os.path.join(PLUGIN, "chongdae.py"))] * 3)
        with open(os.path.join(REPO, "test_chongdae.py"), encoding="utf-8") as fh:
            src = fh.read()
        names = re.search(r"loadTestsFromNames\(\[(.*?)\]\)", src, re.S)
        self.assertTrue(names and '"test_payload"' in names.group(1))


if __name__ == "__main__":
    unittest.main()
