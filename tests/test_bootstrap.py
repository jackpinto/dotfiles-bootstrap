"""Exercise the bootstrap without network, sudo, or writes to the real home."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


BOOTSTRAP = Path(__file__).resolve().parents[1] / "bootstrap.sh"
STUB = r"""
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps({
        "command": name, "args": args,
        "global_config": os.environ.get("GIT_CONFIG_GLOBAL"),
        "no_system": os.environ.get("GIT_CONFIG_NOSYSTEM"),
    }) + "\n")
if name == "gh":
    if args[:2] == ["auth", "status"]:
        sys.exit(int(os.environ.get("TEST_AUTH_STATUS", "0")))
    if args[:2] == ["auth", "login"]:
        sys.exit(int(os.environ.get("TEST_LOGIN_STATUS", "0")))
if name == "git":
    if "clone" in args:
        if os.environ.get("TEST_CLONE_FAIL") == "1":
            sys.exit(1)
        (Path(args[-1]) / ".git").mkdir(parents=True)
    elif "config" in args:
        print(os.environ.get("TEST_ORIGIN", "https://github.com/jackpinto/dot-files.git"))
"""


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dotfiles-bootstrap-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "commands.jsonl"
        for command in ("git", "gh", "sudo"):
            stub = self.bin / command
            stub.write_text(f"#!{sys.executable}\n" + STUB)
            stub.chmod(0o755)
        self.env = dict(os.environ)
        self.env.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:/usr/bin:/bin",
            TEST_LOG=str(self.log),
            TEST_AUTH_STATUS="0",
            TEST_LOGIN_STATUS="0",
            TEST_CLONE_FAIL="0",
            TEST_ORIGIN="https://github.com/jackpinto/dot-files.git",
        )

    def run_script(self, *args, code=None, **env):
        environment = dict(self.env, **env)
        if code is None:
            if os.geteuid() == 0:
                self.skipTest("End-to-end bootstrap must run as a regular user")
            code = 'detect_distro() { printf "%s\\n" "${TEST_DISTRO:-fedora}"; }; main "$@"'
        return subprocess.run(
            [
                "bash",
                "-c",
                f"source {shlex.quote(str(BOOTSTRAP))}; {code}",
                "test",
                *args,
            ],
            env=environment,
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def calls(self, name=None):
        calls = (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists()
            else []
        )
        return [call for call in calls if name is None or call["command"] == name]

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_help_and_sourcing_have_no_side_effects(self):
        result = self.run_script(code="main --help")
        self.assert_success(result)
        self.assertIn("Usage:", result.stdout)
        self.assertEqual(self.calls(), [])
        self.assert_success(self.run_script(code=":"))
        self.assertEqual(list(self.home.iterdir()), [])

    def test_authenticated_clone_ignores_global_git_config(self):
        (self.home / ".gitconfig").write_text(
            '[url "git@github.com:"]\n    insteadOf = https://github.com/\n'
        )
        result = self.run_script()
        self.assert_success(result)
        clone = next(call for call in self.calls("git") if "clone" in call["args"])
        self.assertEqual(clone["global_config"], "/dev/null")
        self.assertEqual(clone["no_system"], "1")
        self.assertIn(
            "credential.https://github.com.helper=!gh auth git-credential",
            clone["args"],
        )
        self.assertEqual(
            clone["args"][-2], "https://github.com/jackpinto/dot-files.git"
        )
        self.assertTrue((self.home / "projects/dot-files/.git").is_dir())
        self.assertNotIn(
            ["auth", "login"], [call["args"][:2] for call in self.calls("gh")]
        )
        self.assertEqual(self.calls("sudo"), [])

    def test_login_and_custom_destination_with_spaces(self):
        destination = self.root / "my dotfiles"
        result = self.run_script(
            "--repo",
            "someone/config",
            "--destination",
            str(destination),
            TEST_AUTH_STATUS="1",
        )
        self.assert_success(result)
        self.assertIn(
            [
                "auth",
                "login",
                "--hostname",
                "github.com",
                "--git-protocol",
                "https",
                "--web",
            ],
            [call["args"] for call in self.calls("gh")],
        )
        self.assertTrue((destination / ".git").is_dir())

    def test_failed_login_stops_before_clone(self):
        result = self.run_script(TEST_AUTH_STATUS="1", TEST_LOGIN_STATUS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls("git"), [])
        self.assertNotIn("Bootstrap complete", result.stdout)

    def test_existing_checkout_is_preserved_for_ssh_and_https_origins(self):
        destination = self.home / "projects/dot-files"
        (destination / ".git").mkdir(parents=True)
        marker = destination / "local-work"
        marker.write_text("keep me")
        for origin in (
            "https://github.com/jackpinto/dot-files.git",
            "git@github.com:jackpinto/dot-files.git",
            "ssh://git@github.com/jackpinto/dot-files.git",
        ):
            with self.subTest(origin=origin):
                result = self.run_script(TEST_ORIGIN=origin)
                self.assert_success(result)
                self.assertIn("Reusing existing checkout", result.stdout)
        self.assertFalse(any("clone" in call["args"] for call in self.calls("git")))
        self.assertEqual(marker.read_text(), "keep me")

    def test_conflicting_destination_is_rejected_before_authentication(self):
        destination = self.root / "occupied"
        destination.mkdir()
        result = self.run_script("--destination", str(destination))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a Git checkout", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_wrong_repository_is_rejected(self):
        destination = self.home / "projects/dot-files"
        (destination / ".git").mkdir(parents=True)
        result = self.run_script(TEST_ORIGIN="https://github.com/someone/other.git")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another repository", result.stderr)
        self.assertEqual(self.calls("gh"), [])

    def test_broken_destination_symlink_is_preserved(self):
        destination = self.root / "broken"
        destination.symlink_to(self.root / "missing")
        result = self.run_script("--destination", str(destination) + "/")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(self.calls(), [])

    def test_invalid_arguments_fail_before_commands(self):
        for args in (
            ("--unknown",),
            ("--repo",),
            ("--destination", ""),
            ("--repo", "https://github.com/user/repo"),
            ("--repo", "user/repo.git"),
        ):
            with self.subTest(args=args):
                result = self.run_script(*args, code='main "$@"')
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_clone_failure_is_not_reported_as_success(self):
        result = self.run_script(TEST_CLONE_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Bootstrap complete", result.stdout)

    def test_package_installation_for_each_distribution(self):
        # Only availability checks are mocked. The production installer calls
        # the logging sudo stub; no package manager is actually executed.
        code = r"""
installed=0
command() {
    if [[ "${2:-}" == git || "${2:-}" == gh ]]; then
        (( installed == 1 ))
    else
        builtin command "$@"
    fi
}
sudo() {
    builtin command sudo "$@"
    installed=1
}
install_dependencies "$1"
"""
        expected = {
            "fedora": [["dnf", "install", "-y", "git", "gh", "ca-certificates"]],
            "ubuntu": [
                ["apt-get", "update"],
                ["apt-get", "install", "-y", "git", "gh", "ca-certificates"],
            ],
            "arch": [
                [
                    "pacman",
                    "-S",
                    "--needed",
                    "--noconfirm",
                    "git",
                    "github-cli",
                    "ca-certificates",
                ]
            ],
        }
        for distro, commands in expected.items():
            with self.subTest(distro=distro):
                self.log.unlink(missing_ok=True)
                result = self.run_script(distro, code=code)
                self.assert_success(result)
                self.assertEqual(
                    [call["args"] for call in self.calls("sudo")], commands
                )

    def test_package_failure_stops_the_installer(self):
        result = self.run_script(
            code=r"""
command() {
    [[ "${2:-}" != git && "${2:-}" != gh ]]
}
sudo() { return 23; }
install_dependencies ubuntu
printf 'unexpected completion'
"""
        )
        self.assertEqual(result.returncode, 23)
        self.assertNotIn("unexpected completion", result.stdout)

    def test_unsupported_distribution_is_rejected(self):
        # Replace only the os-release source operation, leaving case dispatch real.
        result = self.run_script(code="source() { ID=unsupported; }; detect_distro")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported distribution", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
