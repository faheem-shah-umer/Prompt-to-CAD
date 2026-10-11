import os
from contextlib import contextmanager


@contextmanager
def revision_lock(folder):
    """Hold an OS lock across app windows; the OS releases it if a worker exits."""
    folder.mkdir(parents=True, exist_ok=True)
    handle = (folder / ".revision.lock").open("a+b")
    locked = False
    try:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as error:
            from .projects import RevisionConflict
            raise RevisionConflict("Another application window is updating this project. Reopen it and retry.") from error
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
