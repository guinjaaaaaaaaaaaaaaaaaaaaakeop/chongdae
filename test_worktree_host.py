"""C8: a new worktree brings the main tree's ignored host configuration.

A git project whose committed .gitignore lists `.codex/hooks.json`, `.claude/settings.local.json` and `hunsu.local.json`.
Main has those two host files (ignored), a committed `.claude/settings.json` whose working copy is then modified, and an
untracked, not ignored `.codex/config.toml`. `init --session --worktree` must copy the ignored ones byte-for-byte, leave
the tracked one to the checkout, refuse the untracked one with a line, name what it copied, and the landing must not
commit a copied file.
"""
import os
import re
import subprocess
import unittest

from test_chongdae import Project, run, write
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
HOST_PATHS = (".codex/hooks.json", ".codex/config.toml", ".claude/settings.json", ".claude/settings.local.json")

HOOKS = '{"hooks": {"PreToolUse": [{"command": "/opt/abs/path/to/pre_write.py --flag"}]}}\n'
LOCAL = '{"permissions": {"allow": ["Bash(ls:*)"]}, "note": "local settings \\u00e9"}\n'
SETTINGS_COMMITTED = '{"committed": true}\n'
SETTINGS_MODIFIED = '{"committed": false, "modified in main": 1}\n'
CONFIG_TOML = 'model = "x"\n'


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                          capture_output=True, text=True)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def host_project(pj):
    """The fixture of the brief, in Project `pj`."""
    git(pj.dir, "config", "user.email", "t@t")
    git(pj.dir, "config", "user.name", "t")
    write(os.path.join(pj.dir, ".gitignore"), ".codex/hooks.json\n.claude/settings.local.json\nhunsu.local.json\n")
    write(os.path.join(pj.dir, "a.txt"), "base\n")
    write(os.path.join(pj.dir, ".claude", "settings.json"), SETTINGS_COMMITTED)
    git(pj.dir, "add", "-A")
    r = git(pj.dir, "commit", "-qm", "base")
    assert r.returncode == 0, r.stderr
    write(os.path.join(pj.dir, ".codex", "hooks.json"), HOOKS)
    write(os.path.join(pj.dir, ".claude", "settings.local.json"), LOCAL)
    write(os.path.join(pj.dir, ".claude", "settings.json"), SETTINGS_MODIFIED)   # uncommitted change in main
    write(os.path.join(pj.dir, ".codex", "config.toml"), CONFIG_TOML)              # untracked, not ignored
    # the fixture is what the brief says it is
    assert git(pj.dir, "check-ignore", "-q", ".codex/hooks.json").returncode == 0
    assert git(pj.dir, "check-ignore", "-q", ".claude/settings.local.json").returncode == 0
    assert git(pj.dir, "check-ignore", "-q", ".codex/config.toml").returncode != 0
    assert ".codex/config.toml" in git(pj.dir, "status", "--porcelain", "-uall").stdout


def init_worktree(tc, pj):
    code, out = run("init", "--session", "--worktree", "--goal", "g", "--target", pj.dir)
    tc.assertEqual(code, 0, out)
    m = re.search(r"^worktree (\S+) \(branch ", out, re.M)
    tc.assertTrue(m, "init's output names the worktree:\n%s" % out)
    wt = m.group(1)
    tc.assertTrue(os.path.isdir(wt), wt)
    # the run's record lives in the worktree until it lands; its state names the worktree's main and branch
    st = c.load_state(c.run_dir(wt))
    tc.assertEqual(os.path.realpath((st.get("worktree") or {}).get("main", "")), os.path.realpath(pj.dir), st)
    return wt, out


def copy_lines(out):
    """The lines of init's output that name a host file."""
    return [ln for ln in out.splitlines() if any(p in ln for p in HOST_PATHS)]


class WorktreeHostFiles(unittest.TestCase):

    def test_C8_1_ignored_host_files_are_copied_byte_equal(self):
        with Project() as pj:
            host_project(pj)
            wt, out = init_worktree(self, pj)
            for rel in (".codex/hooks.json", ".claude/settings.local.json"):
                dst = os.path.join(wt, rel)
                self.assertTrue(os.path.isfile(dst), "%s is copied into the worktree; init said:\n%s" % (rel, out))
                self.assertEqual(read_bytes(dst), read_bytes(os.path.join(pj.dir, rel)),
                                 "%s is byte-for-byte main's (paths in it included)" % rel)
            # the hooks file names an absolute path: it is copied as is, not rewritten for the worktree
            self.assertIn("/opt/abs/path/to/pre_write.py", read_bytes(os.path.join(wt, ".codex/hooks.json")).decode())

    def test_C8_1_one_named_constant_lists_the_two_hosts_paths(self):
        found = [name for name, val in vars(c).items()
                 if name.isupper() and isinstance(val, (tuple, list, frozenset, set))
                 and all(isinstance(v, str) for v in val)
                 and set(val) == set(HOST_PATHS) and len(val) == len(HOST_PATHS)]
        self.assertTrue(found, "one named constant in chongdae holds exactly the four host configuration paths %r"
                        % (HOST_PATHS,))

    def test_C8_2_a_tracked_host_file_comes_from_the_branch_not_main(self):
        with Project() as pj:
            host_project(pj)
            wt, out = init_worktree(self, pj)
            # the copy happened (else this test decides nothing about "never overwritten")
            self.assertTrue(os.path.isfile(os.path.join(wt, ".codex", "hooks.json")),
                            "the ignored host files are copied; init said:\n%s" % out)
            self.assertEqual(read_bytes(os.path.join(wt, ".claude", "settings.json")), SETTINGS_COMMITTED.encode(),
                             "the tracked .claude/settings.json is the committed content, not main's modified copy")
            self.assertEqual(git(wt, "status", "--porcelain", "--", ".claude/settings.json").stdout.strip(), "",
                             "the worktree's tracked settings.json is unmodified")

    def test_C8_2_an_untracked_not_ignored_host_file_is_not_copied_and_init_says_so(self):
        with Project() as pj:
            host_project(pj)
            wt, out = init_worktree(self, pj)
            self.assertFalse(os.path.exists(os.path.join(wt, ".codex", "config.toml")),
                             "an untracked, not ignored host file is not copied")
            named = [ln for ln in out.splitlines() if ".codex/config.toml" in ln]
            self.assertEqual(len(named), 1, "one line of init's output names .codex/config.toml:\n%s" % out)
            self.assertRegex(named[0].lower(), r"untracked|not ignored|ignore",
                             "the line says why (untracked, not ignored): %r" % named[0])

    def test_C8_3_init_prints_the_copied_files_in_one_line(self):
        with Project() as pj:
            host_project(pj)
            wt, out = init_worktree(self, pj)
            both = [ln for ln in out.splitlines()
                    if ".codex/hooks.json" in ln and ".claude/settings.local.json" in ln]
            self.assertEqual(len(both), 1, "one line names both copied host files:\n%s" % out)
            self.assertNotRegex(both[0], r"\.claude/settings\.json",
                                "the tracked settings.json was not copied and is not named as copied: %r" % both[0])

    def test_C8_3_a_copied_file_stays_out_of_the_landing(self):
        with Project() as pj:
            host_project(pj)
            wt, out = init_worktree(self, pj)
            for rel in (".codex/hooks.json", ".claude/settings.local.json"):
                self.assertTrue(os.path.isfile(os.path.join(wt, rel)), "%s copied; init said:\n%s" % (rel, out))
                self.assertEqual(git(wt, "check-ignore", "-q", rel).returncode, 0, "%s is ignored in the worktree" % rel)
            self.assertNotIn(".codex/hooks.json", git(wt, "status", "--porcelain", "-uall").stdout)
            self.assertNotIn(".claude/settings.local.json", git(wt, "status", "--porcelain", "-uall").stdout)
            # the landing merges into a clean main: put main's own tracked/untracked fixture changes away (its ignored
            # host files stay — they are what was copied, and git status does not see them)
            self.assertEqual(git(pj.dir, "checkout", "--", ".claude/settings.json").returncode, 0)
            os.remove(os.path.join(pj.dir, ".codex", "config.toml"))
            code, out = run("close", "--target", wt)
            self.assertEqual(code, 0, out)
            self.assertIn("merged", out)
            st = pj.state()
            merge = (st.get("landed") or {}).get("commit")
            self.assertTrue(merge, "the run landed: %r\n%s" % (st.get("landed"), out))
            files = git(pj.dir, "ls-tree", "-r", "--name-only", merge).stdout.splitlines()
            head_files = git(pj.dir, "ls-tree", "-r", "--name-only", "HEAD").stdout.splitlines()
            for rel in (".codex/hooks.json", ".claude/settings.local.json", ".codex/config.toml"):
                self.assertNotIn(rel, files, "the merge commit does not contain %s" % rel)
                self.assertNotIn(rel, head_files, "main's HEAD does not contain %s" % rel)
            # main's own copies are untouched by the landing
            self.assertEqual(read_bytes(os.path.join(pj.dir, ".codex", "hooks.json")), HOOKS.encode())
            self.assertEqual(read_bytes(os.path.join(pj.dir, ".claude", "settings.local.json")), LOCAL.encode())

    def test_C8_3_no_host_files_no_copy_line(self):
        with Project() as pj:
            git(pj.dir, "config", "user.email", "t@t")
            git(pj.dir, "config", "user.name", "t")
            write(os.path.join(pj.dir, ".gitignore"), ".codex/hooks.json\n.claude/settings.local.json\nhunsu.local.json\n")
            write(os.path.join(pj.dir, "a.txt"), "base\n")
            git(pj.dir, "add", "-A")
            self.assertEqual(git(pj.dir, "commit", "-qm", "base").returncode, 0)
            wt, out = init_worktree(self, pj)
            self.assertEqual(copy_lines(out), [], "no host file, no line about host files:\n%s" % out)
            self.assertNotRegex(out.lower(), r"\bcop(y|ied)\b.*(host|\.codex|\.claude)",
                                "no copy line when nothing was copied:\n%s" % out)
            for rel in HOST_PATHS:
                self.assertFalse(os.path.exists(os.path.join(wt, rel)), "%s does not appear in the worktree" % rel)


def readme_section(text, heading):
    m = re.search(r"^## %s\b.*?$(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    return m.group(1) if m else ""


class WorktreeHostReadme(unittest.TestCase):

    def test_C8_4_readme_runs_and_limits_name_what_a_worktree_gets(self):
        with open(os.path.join(HERE, "plugin", "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        for heading in ("Runs", "Limits"):
            sec = readme_section(text, heading)
            self.assertTrue(sec, "plugin/README.md has a %s section" % heading)
            for name in ("hunsu.local.json",) + HOST_PATHS:
                self.assertIn(name, sec, "the %s section names %s among what a worktree gets" % (heading, name))
            self.assertRegex(sec.lower(), r"worktree", "the %s section speaks of the worktree" % heading)


if __name__ == "__main__":
    unittest.main()
