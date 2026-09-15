"""HTTP-only transport restricted to one credential-free local health endpoint."""
import http.client
import time
import httpx


class LoopbackHealthTransport(httpx.BaseTransport):
    def handle_request(self, request):
        if request.method != 'GET' or str(request.url) != 'http://127.0.0.1:8010/api/health':
            raise httpx.RequestError('Endpoint not permitted', request=request)
        if 'authorization' in request.headers or 'cookie' in request.headers:
            raise httpx.RequestError('Credentials not permitted', request=request)
        started = time.monotonic()
        conn = http.client.HTTPConnection('127.0.0.1', 8010, timeout=3)
        try:
            conn.request('GET', '/api/health', headers={'Accept': 'application/json'})
            response = conn.getresponse()
            data = bytearray()
            while True:
                remaining = 3 - (time.monotonic()-started)
                if remaining <= 0:
                    raise TimeoutError('Read budget exceeded')
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(4096, 65537-len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > 65536:
                    raise httpx.RequestError('Response exceeds limit', request=request)
            return httpx.Response(response.status, content=bytes(data), request=request)
        except (OSError, http.client.HTTPException) as exc:
            raise httpx.RequestError('Local HTTP transport failed', request=request) from exc
        finally:
            conn.close()
