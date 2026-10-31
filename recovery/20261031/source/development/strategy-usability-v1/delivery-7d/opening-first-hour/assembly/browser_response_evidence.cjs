// Classification is based on an explicit isolated-server marker, never on URL alone.
function classifyResponse(status, headers) {
  if (status === 503 && headers['x-kquant-test-isolation'] === 'legacy-not-mounted') {
    return 'TEST_ONLY_UNMOUNTED';
  }
  return status >= 400 ? 'HTTP_FAILURE_REQUIRES_ATTRIBUTION' : 'HTTP_SUCCESS';
}

function responseEvidence(response, scope, request, observedMs = Date.now()) {
  const headers = response.headers();
  const codes = new Set(['UPSTREAM_TIMEOUT', 'UPSTREAM_CONNECTION_FAILED', 'UPSTREAM_TRANSPORT_FAILED']);
  const stages = new Set(['NOT_STARTED', 'CONNECT', 'CONNECTED', 'SEND', 'RECEIVE', 'UNKNOWN']);
  const provenance = headers['x-kquant-error-origin'] === 'GATEWAY_UPSTREAM'
    && codes.has(headers['x-kquant-error-code']) ? {
      error_code: headers['x-kquant-error-code'], error_origin: 'GATEWAY_UPSTREAM',
      failure_stage: stages.has(headers['x-kquant-failure-stage']) ? headers['x-kquant-failure-stage'] : 'UNKNOWN',
    } : {};
  return {
    ...scope,
    ...provenance,
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
async function isolationCode(response, budgetMs = 1000, observation = {}) {
  let timer;
  try {
    const body = await Promise.race([
      response.json(),
      new Promise(resolve => { timer = setTimeout(() => resolve(null), budgetMs); }),
    ]);
    observation.error_body_state = body === null ? 'UNAVAILABLE_OR_TIMEOUT' : 'PARSED';
    const allowed = new Set(['UPSTREAM_TIMEOUT','UPSTREAM_CONNECTION_FAILED',
      'UPSTREAM_TRANSPORT_FAILED','CURRENT_CARDS_UNAVAILABLE','TREND_STATUS_UNAVAILABLE',
      'SNAPSHOT_READ_CAPACITY','CONNECT','SEND','RECEIVE','UNKNOWN','POOL',
      'GATEWAY_UPSTREAM','TEST_ONLY_LEGACY_NOT_MOUNTED',
      'LOGIN_CONFIGURATION_CHECK_UNAVAILABLE','LOGIN_CONFIGURATION_RESTART_REQUIRED',
      'CURRENT_SESSION_SNAPSHOT_UNAVAILABLE','CONNECTED','NOT_STARTED']);
    for (const key of ['error_code', 'error_origin', 'failure_stage']) {
      if (allowed.has(body?.[key])) observation[key] = body[key];
    }
    if (allowed.has(body?.detail)) observation.error_code = body.detail;
    return body?.detail === 'TEST_ONLY_LEGACY_NOT_MOUNTED' ? body.detail : null;
  } catch { observation.error_body_state = 'READ_FAILED'; return null; }
  finally { clearTimeout(timer); }
}
module.exports = { classifyResponse, responseEvidence, isolationCode };
