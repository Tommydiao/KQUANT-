// Classification is based on an explicit isolated-server marker, never on URL alone.
function classifyResponse(status, headers) {
  if (status === 503 && headers['x-kquant-test-isolation'] === 'legacy-not-mounted') {
    return 'TEST_ONLY_UNMOUNTED';
  }
  return status >= 400 ? 'HTTP_FAILURE_REQUIRES_ATTRIBUTION' : 'HTTP_SUCCESS';
}

function responseEvidence(response, scope, request, observedMs = Date.now()) {
  const headers = response.headers();
  return {
    ...scope,
    path: new URL(response.url()).pathname,
    status: response.status(),
    request_id: request?.id ?? null,
    server_request_id: headers['x-request-id'] ?? null,
    request_started_at: request ? new Date(request.started).toISOString() : null,
    response_headers_at: new Date(observedMs).toISOString(),
    time_to_headers_ms: request ? observedMs - request.started : null,
    retry_after: headers['retry-after'] ?? null,
    classification: classifyResponse(response.status(), headers),
  };
}
async function isolationCode(response, budgetMs = 1000) {
  let timer;
  try {
    const body = await Promise.race([
      response.json(),
      new Promise(resolve => { timer = setTimeout(() => resolve(null), budgetMs); }),
    ]);
    return body?.detail === 'TEST_ONLY_LEGACY_NOT_MOUNTED' ? body.detail : null;
  } catch { return null; }
  finally { clearTimeout(timer); }
}
module.exports = { classifyResponse, responseEvidence, isolationCode };
