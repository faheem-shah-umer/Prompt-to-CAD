import ctypes
import os
import subprocess
import sys
import unittest

from backend.v2.process_limits import ProcessTree


@unittest.skipUnless(os.name == "nt", "Windows job ownership")
class ProcessOwnershipTests(unittest.TestCase):
    def test_closing_runtime_job_stops_its_tool_descendants(self):
        from ctypes import wintypes

        python = getattr(sys, "_base_executable", sys.executable)
        source = "import subprocess,sys,time; sys.stdin.readline(); p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
        parent = subprocess.Popen(
            [python, "-c", source],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        tree = None
        child_handle = None
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            tree = ProcessTree(parent)
            parent.stdin.write("start\n")
            parent.stdin.flush()
            child_id = int(parent.stdout.readline().strip())
            child_handle = kernel.OpenProcess(0x100000, False, child_id)
            self.assertTrue(child_handle)
            tree.close()
            parent.wait(timeout=5)
            self.assertEqual(kernel.WaitForSingleObject(child_handle, 5000), 0)
        finally:
            if tree:
                tree.close()
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)
            if child_handle:
                kernel.CloseHandle(child_handle)
            parent.stdin.close()
            parent.stdout.close()


if __name__ == "__main__":
    unittest.main()
