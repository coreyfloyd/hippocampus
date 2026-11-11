"""Test-only audit guard; reject protected state mutations before they happen."""
import os
from pathlib import Path
import sys


def install_write_guard(roots):
    protected = tuple(Path(root).resolve() for root in roots)

    def guard(event, args):
        paths = ()
        if event == 'open':
            path, mode, flags = args
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                paths = (path,)
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.chown', 'os.utime', 'os.truncate'):
            paths = (args[0],)
        elif event == 'os.rename':
            paths = args[:2]
        elif event in ('os.link', 'os.symlink'):
            paths = (args[1],)
        for path in paths:
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(path)).resolve()
                if any(candidate == root or candidate.is_relative_to(root) for root in protected):
                    raise AssertionError('unisolated state write: ' + str(candidate))

    sys.addaudithook(guard)
