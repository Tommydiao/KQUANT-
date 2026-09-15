"""Bounded source locations only: never serialize exception locals or messages."""
from pathlib import Path


def failure_frames(exc, root):
    root = Path(root).resolve()
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        try:
            path = Path(code.co_filename).resolve().relative_to(root).as_posix()
        except ValueError:
            path = '<external>'
        frames.append({'file': path, 'line': tb.tb_lineno,
                       'function': code.co_name if path != '<external>' else '<external>'})
        tb = tb.tb_next
    return {'frames': frames[-16:], 'truncated': len(frames) > 16,
            'locals_included': False, 'cause_proven': False}
