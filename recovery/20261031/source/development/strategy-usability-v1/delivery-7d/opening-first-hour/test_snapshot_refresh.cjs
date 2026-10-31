const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const base = path.resolve(__dirname, '../../../workspace/web/package.json');
const ts = createRequire(base)('typescript');
const source = fs.readFileSync(path.join(__dirname, 'patches/web/src/unified/snapshotRefreshPolicy.ts'), 'utf8');
const js = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
const exportsObject = {};
new Function('exports', js)(exportsObject);
const matches = exportsObject.publishedSnapshotResource;
for (const strategy of ['opening_momentum', 'opening_trend']) {
  assert.equal(matches(`/api/options/opening-trend/current?research_strategy=${strategy}`), true);
  assert.equal(matches(`/api/options/one-minute/status?compact=true&research_strategy=${strategy}`), true);
  assert.equal(matches(`/api/options/one-minute/status?research_strategy=${strategy}`), false);
}
for (const route of ['/api/options/one-minute/manual', '/api/options/event-sources',
  '/api/options/opening-trend/current?research_strategy=unknown', '/api/options/one-minute/status']) {
  assert.equal(matches(route), false);
}
console.log('SNAPSHOT_REFRESH_ROUTE_TESTS_PASS');
