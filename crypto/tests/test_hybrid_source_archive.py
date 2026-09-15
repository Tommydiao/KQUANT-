import importlib.util
from pathlib import Path
import subprocess


spec = importlib.util.spec_from_file_location('archive_source', Path(__file__).resolve().parents[1] / 'scripts/archive_hybrid_source.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_paths():
    assert module.eligible('crypto/config/strategy.json')
    assert module.eligible('crypto/.env.example')
    for name in ['crypto/work/model.bin', 'crypto/.env', 'web/node_modules/a.js', 'crypto/.venv/a.py']:
        assert not module.eligible(name)
    for name in ['crypto/.env.local','crypto/.env.production','crypto/session.db','crypto/key.pfx','crypto/store.sqlite3-wal']:
        assert not module.eligible(name)


def test_restore_dirty_and_untracked(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
    (root / 'a.py').write_text('x = 1\n')
    module.git(root, 'add', 'a.py')
    module.git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'baseline')
    (root / 'a.py').write_text('x = 2\n')
    (root / 'b.py').write_text('y = 3\n')
    (root / '.env').write_text('DO_NOT_ARCHIVE=secret')
    result = module.archive(root, tmp_path / 'bundle')
    assert result['source_restore_hashes_pass']
    assert (tmp_path / 'bundle/restored/a.py').read_text() == 'x = 2\n'
    assert (tmp_path / 'bundle/restored/b.py').exists()
    assert not (tmp_path / 'bundle/restored/.env').exists()
    assert b'x = 2' in (tmp_path / 'bundle/review.patch').read_bytes()
