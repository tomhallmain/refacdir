"""Python stack traces for native crashes, written to a file in the logs dir.

``faulthandler`` dumps every thread's stack when the process gets a fatal
signal or, on Windows, a fatal exception (access violation, ``abort()``,
``qFatal``). It cannot report a fast-fail termination, such as the C
runtime's invalid-parameter abort (``0xc0000409``), which ends the process
without running any handler. On Windows it also reports exceptions that
native code goes on to handle, so an entry is not proof of a crash unless
the process ended there.
"""

import faulthandler
import os
import time

from refacdir.utils.app_paths import user_logs_dir
from refacdir.utils.version import describe

# Not refacdir_<date>.log: the logger deletes old files matching that pattern.
FAULT_LOG_NAME = "faults.log"
# Start the file afresh at the next start once it grows past this.
MAX_FAULT_LOG_BYTES = 1024 * 1024

# faulthandler writes to the file descriptor, so the file must stay open for
# the life of the process.
_fault_log = None


def enable_fault_log() -> str:
    """Send faulthandler's output to the fault log; returns the log's path.
    Later calls return the same path without reopening it."""
    global _fault_log
    if _fault_log is None:
        path = os.path.join(user_logs_dir(), FAULT_LOG_NAME)
        try:
            mode = "w" if os.path.getsize(path) > MAX_FAULT_LOG_BYTES else "a"
        except OSError:
            mode = "a"
        fault_log = open(path, mode, encoding="utf-8")
        fault_log.write(f"--- started {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()}, {describe()}\n")
        fault_log.flush()
        faulthandler.enable(file=fault_log, all_threads=True)
        _fault_log = fault_log
    return _fault_log.name
