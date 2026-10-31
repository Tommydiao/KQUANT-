const test = require('node:test');
const assert = require('node:assert/strict');
const { classifyResponse, responseEvidence, isolationCode } = require('./browser_response_evidence.cjs');

test('body observation cannot indefinitely block browser shutdown', async () => {
  assert.equal(await isolationCode({ json: () => new Promise(() => {}) }, 10), null);
  assert.equal(await isolationCode({ json: async () => ({ detail: 'private text' }) }), null);
  assert.equal(await isolationCode({ json: async () => ({ detail: 'TEST_ONLY_LEGACY_NOT_MOUNTED' }) }), 'TEST_ONLY_LEGACY_NOT_MOUNTED');
});

test('only an explicit isolated-server marker classifies intentional exclusion', () => {
  assert.equal(classifyResponse(503, {}), 'HTTP_FAILURE_REQUIRES_ATTRIBUTION');
  assert.equal(classifyResponse(503, { 'x-kquant-test-isolation': 'legacy-not-mounted' }), 'TEST_ONLY_UNMOUNTED');
  assert.equal(classifyResponse(500, { 'x-kquant-test-isolation': 'legacy-not-mounted' }), 'HTTP_FAILURE_REQUIRES_ATTRIBUTION');
});
test('timing and identifiers exclude query strings, cookies and authorization', () => {
  const response = { url: () => 'http://127.0.0.1:8142/api/status?secret=hidden', status: () => 503,
    headers: () => ({ 'set-cookie': 'private', authorization: 'private', 'x-request-id': 'server-1' }) };
  const result = responseEvidence(response, { index: 1 }, { id: 'browser-1', started: 1000 }, 1037);
  assert.equal(result.path, '/api/status');
  assert.equal(result.time_to_headers_ms, 37);
  assert.equal(result.server_request_id, 'server-1');
  assert.equal(JSON.stringify(result).includes('private'), false);
  assert.equal(JSON.stringify(result).includes('hidden'), false);
  assert.equal(responseEvidence(response, {}, null).time_to_headers_ms, null);
});
