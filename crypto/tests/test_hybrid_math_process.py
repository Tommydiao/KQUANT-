import time
import os
from kquant_crypto.hybrid_math_process import DevelopmentMathProcess


def slow():
    time.sleep(30)


def answer():
    return 42


def nested_answer():
    return {'evidence': [1, 2]}


def oversized():
    return 'x' * 100000


def crash():
    os._exit(7)


def fail():
    raise ValueError('sensitive input must not escape')


def wait(worker):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        result = worker.poll()
        if result['status'] != 'PENDING':
            return result
        time.sleep(.01)
    raise AssertionError('bounded worker did not finish')


def test_slow_math_does_not_wait_in_poll():
    worker = DevelopmentMathProcess(slow, timeout_seconds=.4)
    try:
        ticks = 0
        start = time.monotonic()
        while time.monotonic() - start < .1:
            worker.poll()
            ticks += 1
        assert ticks > 1
        assert wait(worker)['reason'] == 'DEADLINE_EXPIRED'
    finally:
        worker.close()
    assert not worker.process.is_alive()


def test_result_never_grants_admission():
    worker = DevelopmentMathProcess(answer, timeout_seconds=10)
    try:
        result = wait(worker)
        assert result['value'] == 42
        assert result['admission'] == 'ABSTAIN'
        assert not result['execution_allowed']
    finally:
        worker.close()


def test_large_result_is_rejected():
    worker = DevelopmentMathProcess(oversized, timeout_seconds=10)
    try:
        assert wait(worker)['reason'] == 'RESULT_TOO_LARGE'
    finally:
        worker.close()


def test_crash_does_not_wait_until_deadline():
    worker = DevelopmentMathProcess(crash, timeout_seconds=10)
    try:
        assert wait(worker)['reason'] == 'WORKER_EXIT_WITHOUT_VALID_RESULT'
    finally:
        worker.close()
    assert not worker.reader.is_alive()


def test_error_text_is_not_returned():
    worker = DevelopmentMathProcess(fail, timeout_seconds=10)
    try:
        result = wait(worker)
        assert result['reason'] == 'MATH_WORKER_ERROR'
        assert 'sensitive' not in str(result)
    finally:
        worker.close()


def test_deadline_poll_never_terminates_or_waits_for_process(monkeypatch):
    worker = DevelopmentMathProcess(slow, timeout_seconds=10)
    try:
        worker.deadline = time.monotonic() - 1
        with monkeypatch.context() as patch:
            def forbidden(*args, **kwargs):
                raise AssertionError('process operation on polling path')
            patch.setattr(worker.process, 'terminate', forbidden)
            patch.setattr(worker.process, 'join', forbidden)
            patch.setattr(worker.process, 'is_alive', forbidden)
            assert worker.poll()['reason'] == 'DEADLINE_EXPIRED'
            assert worker.poll()['admission'] == 'ABSTAIN'
    finally:
        worker.close()


def test_caller_cannot_mutate_future_result_or_authorization():
    worker = DevelopmentMathProcess(nested_answer, timeout_seconds=10)
    try:
        result = wait(worker)
        result['execution_allowed'] = True
        result['admission'] = 'PASS'
        result['value']['evidence'].append(3)
        fresh = worker.poll()
        assert fresh['value'] == {'evidence': [1, 2]}
        assert fresh['admission'] == 'ABSTAIN'
        assert not fresh['execution_allowed']
    finally:
        worker.close()
