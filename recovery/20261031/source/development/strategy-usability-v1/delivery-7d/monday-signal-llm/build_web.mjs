import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const dev = path.dirname(fileURLToPath(import.meta.url));
const base = path.resolve(dev, '../../../../../source/development/workspace/web');
process.chdir(base);
const requireBase = createRequire(path.join(base, 'package.json'));
const ts = requireBase('typescript');
const { build } = await import(pathToFileURL(requireBase.resolve('vite')).href);
const react = (await import(pathToFileURL(requireBase.resolve('@vitejs/plugin-react')).href)).default;
const normalize = p => p.replaceAll('\\', '/');
const relativeOverlay = p => {
  const relative = path.relative(base, p);
  if (relative.startsWith('..') || path.isAbsolute(relative)) return null;
  const candidate = path.join(dev, 'patches', 'web', relative);
  return fs.existsSync(candidate) && fs.statSync(candidate).isFile() ? candidate : null;
};
const modes = process.argv.includes('--unified-only') ? ['unified'] : ['unified', 'stock'];
for (const mode of modes) {
  const config = ts.readConfigFile(path.join(base, mode === 'unified' ? 'tsconfig.unified.json' : 'tsconfig.stock.recovery.json'), ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, base);
  const host = ts.createCompilerHost(parsed.options);
  const read = host.readFile.bind(host);
  const exists = host.fileExists.bind(host);
  host.readFile = name => read(relativeOverlay(name) ?? name);
  host.fileExists = name => !!relativeOverlay(name) || exists(name);
  const program = ts.createProgram(parsed.fileNames, parsed.options, host);
  const diagnostics = ts.getPreEmitDiagnostics(program);
  if (diagnostics.length) {
    console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {getCanonicalFileName:f=>f,getCurrentDirectory:()=>base,getNewLine:()=> '\n'}));
    process.exit(1);
  }
  await build({ configFile: false, root: base, publicDir: mode === 'unified' ? 'unified-public' : 'stock-public',
    plugins: [{name:'kquant-development-overlay', enforce:'pre',
      resolveId(source, importer) {
        if (!importer || !source.startsWith('.')) return null;
        const target = path.resolve(path.dirname(importer.split('?')[0]), source);
        for (const ext of ['', '.tsx', '.ts', '.css']) {
          if (relativeOverlay(target + ext)) return normalize(target + ext);
        }
        return null;
      },
      load(id) { const replacement = relativeOverlay(id.split('?')[0]); return replacement ? fs.readFileSync(replacement, 'utf8') : null; }
    }, react()], build: {outDir:path.join(dev, 'build', mode), emptyOutDir:true,
      rollupOptions:{input:path.join(base, mode === 'unified' ? 'unified.html' : 'index.html')}}});
}
console.log('BUILD_COMPLETE_ACCEPTED_TREE_UNCHANGED');
