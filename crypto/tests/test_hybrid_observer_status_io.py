from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

from kquant_crypto.hybrid_observer_status_io import publish_status, io_failure_detail


def test_bounded_transient_and_persistent():
    write=Mock(side_effect=[PermissionError(),None])
    sleep=Mock()
    publish_status('status.json',{},write=write,sleep=sleep)
    assert write.call_count==2
    sleep.assert_called_once_with(.05)
    write=Mock(side_effect=PermissionError())
    sleep=Mock()
    with pytest.raises(PermissionError):
        publish_status('status.json',{},write=write,sleep=sleep)
    assert write.call_count==5
    assert sum(c.args[0] for c in sleep.call_args_list)==.75


def test_other_io_errors_not_retried():
    write=Mock(side_effect=OSError('disk full'))
    with pytest.raises(OSError):
        publish_status('status.json',{},write=write,sleep=Mock())
    assert write.call_count==1


def test_failure_path_scope(tmp_path):
    exc=PermissionError(13,'do not record arbitrary messages',str(tmp_path/'status.tmp'))
    assert io_failure_detail(exc,tmp_path)['filename']=='status.tmp'
    assert io_failure_detail(exc,tmp_path/'other')['filename']=='OUTSIDE_RUN_REDACTED'
    assert 'arbitrary' not in str(io_failure_detail(exc,tmp_path))


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows sharing semantics')
def test_real_windows_reader_prevents_replace_until_release(tmp_path):
    import ctypes
    from ctypes import wintypes
    import json
    from kquant_crypto.hybrid_delivery import atomic_json
    path=tmp_path/'status.json'
    atomic_json(path,{'state':'OLD'})
    dll=ctypes.WinDLL('kernel32',use_last_error=True)
    dll.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                             wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    dll.CreateFileW.restype=wintypes.HANDLE
    dll.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=dll.CreateFileW(str(path),0x80000000,1,None,3,128,None)
    assert handle not in (None,ctypes.c_void_p(-1).value)
    try:
        with pytest.raises(PermissionError):
            atomic_json(path,{'state':'NEW'})
        def release(_):
            nonlocal handle
            dll.CloseHandle(handle)
            handle=None
        publish_status(path,{'state':'NEW'},sleep=release)
        assert json.loads(path.read_text())['state']=='NEW'
    finally:
        if handle is not None:
            dll.CloseHandle(handle)
