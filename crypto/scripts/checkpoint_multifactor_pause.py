"""Save a user-deadline checkpoint after the executor confirms process exit."""
import argparse
import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--fit', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--terminal-exit-code', type=int, required=True)
    p.add_argument('--terminal-session', required=True)
    p.add_argument('--stop-method', choices=['cooperative_deadline','owned_process_deadline_stop','completed_before_deadline'], required=True)
    a = p.parse_args()
    fit, out = (ROOT/a.fit).resolve(), (ROOT/a.output).resolve()
    if any(not path.is_relative_to(ROOT/'outputs/hybrid_delivery') for path in (fit,out)):
        raise ValueError('Independent research checkpoint required')
    out.mkdir(exist_ok=False)
    files = {path.name: sha(path) for path in fit.iterdir() if path.is_file()}
    progress = json.loads((fit/'progress.json').read_text()) if (fit/'progress.json').exists() else {}
    verified_chains = {key: digest for key,digest in progress.get('chain_hashes',{}).items()
                       if files.get(f'chain_{key}.nc') == digest}
    completed = len(verified_chains)
    status = json.loads((fit/'status.json').read_text()) if (fit/'status.json').exists() else None
    artifact = json.loads((fit/'artifact.json').read_text()) if (fit/'artifact.json').exists() else None
    verified = bool(artifact and artifact.get('posterior_sha256') == files.get('posterior.nc')
                    and artifact.get('diagnostics',{}).get('status')=='COMPLETED')
    result = {'checkpoint_time_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'pause_reason': 'USER_REQUEST_2026_09_08_02_00_ASIA_SHANGHAI',
        'terminal_session': a.terminal_session, 'terminal_exit_code': a.terminal_exit_code,
        'terminal_evidence_source': 'executor result supplied by calling task, not inferred from lock/file age',
        'stop_method': a.stop_method, 'fit_path': fit.relative_to(ROOT).as_posix(),
        'fit_files': files, 'completed_chain_files': completed, 'required_chains': 4,
        'verified_chain_hashes': verified_chains,
        'completed_artifact_hash_verified': verified, 'fit_status': status,
        'new_population_model_status': 'DEV_ONLY_UNVALIDATED' if verified else 'INCOMPLETE_NO_VALIDATED_ARTIFACT',
        'mid_chain_resume_supported': False, 'completed_chain_files_preserved': True,
        'automatic_resume': False, 'explicit_user_resume_required': True,
        'original_services_stopped': False, 'execution_enabled': False,
        'remaining': ['sampling performance and missing chains if incomplete',
            'exposed prediction diagnostic after complete artifact only',
            'new holding embargo and 10R conflict', 'independent evaluation and EVAL sidecar acceptance']}
    write_json(out/'checkpoint.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
