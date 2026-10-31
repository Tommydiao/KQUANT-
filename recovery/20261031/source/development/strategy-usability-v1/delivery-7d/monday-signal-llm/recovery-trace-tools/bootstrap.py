"""TEST_ONLY cold-start request timing, without headers, bodies or locals."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metadata_trace_parent', HERE/'metadata-tools/bootstrap.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
MODULES = parent.MODULES
installed = False


def activate(*, verify=False):
    global installed
    result = parent.activate(verify=verify)
    if verify and not installed:
        out = Path(os.environ['KQUANT_TEST_COLD_TRACE_OUT']).resolve()
        if not (out/'TEST_ONLY.json').is_file():
            raise ValueError('TRACE_REQUIRES_TEST_ONLY')
        installed = True
        path = out/f'TEST_ONLY-cold-http-{os.getpid()}.jsonl'
        lock = threading.Lock()

        def emit(row):
            row.update(test_only=True, pid=os.getpid(), monotonic=time.monotonic())
            with lock, path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row)+'\n')

        from kquant.security import ApiSecurityMiddleware
        actual = ApiSecurityMiddleware.dispatch

        async def dispatch(self, request, call_next):
            started = time.monotonic()
            identity = str(id(request))
            emit(dict(kind='request-start', identity=identity, path=request.url.path))
            try:
                response = await actual(self, request, call_next)
                emit(dict(kind='request-end', identity=identity, status=response.status_code,
                          elapsed=time.monotonic()-started))
                return response
            except BaseException as exc:
                emit(dict(kind='request-error', identity=identity, error_type=type(exc).__name__,
                          elapsed=time.monotonic()-started))
                raise

        ApiSecurityMiddleware.dispatch = dispatch

        def sample():
            end = time.monotonic()+12
            while time.monotonic() < end:
                frames = sys._current_frames()
                rows = []
                for thread in threading.enumerate():
                    if thread.ident == threading.get_ident() or thread.ident not in frames:
                        continue
                    rows.append(dict(name=thread.name, stack=[dict(file=frame.filename,
                        line=frame.lineno, function=frame.name)
                        for frame in traceback.extract_stack(frames[thread.ident])[-14:]]))
                emit(dict(kind='threads', threads=rows))
                time.sleep(.05)

        threading.Thread(target=sample, name='TEST_ONLY-cold-trace', daemon=True).start()
    return result
