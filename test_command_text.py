"""Contract B: commands are read as commands, and a check runs as it was given.

The Bash hook matched operation patterns against text — heredoc bodies, quoted commit messages, a quoted --brief — and told
the session an operation was running outside `did` when none was. A check's inline program had a home path inside it
rewritten into a placeholder in the public record, so another clone ran a different program; a placeholder swallowed a
closing bracket; and a check with an unbalanced quote ended in a traceback.

  python -m unittest test_command_text
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_chongdae import Project, run, write, UNCOMMITTED  # noqa: F401  (puts plugin/ on sys.path)
import chongdae as c

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(HERE, "plugin")
ENGINE = os.path.join(PLUGIN, "chongdae.py")
PRE_BASH = os.path.join(PLUGIN, "hooks", "pre_bash.py")
README = os.path.join(PLUGIN, "README.md")

# the five shapes of text the hook took for commands (B1.1)
HEREDOC_PLAN = "cat >> plan.md <<'EOF'\nthen npm run deploy:write\nEOF"
COMMIT_MESSAGE = "git commit -m 'note: git push origin main went through'"
COMMIT_MESSAGE_LINES = "git commit -m 'note:\ngit push origin main\nwent through'"
HEREDOC_PROGRAM = "python3 - <<'PY'\nprint(\"git push origin main\")\nPY"
QUOTED_BRIEF = 'python3 chongdae.py add fix --brief "after npm run deploy the site"'
ECHOED = 'echo "wrangler deploy"'

# commands that are operations, matched as today (B1.2)
OPERATIONS = [
    "git push origin main",
    "npm run deploy",
    "cd app && npm run deploy",
    "FOO=1 npm run deploy",
    "git commit -m x; git push",
    "cat > notes.txt <<EOF\nsome text\nEOF\ngit push",
    'bash -c "git push origin main"',
    "wrangler deploy",
]

PROGRAM = ('import os,sys; sys.exit(0 if os.path.isdir(os.path.expanduser("~/.claude/plugins/cache/")) else 1)')
CHECK_TEXT = 'python3 -c "%s"' % PROGRAM.replace('"', '\\"')
UNBALANCED = 'python3 -c "print(1'
PASS_CHECK = "python3 -c pass"


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def cli(*argv):
    """The engine's main in-process, stdout and stderr both captured; an exception other than SystemExit is reported as
    (None, its traceback text) so a test fails by assertion rather than erroring."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = c.main(list(argv))
        except SystemExit as err:
            code = err.code if isinstance(err.code, int) else 1
            out.write(str(err) + "\n")
        except Exception as err:  # noqa: BLE001 — the defect itself: a raise is what the contract forbids
            import traceback
            out.write("Traceback (most recent call last):\n" + traceback.format_exc() + "\n")
            out.write("%s: %s\n" % (type(err).__name__, err))
            code = None
    return code, out.getvalue()


def operation(target, command):
    """c.bash_operation, with a raise turned into a value a test can assert on."""
    try:
        return c.bash_operation(target, command)
    except Exception as err:  # noqa: BLE001
        return ("raised", repr(err))


def hook(payload):
    env = dict(os.environ)
    env.pop("AGENT_WORKER", None)
    done = subprocess.run([sys.executable, PRE_BASH], input=json.dumps(payload), capture_output=True, text=True,
                          encoding="utf-8", env=env)
    return done.returncode, done.stdout + done.stderr


def paragraphs(path):
    with io.open(path, encoding="utf-8") as fh:
        return [p for p in fh.read().split("\n\n") if p.strip()]


class B1BashOperation(unittest.TestCase):
    """bash_operation reads command words, not text (a temporary project with no settings)."""

    def setUp(self):
        self.target = tempfile.mkdtemp(prefix="chongdae-cmdtext-")
        self.addCleanup(shutil.rmtree, self.target, True)

    def assertNoOperation(self, command):
        self.assertIsNone(operation(self.target, command), "text, not a command: %r" % command)

    def test_B1_1_heredoc_body_appended_to_a_plan_is_text(self):
        self.assertNoOperation(HEREDOC_PLAN)

    def test_B1_1_quoted_commit_message_is_text(self):
        self.assertNoOperation(COMMIT_MESSAGE)

    def test_B1_1_quoted_commit_message_spanning_three_lines_is_text(self):
        self.assertNoOperation(COMMIT_MESSAGE_LINES)

    def test_B1_1_heredoc_python_program_body_is_text(self):
        self.assertNoOperation(HEREDOC_PROGRAM)

    def test_B1_1_quoted_brief_argument_is_text(self):
        self.assertNoOperation(QUOTED_BRIEF)

    def test_B1_1_echoed_double_quoted_argument_is_text(self):
        self.assertNoOperation(ECHOED)

    def test_B1_1_dash_heredoc_with_tab_indented_terminator_is_text(self):
        self.assertNoOperation("cat > a.txt <<-EOF\n\tgit push origin main\n\tEOF")

    def test_B1_1_double_quoted_heredoc_word_is_text(self):
        self.assertNoOperation('cat > a.txt <<"END"\nnpm run deploy\nEND')

    def test_B1_1_ansi_c_quoted_argument_is_text(self):
        self.assertNoOperation("printf $'git push origin main\\n'")

    def test_B1_1_semicolon_inside_quotes_does_not_start_a_command(self):
        self.assertNoOperation("git commit -m 'done; git push origin main'")

    def test_B1_1_unbalanced_quote_does_not_raise(self):
        for command in ("echo 'abc", 'git commit -m "half', "git push origin main; echo 'abc", "cat <<'EOF\nx"):
            got = operation(self.target, command)
            self.assertFalse(isinstance(got, tuple) and got and got[0] == "raised", (command, got))

    def test_B1_2_operations_are_still_matched(self):
        for command in OPERATIONS:
            self.assertTrue(operation(self.target, command), "an operation, matched as today: %r" % command)

    def test_B1_2_command_after_heredoc_terminator_matched_while_body_is_not(self):
        # the body says npm run deploy (text); the line after the terminator is the command
        got = operation(self.target, "cat > a.txt <<EOF\nnpm run deploy\nEOF\ngit push")
        self.assertTrue(got, got)
        self.assertIn("git push", got)
        self.assertNotIn("deploy", got)

    def test_B1_1_bash_c_argument_read_as_a_command_line(self):
        for command in ('bash -c "git push origin main"', "sh -c 'npm run deploy'", 'zsh -c "git push"', "eval 'git push'"):
            self.assertTrue(operation(self.target, command), "the argument runs as a shell line: %r" % command)

    def test_B1_2_did_segment_is_the_record_itself(self):
        self.assertIsNone(operation(self.target, "python3 chongdae.py did t --why w -- git push"))

    def test_B1_2_after_close_on_the_same_line(self):
        self.assertTrue(c.after_close(self.target, "python3 chongdae.py close; git push"))

    def test_B1_2_after_close_not_read_in_a_heredoc_body(self):
        try:
            got = c.after_close(self.target, "cat >> notes.md <<'EOF'\nthen chongdae close\nthen git push\nEOF")
        except Exception as err:  # noqa: BLE001
            self.fail("after_close raised: %r" % err)
        self.assertFalse(got, "a heredoc body that mentions close and push is text")


class B1Hook(unittest.TestCase):
    """pre_bash.py as a subprocess in a project with a session run in progress."""

    def setUp(self):
        self.pj = Project()
        self.addCleanup(self.pj.__exit__)
        git(self.pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        code, out = run("init", "--session", "--goal", "g", "--target", self.pj.dir)
        assert code == 0, out
        code, out = run("add", "ops", "--why", "a test task: no check decides it", "--brief", "b", "--target", self.pj.dir)
        assert code == 0, out

    def fire(self, command):
        return hook({"cwd": self.pj.dir, "tool_name": "Bash", "tool_input": {"command": command}})

    def assertSilent(self, command):
        self.assertEqual(self.fire(command), (0, ""), "text, not a command: %r" % command)

    def test_B1_3_hook_silent_on_heredoc_plan_body(self):
        self.assertSilent(HEREDOC_PLAN)

    def test_B1_3_hook_silent_on_quoted_commit_message(self):
        self.assertSilent(COMMIT_MESSAGE)
        self.assertSilent(COMMIT_MESSAGE_LINES)

    def test_B1_3_hook_silent_on_heredoc_program(self):
        self.assertSilent(HEREDOC_PROGRAM)

    def test_B1_3_hook_silent_on_quoted_brief(self):
        self.assertSilent(QUOTED_BRIEF)

    def test_B1_3_hook_names_did_for_a_push(self):
        code, out = self.fire("git push origin main")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.strip(), "a push while a run is in progress gets its line")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("did TASK", ctx)

    def test_B1_3_hook_never_fails_on_an_unbalanced_quote(self):
        code, out = self.fire("git commit -m \"half; git push origin main")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)


class B2Portable(unittest.TestCase):
    """portable_argv and neutral_path: paths are rewritten where an argument begins with one; no bracket is swallowed."""

    def setUp(self):
        self.home = os.path.expanduser("~")
        self.cache = self.home + "/.claude/plugins/cache/m/mangsang/2.4.0"
        self.target = tempfile.mkdtemp(prefix="chongdae-cmdtext-")
        self.addCleanup(shutil.rmtree, self.target, True)

    def test_B2_1_portable_argv_keeps_an_inline_program_unchanged(self):
        argv = ["python3", "-c", "print('(~/.claude/plugins/cache/m/mangsang/2.4.0)')"]
        self.assertEqual(c.portable_argv(list(argv)), argv)

    def test_B2_1_portable_argv_keeps_an_inline_program_with_an_expanduser_call(self):
        argv = ["python3", "-c", PROGRAM]
        self.assertEqual(c.portable_argv(list(argv)), argv)

    def test_B2_2_portable_argv_still_rewrites_a_plugin_path_argument(self):
        self.assertEqual(c.portable_argv([self.cache + "/mangsang.py"]), ["{plugin:mangsang}/mangsang.py"])

    def test_B2_2_neutral_path_keeps_a_closing_parenthesis(self):
        self.assertEqual(c.neutral_path("(" + self.cache + ")", self.target), "(<plugin:mangsang@2.4.0>)")

    def test_B2_2_neutral_path_keeps_a_closing_bracket(self):
        self.assertEqual(c.neutral_path("[" + self.cache + "]", self.target), "[<plugin:mangsang@2.4.0>]")

    def test_B2_2_neutral_path_keeps_a_trailing_comma(self):
        self.assertEqual(c.neutral_path("(" + self.cache + "),", self.target), "(<plugin:mangsang@2.4.0>),")
        self.assertEqual(c.neutral_path("[" + self.cache + "],", self.target), "[<plugin:mangsang@2.4.0>],")

    def test_B2_2_neutral_path_tilde_form_keeps_the_bracket(self):
        self.assertEqual(c.neutral_path("[~/.claude/plugins/cache/m/mangsang/2.4.0]", self.target), "[<plugin:mangsang@2.4.0>]")

    def test_B2_2_no_path_segment_takes_in_punctuation_or_a_backtick(self):
        for after in (",", ";", "`", ")", "]"):
            self.assertEqual(c.neutral_path("x " + self.cache + after + " y", self.target), "x <plugin:mangsang@2.4.0>" + after + " y", after)
        self.assertEqual(c.neutral_path("`" + self.cache + "`", self.target), "`<plugin:mangsang@2.4.0>`")


class B2CheckAsGiven(unittest.TestCase):
    """The engine as a subprocess with HOME a temporary directory that holds .claude/plugins/cache/."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="chongdae-cmdtext-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        os.makedirs(os.path.join(self.home, ".claude", "plugins", "cache"))
        self.proj = os.path.join(self.base, "project")
        os.makedirs(self.proj)
        self.env = dict(os.environ, HOME=self.home, CHONGDAE_SESSION="parent", CHONGDAE_USER="test", CHONGDAE_WAIT="20",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
                        GIT_COMMITTER_EMAIL="t@example.invalid")
        self.env.pop("AGENT_WORKER", None)
        for a in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.invalid"],
                  ["commit", "-q", "--allow-empty", "-m", "base"]):
            subprocess.run(["git", *a], cwd=self.proj, check=True, capture_output=True, env=self.env)
        code, out = self.engine("init", "--session", "--goal", "g")
        assert code == 0, out

    def engine(self, *argv):
        done = subprocess.run([sys.executable, ENGINE, *argv, "--target", self.proj], capture_output=True, text=True,
                              encoding="utf-8", env=self.env, cwd=self.proj)
        return done.returncode, done.stdout + done.stderr

    def run_dir(self):
        runs = [os.path.join(self.proj, ".chongdae", n) for n in os.listdir(os.path.join(self.proj, ".chongdae"))
                if n.startswith("run-")]
        self.assertEqual(len(runs), 1, runs)
        return runs[0]

    def public_task(self, tid):
        path = os.path.join(self.run_dir(), "tasks", tid + ".json")
        self.assertTrue(os.path.isfile(path), path)
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
        return json.loads(text), text

    def assertCheckAsGiven(self, task, text):
        self.assertIn("def", task)
        checks = task["def"].get("checks") or []
        self.assertTrue(checks and len(checks[0]) == 3, checks)
        self.assertEqual(checks[0][2], PROGRAM, "the inline program is kept as given in the public record")
        self.assertNotIn("<claude-plugins>", text)

    def test_B2_1_inline_program_kept_in_def_checks_and_another_clone_passes(self):
        code, out = self.engine("add", "T", "--role", "session", "--why", "w", "--check", CHECK_TEXT)
        self.assertEqual(code, 0, out)
        task, text = self.public_task("T")
        self.assertCheckAsGiven(task, text)
        write(os.path.join(self.proj, "work.txt"), "changed\n")
        overlay = os.path.join(self.run_dir(), "local", "tasks", "T.json")
        if os.path.exists(overlay):
            os.remove(overlay)   # another clone's view: this machine's overlay is not there
        code, out = self.engine("run", "T")
        self.assertEqual(code, 0, out)
        state = c.load_state(self.run_dir())
        self.assertEqual(((state.get("tasks") or {}).get("T") or {}).get("status"), "done", out)

    def test_B2_1_inline_program_kept_when_attached_to_an_open_task(self):
        code, out = self.engine("add", "T", "--brief", "b", "--why", "nothing to check yet")
        self.assertEqual(code, 0, out)
        code, out = self.engine("add", "T", "--check", CHECK_TEXT)
        self.assertEqual(code, 0, out)
        task, text = self.public_task("T")
        self.assertCheckAsGiven(task, text)

    def test_B2_1_inline_program_kept_through_amend(self):
        code, out = self.engine("add", "T", "--check", PASS_CHECK)
        self.assertEqual(code, 0, out)
        code, out = self.engine("amend", "T", "--check", CHECK_TEXT, "--why", "the check was too weak")
        self.assertEqual(code, 0, out)
        task, text = self.public_task("T")
        self.assertCheckAsGiven(task, text)


class B2Unparsable(unittest.TestCase):
    """A check text that does not split into words is a usage error, not a traceback."""

    def setUp(self):
        self.pj = Project()
        self.addCleanup(self.pj.__exit__)
        git(self.pj.dir, "commit", "-q", "--allow-empty", "-m", "base")
        code, out = run("init", "--session", "--goal", "g", "--target", self.pj.dir)
        assert code == 0, out

    def assertUsageError(self, code, out):
        self.assertNotIn("Traceback", out)
        self.assertIsNotNone(code, out)
        self.assertNotEqual(code, 0, out)
        self.assertIn("--check", out)
        self.assertIn("print(1", out, "the message names the text")
        self.assertTrue("does not parse" in out or "No closing quotation" in out, out)

    def checks_of(self, tid):
        return ((self.pj.state().get("tasks") or {}).get(tid) or {}).get("def", {}).get("checks")

    def test_B2_3_add_new_task_with_unbalanced_check_is_a_usage_error(self):
        code, out = cli("add", "T", "--check", UNBALANCED, "--target", self.pj.dir)
        self.assertUsageError(code, out)
        self.assertNotIn("T", self.pj.state().get("tasks") or {}, "no task is created")

    def test_B2_3_check_attached_to_an_open_task_unbalanced_is_a_usage_error(self):
        code, out = run("add", "T", "--check", PASS_CHECK, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        before = self.checks_of("T")
        code, out = cli("add", "T", "--check", UNBALANCED, "--target", self.pj.dir)
        self.assertUsageError(code, out)
        self.assertEqual(self.checks_of("T"), before, "the task's checks are unchanged")

    def test_B2_3_amend_with_unbalanced_check_is_a_usage_error(self):
        code, out = run("add", "T", "--check", PASS_CHECK, "--target", self.pj.dir)
        self.assertEqual(code, 0, out)
        before = self.checks_of("T")
        code, out = cli("amend", "T", "--check", UNBALANCED, "--why", "w", "--target", self.pj.dir)
        self.assertUsageError(code, out)
        self.assertEqual(self.checks_of("T"), before, "the task's checks are unchanged")


class B3Documentation(unittest.TestCase):

    def test_B3_readme_says_the_bash_hook_reads_command_words_only(self):
        hook_paras = [p for p in paragraphs(README) if "ops-patterns" in p or ("PreToolUse" in p and "Bash" in p)]
        self.assertTrue(hook_paras, "the README describes the Bash hook")
        joined = "\n".join(hook_paras).lower()
        self.assertIn("heredoc", joined, "the Bash hook's description says a heredoc body is text")
        self.assertIn("quoted", joined, "the Bash hook's description says a quoted argument is text")

    def test_B3_readme_says_text_inside_a_check_argument_is_kept_as_given(self):
        paras = [p for p in paragraphs(README) if "{plugin:NAME}" in p and "as given" in p]
        self.assertTrue(paras, "a paragraph on how a check's argv is kept says text inside an argument is kept as given")
        joined = "\n".join(paras)
        self.assertTrue("does not parse" in joined or "usage error" in joined, "and that text that does not parse is a usage error")

    def test_B3_hook_docstring_says_command_words_only(self):
        with io.open(PRE_BASH, encoding="utf-8") as fh:
            src = fh.read()
        self.assertTrue(src.lstrip().startswith('"""'), "the hook has a docstring")
        doc = src.lstrip()[3:].split('"""', 1)[0].lower()
        self.assertIn("heredoc", doc)
        self.assertIn("quoted", doc)


if __name__ == "__main__":
    unittest.main()
