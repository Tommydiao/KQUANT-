"""Explicit offline research entrypoint; never a runtime model registration."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Keep compilation caches within the newly authorized isolated environment.
os.environ.setdefault('PYTENSOR_FLAGS', 'cxx=,base_compiledir=' + str(Path(sys.prefix) / 'pytensor_cache'))
os.environ.setdefault('MPLCONFIGDIR', str(Path(sys.prefix) / 'mpl_cache'))
os.environ.setdefault('JAX_ENABLE_X64', 'true')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--diagnose-only', action='store_true')
    parser.add_argument('--sampler-backend', choices=('pymc','numpyro'), default='pymc')
    args = parser.parse_args()
    from kquant_crypto.hybrid_dev_fit import diagnose_saved, fit
    if args.diagnose_only:
        diagnose_saved(args.output)
    else:
        fit(args.output, sampler_backend=args.sampler_backend)
