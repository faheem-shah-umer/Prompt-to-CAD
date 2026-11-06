"""Portable source launches and actionable prerequisite failures."""
from contextlib import ExitStack
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.build_native import ROOT
from tools.run_native import check_dependencies, check_python, main


class DeveloperLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="Prompt to CAD ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.sdk = self.root / "SDK with spaces"
        self.build = self.root / "build"
        self.stack = self.enterContext(ExitStack())
        for name in ("tools.run_native.ROOT", "tools.build_native.ROOT"):
            self.stack.enter_context(patch(name, self.root))
        self.stack.enter_context(patch("tools.build_native.DEFAULT_BUILD", self.build))
        self.stack.enter_context(patch.dict(os.environ, {"CAD_SDK_PREFIX": str(self.sdk), "CAD_QT_PREFIX": str(self.sdk), "CAD_OCCT_PREFIX": str(self.sdk)}))
        for path in (self.sdk / "lib/cmake/Qt6/Qt6Config.cmake",
                     self.sdk / "lib/cmake/opencascade/OpenCASCADEConfig.cmake",
                     self.build / "bin/PromptToCAD.exe"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def launch(self, *arguments):
        with patch("sys.argv", ["run_native", *arguments]), \
                patch("tools.run_native.check_dependencies"), \
                patch("tools.build_native.shutil.which", return_value=None), \
                patch("tools.build_native.msvc_environment", side_effect=AssertionError("Compiler requested")), \
                patch("tools.run_native.subprocess.run") as launch:
            main()
        return launch

    def test_launch_uses_runtime_without_compiler_tools(self):
        launch = self.launch()
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[0], [str(self.build / "bin/PromptToCAD.exe"), "--workspace", str(self.root), "--python", sys.executable])
        self.assertIn(str(self.sdk / "bin"), launch.call_args.kwargs["env"]["PATH"])
        self.assertEqual(launch.call_args.kwargs["cwd"], self.root)

    def test_explicit_paths_and_native_arguments(self):
        other = self.root / "other build with spaces"
        (other / "bin").mkdir(parents=True)
        (other / "bin/PromptToCAD.exe").touch()
        launch = self.launch("--qt-prefix", str(self.sdk), "--occt-prefix", str(self.sdk), "--build-dir", str(other), "--", "--version")
        self.assertEqual(launch.call_args.args[0][0], str(other / "bin/PromptToCAD.exe"))
        self.assertEqual(launch.call_args.args[0][-1], "--version")

    def test_missing_application_explains_build(self):
        (self.build / "bin/PromptToCAD.exe").unlink()
        with self.assertRaisesRegex(RuntimeError, "Application missing: .*tools.build_native"):
            self.launch()

    def test_missing_sdks_explain_setup(self):
        for config in ("Qt6/Qt6Config.cmake", "opencascade/OpenCASCADEConfig.cmake"):
            path = self.sdk / "lib/cmake" / config
            path.unlink()
            with self.subTest(config=config), self.assertRaisesRegex(RuntimeError, "tools.setup_windows --download-sdk"):
                self.launch()
            path.touch()

    def test_python_requirements_come_from_existing_file(self):
        (self.root / "requirements.txt").write_text("# Runtime roots\nsample-runtime==1.2.0\n", encoding="utf-8")
        (self.root / "requirements-runtime-lock.txt").write_text("sample-runtime==1.2.0\nsample-transitive==1.2.0\n", encoding="utf-8")
        with patch("tools.run_native.metadata.version", return_value="1.2.0") as version:
            check_dependencies()
        self.assertEqual([call.args[0] for call in version.call_args_list], ["sample-runtime", "sample-transitive"])
        for result in (metadata.PackageNotFoundError("sample-runtime"), "0.1.0"):
            values = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
            with self.subTest(result=str(result)), patch("tools.run_native.metadata.version", **values), \
                    self.assertRaisesRegex(RuntimeError, "sample-runtime.*requirements-dev.txt"):
                check_dependencies()

    def test_missing_transitive_dependency_explains_install(self):
        (self.root / "requirements.txt").write_text("sample-runtime==1.2.0\n", encoding="utf-8")
        (self.root / "requirements-runtime-lock.txt").write_text("sample-transitive==1.2.0\n", encoding="utf-8")
        with patch("tools.run_native.metadata.version", side_effect=["1.2.0", metadata.PackageNotFoundError("sample-transitive")]), \
                self.assertRaisesRegex(RuntimeError, "sample-transitive.*requirements-dev.txt"):
            check_dependencies()

    def test_missing_dependency_checker_explains_install(self):
        with patch.dict(sys.modules, {"packaging.requirements": None}), \
                self.assertRaisesRegex(RuntimeError, "pip install -r requirements-dev.txt"):
            check_dependencies()

    def test_unsupported_python_explains_prerequisite(self):
        with patch("sys.version_info", (3, 12)), self.assertRaisesRegex(RuntimeError, "py -3.11 -m venv .venv"):
            check_python()
        with patch("sys.maxsize", 2**31 - 1), self.assertRaisesRegex(RuntimeError, "Windows x64 and CPython 3.11 x64"):
            check_python()


@unittest.skipUnless(os.name == "nt", "Windows batch entry point")
class BatchLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="Prompt to CAD batch ")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "checkout with spaces"
        cls.root.mkdir()
        cls.outside = Path(cls.temporary.name) / "outside"
        cls.outside.mkdir()
        shutil.copyfile(ROOT / "Run-PromptToCAD.cmd", cls.root / "Run-PromptToCAD.cmd")
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(cls.root / ".venv")], check=True, capture_output=True, timeout=60)
        (cls.root / "tools").mkdir()
        (cls.root / "tools/run_native.py").write_text(
            "import json, os, sys\n"
            "print(json.dumps({'cwd': os.getcwd(), 'python': sys.executable, 'args': sys.argv[1:]}))\n"
            "sys.exit(23 if '--fail' in sys.argv else 0)\n", encoding="utf-8")

    def run_batch(self, *arguments, root=None, show_directory=False):
        processor = os.environ.get("COMSPEC", "C:/Windows/System32/cmd.exe")
        command = "call " + subprocess.list2cmdline([str((root or self.root) / "Run-PromptToCAD.cmd"), *arguments])
        if show_directory:
            command += " && cd"
        return subprocess.run(f'"{processor}" /d /s /c "{command}"', executable=processor,
                              cwd=self.outside, env={**os.environ, "CI": "true"}, capture_output=True, text=True, timeout=30)

    def test_external_directory_arguments_and_caller_directory(self):
        result = self.run_batch("--qt-prefix", "SDK with spaces", "--", "--version", show_directory=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.strip().splitlines()
        report = json.loads(lines[0])
        self.assertEqual(Path(report["cwd"]), self.root)
        self.assertEqual(Path(report["python"]), self.root / ".venv/Scripts/python.exe")
        self.assertEqual(report["args"], ["--qt-prefix", "SDK with spaces", "--", "--version"])
        self.assertEqual(Path(lines[-1]), self.outside)

    def test_application_exit_code_is_preserved(self):
        self.assertEqual(self.run_batch("--fail").returncode, 23)

    def test_missing_venv_explains_setup_without_pausing(self):
        missing = Path(self.temporary.name) / "no environment"
        missing.mkdir(exist_ok=True)
        shutil.copyfile(self.root / "Run-PromptToCAD.cmd", missing / "Run-PromptToCAD.cmd")
        result = self.run_batch(root=missing)
        self.assertEqual(result.returncode, 1)
        self.assertIn("py -3.11 -m venv .venv", result.stdout)
        self.assertIn("pip install -r requirements-dev.txt", result.stdout)

    def test_private_outputs_and_credentials_remain_ignored(self):
        paths = [".venv/Scripts/python.exe", ".local/toolchain/env.json", "build/bin/PromptToCAD.exe",
                 ".sdk/windows/Library/bin/Qt6Core.dll", "Projects/private/project.json", ".promptcad/identity/auth.json", ".env", "credentials.json"]
        output = subprocess.check_output(["git", "check-ignore", "--stdin", "-z"], input=("\0".join(paths) + "\0").encode(), cwd=ROOT)
        ignored = output.decode().rstrip("\0").split("\0")
        self.assertEqual(ignored, paths)


if __name__ == '__main__':
    unittest.main()
