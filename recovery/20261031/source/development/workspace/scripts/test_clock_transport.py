"""Explicit TEST_ONLY UDP boundary; real monitor/child/packet validation remain."""
from contextlib import ExitStack
import json
import socket
import subprocess
from threading import Event, Thread
import time
from unittest.mock import patch

from kquant.options_clock_measurement import METHOD, stamp


class LoopbackClockTransport:
    def __init__(self, *, fail_second=False):
        self.fail_second = fail_second

    def __enter__(self):
        self.stopped=Event()
        self.sockets=[]
        self.threads=[]
        endpoints={}
        for index, host in enumerate(METHOD['servers']):
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1',0))
            sock.settimeout(.1)
            self.sockets.append(sock)
            endpoints[host]=['127.0.0.1',sock.getsockname()[1]]
            if self.fail_second and index == 1:
                continue
            thread=Thread(target=self._serve,args=(sock,),name='TEST_ONLY-ntp-peer')
            thread.start()
            self.threads.append(thread)
        original=subprocess.Popen

        def external_transport(arguments,*args,**kwargs):
            if isinstance(arguments,list) and 'kquant.options_clock_measurement' in arguments:
                arguments=[*arguments,'--test-only-udp-endpoints',json.dumps(endpoints)]
            return original(arguments,*args,**kwargs)

        self.stack=ExitStack()
        self.stack.enter_context(patch('kquant.options_clock_measurement.subprocess.Popen',side_effect=external_transport))
        return self

    def _serve(self,sock):
        while not self.stopped.is_set():
            try:
                request,address=sock.recvfrom(512)
                if len(request)!=48:
                    continue
                reply=bytearray(48)
                reply[0],reply[1],reply[3]=0x24,2,236
                reply[24:32]=request[40:48]
                reply[32:40],reply[40:48]=stamp(time.time()),stamp(time.time())
                sock.sendto(reply,address)
            except socket.timeout:
                continue
            except OSError:
                break

    def __exit__(self,*exc):
        self.stack.close()
        self.stopped.set()
        for thread in self.threads:
            thread.join(timeout=1)
        for sock in self.sockets:
            sock.close()
