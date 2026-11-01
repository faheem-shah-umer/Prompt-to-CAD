"""A built application must launch without compiler discovery."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.run_native import main


class DeveloperLauncherTests(unittest.TestCase):
    def test_launch_uses_runtime_without_compiler_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sdk = root / 'SDK with spaces'
            build = root / 'build'
            for path in (sdk / 'lib/cmake/Qt6/Qt6Config.cmake',
                         sdk / 'lib/cmake/opencascade/OpenCASCADEConfig.cmake',
                         build / 'bin/PromptToCAD.exe'):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            argv = ['run_native', '--qt-prefix', str(sdk), '--occt-prefix', str(sdk), '--build-dir', str(build)]
            with patch('sys.argv', argv), patch('tools.build_native.shutil.which', return_value=None), \
                    patch('tools.build_native.msvc_environment', side_effect=AssertionError('Compiler requested')), \
                    patch('tools.run_native.subprocess.run') as launch:
                main()
            launch.assert_called_once()
            self.assertEqual(Path(launch.call_args.args[0][0]), build / 'bin/PromptToCAD.exe')
            self.assertIn(str(sdk / 'bin'), launch.call_args.kwargs['env']['PATH'])


if __name__ == '__main__':
    unittest.main()
