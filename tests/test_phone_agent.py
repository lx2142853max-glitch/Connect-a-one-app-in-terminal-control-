import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phone_agent import run_command


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    @patch("phone_agent.subprocess.run")
    @patch("builtins.input", return_value="n")
    def test_refusal_never_runs_command(self, _input, run):
        result = run_command("touch should-not-exist", "test", self.workdir)
        run.assert_not_called()
        self.assertIn("nothing was executed", result)

    @patch("phone_agent.subprocess.run")
    @patch("builtins.input", return_value="y")
    def test_approval_runs_exact_command_in_workdir(self, _input, run):
        run.return_value = subprocess.CompletedProcess(
            args="printf ok", returncode=0, stdout="ok", stderr=""
        )

        result = run_command("printf ok", "print a test string", self.workdir)

        run.assert_called_once_with(
            "printf ok",
            shell=True,
            executable="/bin/sh",
            cwd=str(self.workdir),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertIn("ok", result)
        self.assertIn("Exit code: 0", result)

    @patch("phone_agent.subprocess.run")
    def test_empty_or_overlong_command_never_prompts_or_runs(self, run):
        with patch("builtins.input") as input_mock:
            empty_result = run_command("  ", "test", self.workdir)
            long_result = run_command("x" * 5_001, "test", self.workdir)

        input_mock.assert_not_called()
        run.assert_not_called()
        self.assertIn("empty", empty_result)
        self.assertIn("limited", long_result)


if __name__ == "__main__":
    unittest.main()
