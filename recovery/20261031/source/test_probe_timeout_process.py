"""Real child timeout at the probe boundary, no credentials or SDK calls."""
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest
import probe_market_readiness as probe


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows process lifecycle check')
def test_actual_worker_timeout_is_reaped_and_receipt_is_redacted(tmp_path):
    pid_file = tmp_path / 'fixture.pid'
    fixture = (
        'import os,time; from pathlib import Path; '
        f'Path({str(pid_file)!r}).write_text(str(os.getpid())); '
        'print("TEST_PRIVATE_OUTPUT",flush=True); time.sleep(30)'
    )
    real_run = subprocess.run
    observed = []

    def delayed_worker(command, **kwargs):
        observed.append((command, kwargs['timeout']))
        # Exercise the same subprocess.run kill/wait boundary with a local child.
        return real_run([sys.executable, '-c', fixture], **{**kwargs, 'timeout': 1})

    output = io.StringIO()
    with patch.object(probe, 'ROOT', tmp_path), \
            patch.object(probe, 'OUT', tmp_path / 'evidence/market-readiness'), \
            patch.object(sys, 'argv', ['probe_market_readiness.py', 'clock-only']), \
            patch.object(probe.subprocess, 'run', side_effect=delayed_worker), redirect_stdout(output):
        probe.main()
    receipt = json.loads(Path(json.loads(output.getvalue())['receipt_path']).read_text())
    assert observed[0][1] == 6
    assert observed[0][0][-1] == '--worker'
    assert receipt['status'] == 'CLOCK_MEASUREMENT_TIMED_OUT'
    assert receipt['child_terminated'] is True
    assert 'TEST_PRIVATE_OUTPUT' not in json.dumps(receipt)
    pid = int(pid_file.read_text())
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if handle:
        try:
            code = ctypes.c_ulong()
            assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            assert code.value != 259, 'Timed-out fixture is still active'
        finally:
            kernel.CloseHandle(handle)
    else:
        assert ctypes.get_last_error() == 87, 'Unexpected process inspection failure'
