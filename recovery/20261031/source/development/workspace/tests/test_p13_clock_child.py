"""Real monitor and module child; only external UDP is a TEST_ONLY loopback peer."""
from datetime import UTC, datetime
from datetime import timedelta
import json
from pathlib import Path
import socket
import struct
import threading
import time

from kquant import options_clock_measurement as clock

CODE=Path(clock.__file__).resolve().parent.parent


def wait(monitor):
    begin=time.monotonic()
    value=monitor.tick(datetime.now(UTC))
    while monitor.child is not None and time.monotonic()-begin<8:
        time.sleep(.02)
        value=monitor.tick(datetime.now(UTC))
    monitor.close()
    return value


def peer():
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1',0))
    sock.settimeout(3)
    port=sock.getsockname()[1]
    def answer():
        try:
            raw,address=sock.recvfrom(512)
            reply=bytearray(48)
            reply[0],reply[1],reply[3]=0x24,2,236
            reply[24:32]=raw[40:48]
            t2=time.time()
            reply[32:40],reply[40:48]=clock.stamp(t2),clock.stamp(time.time())
            sock.sendto(reply,address)
        finally:
            sock.close()
    thread=threading.Thread(target=answer)
    thread.start()
    return port,thread


def test_code_data_config_roots_real_child_missing_acceptance(tmp_path,monkeypatch):
    monkeypatch.delenv('PYTHONPATH',raising=False)
    data=tmp_path/'TEST_ONLY data root'
    method=tmp_path/'TEST_ONLY config'/'missing-method.json'
    ports=[peer(),peer()]
    endpoints={host:['127.0.0.1',item[0]] for host,item in zip(clock.METHOD['servers'],ports)}
    monitor=clock.ClockAttachmentMonitor(code_root=CODE,data_root=data,
        method_config_path=method,acceptance_root=tmp_path,udp_test_endpoints=endpoints)
    value=wait(monitor)
    for _,thread in ports:
        thread.join(timeout=4)
    assert value['child_diagnostic']['returncode']==0
    assert value['child_diagnostic']['cwd']==str(CODE)
    assert value['state']=='MEASURED_UNVERIFIED' and not value['precision_verified']
    assert value['method_config_state']=='MISSING'
    assert len([r for r in value['samples'] if r.get('observation_hash')])==2
    assert (data/'work/option_foundation/runtime/clock-measurement.json').is_file()
    assert not (data/'kquant').exists()


def test_real_child_import_failure_preserves_returncode_and_stderr(tmp_path,monkeypatch):
    monkeypatch.delenv('PYTHONPATH',raising=False)
    code=tmp_path/'TEST_ONLY empty code'
    code.mkdir()
    value=wait(clock.ClockAttachmentMonitor(code_root=code,data_root=tmp_path/'data'))
    assert value['error_phase']=='IMPORT'
    assert value['child_diagnostic']['returncode']==1
    assert 'ModuleNotFoundError' in value['child_diagnostic']['stderr']
    assert not value['precision_verified']


def test_spawn_failure_is_not_json_failure(tmp_path):
    value=wait(clock.ClockAttachmentMonitor(code_root=tmp_path/'missing-code',data_root=tmp_path/'data'))
    assert value['error_phase']=='SPAWN'
    assert value['reason']=='MEASUREMENT_SPAWN_FAILED'


def test_stderr_redacts_credentials_and_keeps_limit(monkeypatch):
    monkeypatch.setenv('LONGBRIDGE_ACCESS_TOKEN','TEST_ONLY_SECRET_abc')
    value=clock._safe_stderr('token TEST_ONLY_SECRET_abc authorization: private '+('x'*9000))
    assert 'TEST_ONLY_SECRET_abc' not in value and 'private' not in value
    assert len(value)<=8192


def endpoints():
    ports=[peer(),peer()]
    return {host:['127.0.0.1',item[0]] for host,item in zip(clock.METHOD['servers'],ports)},ports


def test_invalid_method_keeps_method_phase_not_import_failure(tmp_path):
    transport,ports=endpoints()
    method=tmp_path/'TEST_ONLY-invalid-method.json'
    method.write_text('{',encoding='utf-8')
    value=wait(clock.ClockAttachmentMonitor(code_root=CODE,data_root=tmp_path/'data',
        method_config_path=method,udp_test_endpoints=transport))
    for _,thread in ports:
        thread.join(timeout=4)
    assert value['error_phase']=='METHOD' and value['child_diagnostic']['returncode']==0
    assert not value['precision_verified']


def test_result_store_failure_is_separate_from_successful_child(tmp_path):
    transport,ports=endpoints()
    data=tmp_path/'TEST_ONLY-data'
    data.mkdir()
    (data/'work').write_text('TEST_ONLY path obstruction',encoding='ascii')
    value=wait(clock.ClockAttachmentMonitor(code_root=CODE,data_root=data,
        method_config_path=tmp_path/'missing.json',udp_test_endpoints=transport))
    for _,thread in ports:
        thread.join(timeout=4)
    assert value['error_phase']=='STORE' and value['child_diagnostic']['returncode']==0
    assert value['store_error_type'] and not value['precision_verified']


def test_existing_monitor_owns_data_root_host_publication(tmp_path,monkeypatch):
    from kquant import options_host_clock as host
    transport,ports=endpoints()
    now=datetime.now(UTC)
    monkeypatch.setattr(host,'read_system_status',lambda:dict(state='SYNCED_SYSTEM_REPORT',
        source='time.windows.com',leap=0,stratum=3,last_sync_error=0,last_sync_age_seconds=10,
        checked_at=now.isoformat(),precision_verified=False))
    data=tmp_path/'TEST_ONLY-data'
    value=wait(clock.ClockAttachmentMonitor(code_root=CODE,data_root=data,
        method_config_path=tmp_path/'missing.json',udp_test_endpoints=transport))
    for _,thread in ports:
        thread.join(timeout=4)
    snapshot=host.read_status(path=data/'work/option_foundation/runtime/host-clock.json')
    assert snapshot['state']=='SYNCED_SYSTEM_REPORT' and snapshot['snapshot_state']=='FRESH'
    assert not snapshot['precision_verified'] and not value['precision_verified']


def test_accepted_method_wall_jump_limit_applies_between_samples(monkeypatch):
    now=datetime.now(UTC)
    class Jumped(datetime):
        @classmethod
        def now(cls,tz=None):
            return (now+timedelta(milliseconds=200)).astimezone(tz)
    monkeypatch.setattr(clock,'datetime',Jumped)
    monkeypatch.setattr(clock,'_published_time',(now,time.monotonic()))
    monkeypatch.setattr(clock,'_attachment',dict(state='VERIFIED_BOUND',precision_verified=True,
        uncertainty_ms=500,checked_at=now.isoformat()))
    assert clock.snapshot()['state']=='CLOCK_DISCONTINUITY'
    assert not clock.snapshot()['precision_verified']


def test_stale_attachment_never_renews_from_read(monkeypatch):
    now=datetime.now(UTC)
    monkeypatch.setattr(clock,'_published_time',(now,time.monotonic()))
    monkeypatch.setattr(clock,'_attachment',dict(state='VERIFIED_BOUND',precision_verified=True,
        uncertainty_ms=500,checked_at=(now-timedelta(seconds=901)).isoformat()))
    assert clock.snapshot()['state']=='CLOCK_MEASUREMENT_STALE'
    assert not clock.snapshot()['precision_verified']
