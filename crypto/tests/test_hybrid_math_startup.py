import pytest
import kquant_crypto.hybrid_math_process as module


@pytest.mark.parametrize('failure', ['process','reader'])
def test_startup_failure_releases_owned_resources(monkeypatch,failure):
    events=[]
    class Pipe:
        def __init__(self,name): self.name=name
        def close(self): events.append(self.name+'_closed')
    class Process:
        pid=None
        def start(self):
            if failure=='process': raise RuntimeError('start failed')
            self.pid=123
        def is_alive(self): return True
        def terminate(self): events.append('terminate')
        def kill(self): events.append('kill')
        def join(self,timeout): events.append('join')
    class Context:
        def Pipe(self,duplex): return Pipe('receive'),Pipe('send')
        def Process(self,**kwargs): return Process()
    class Reader:
        def __init__(self,**kwargs): pass
        def start(self): raise RuntimeError('reader failed')
    monkeypatch.setattr(module.mp,'get_context',lambda _:Context())
    monkeypatch.setattr(module.threading,'Thread',Reader)
    with pytest.raises(RuntimeError):
        module.DevelopmentMathProcess(None,timeout_seconds=1)
    assert 'receive_closed' in events and 'send_closed' in events
    assert ('terminate' in events)==(failure=='reader')
    assert ('kill' in events)==(failure=='reader')
