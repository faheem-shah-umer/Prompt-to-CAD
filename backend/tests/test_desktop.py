import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("desktop_app", ROOT / "desktop-app.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class DesktopLifecycleTests(unittest.TestCase):
    def setUp(self):
        test_root = ROOT / "tmp" / "desktop-tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=test_root)
        self.backend = desktop.DesktopBackend(Path(self.folder.name))

    def tearDown(self):
        self.backend.stop()
        self.folder.cleanup()

    def test_closing_during_startup_prevents_a_backend_from_spawning(self):
        self.backend.stopped.set()
        with patch.object(desktop.socket, "socket") as listener, patch.object(desktop.subprocess, "Popen") as spawn:
            listener.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 54321)
            self.assertIsNone(self.backend.start())
            spawn.assert_not_called()
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_ready_backend_is_private_and_owned_until_window_close(self):
        process = Mock()
        process.poll.side_effect = [None, None, 0]
        with patch.object(desktop.socket, "socket") as listener, \
                patch.object(desktop.subprocess, "Popen", return_value=process) as spawn, \
                patch.object(desktop, "urlopen") as request:
            listener.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 54321)
            request.return_value.__enter__.return_value.status = 200
            self.assertEqual(self.backend.start(), "http://127.0.0.1:54321")
            listener.return_value.__enter__.return_value.bind.assert_called_once_with(("127.0.0.1", 0))
            command = spawn.call_args.args[0]
            self.assertEqual(command[-3:], ["--backend", "--port", "54321"])
            self.assertEqual(spawn.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.backend.stop()
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)
            self.assertTrue(self.backend.log.closed)

    def test_window_close_kills_only_its_unresponsive_worker(self):
        process = Mock()
        process.poll.side_effect = [None, 0]
        process.wait.side_effect = [subprocess.TimeoutExpired("worker", 5), 0]
        self.backend.process = process
        self.backend.stop()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertTrue(self.backend.stopped.is_set())

    def test_startup_failure_can_release_the_worker_and_log(self):
        process = Mock()
        process.poll.return_value = 1
        with patch.object(desktop.socket, "socket") as listener, \
                patch.object(desktop.subprocess, "Popen", return_value=process):
            listener.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 54321)
            with self.assertRaisesRegex(RuntimeError, "stopped during startup"):
                self.backend.start()
        self.backend.stop()
        process.terminate.assert_not_called()
        self.assertTrue(self.backend.log.closed)


if __name__ == "__main__":
    unittest.main()
