import asyncio
import pytest
from kquant_crypto.hybrid_observer_cleanup import cancel_renewal
from kquant_crypto.hybrid_observer_cleanup import capture_before_cleanup
from contextlib import asynccontextmanager
from pathlib import Path


def test_cooperative_and_absent():
    async def run():
        assert (await cancel_renewal(None))['state'] == 'NOT_PRESENT'
        task = asyncio.create_task(asyncio.sleep(60))
        assert (await cancel_renewal(task))['state'] == 'FINISHED'
        assert task.cancelled()
        with pytest.raises(ValueError):
            await cancel_renewal(None, float('nan'))
    asyncio.run(run())


def test_resistant_cancel_records_timeout_not_process_exit():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def resist():
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                await release.wait()
        task = asyncio.create_task(resist())
        await started.wait()
        try:
            result = await cancel_renewal(task, .02)
            assert result['state'] == 'TIMED_OUT'
            assert result['process_exit_guaranteed'] is False
            assert not task.done()
        finally:
            release.set()
            await task
    asyncio.run(run())


def test_capture_precedes_outer_cleanup_and_preserves_exception():
    async def run():
        order = []
        error = ValueError('private-value')
        @asynccontextmanager
        async def connection():
            try:
                yield
            finally:
                order.append('cleanup')
        def record(event):
            assert 'private-value' not in str(event)
            assert event['scope'] == 'BODY_EXCEPTION_BEFORE_ENCLOSING_CONTEXT_CLEANUP'
            order.append('record')
        with pytest.raises(ValueError) as caught:
            async with connection(), capture_before_cleanup(record, Path.cwd()):
                raise error
        assert caught.value is error
        assert order == ['record', 'cleanup']
    asyncio.run(run())


def test_recording_failure_does_not_mask_original():
    async def run():
        error = ValueError('original')
        def fail(event):
            raise OSError('private-path')
        with pytest.raises(ValueError) as caught:
            async with capture_before_cleanup(fail, Path.cwd()):
                raise error
        assert caught.value is error
        assert error.__notes__ == ['Pre-cleanup recording failed: OSError']
    asyncio.run(run())
