"""Offline tests: never decrypt or contact a provider."""
import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_quote_facts as target


class PrivateLoaderTests(unittest.TestCase):
    def run_loader(self, payload, returncode=0, raw=None, error=None):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'KQUANT'
            config.mkdir()
            (config / 'longbridge_market.dpapi').write_text('fixture-not-a-secret')
            result = subprocess.CompletedProcess([], returncode,
                                                 json.dumps(payload).encode() if raw is None else raw,
                                                 b'private error')
            with patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LONGBRIDGE_APP_KEY': 'old'}), \
                    patch.object(target.subprocess, 'run', return_value=result, side_effect=error) as call:
                before = dict(os.environ)
                environment = target.market_environment()
                self.assertEqual(before, dict(os.environ))
                self.assertEqual(call.call_args.kwargs['timeout'], 10)
                self.assertNotIn('new-secret', str(call.call_args.args))
                return environment

    def test_complete_set_replaces_old_environment_without_mutation(self):
        payload = dict(zip(target.MARKET_KEYS, ['new-key', 'new-secret', 'new-token']))
        environment = self.run_loader(payload)
        for key, value in payload.items():
            self.assertEqual(environment[key], value)

    def test_missing_field_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, '^DPAPI_CREDENTIAL_SET_INCOMPLETE$'):
            self.run_loader({'LONGBRIDGE_APP_KEY': 'new-key'})

    def test_decrypt_failure_does_not_expose_stderr(self):
        with self.assertRaisesRegex(ValueError, '^DPAPI_DECRYPT_FAILED$'):
            self.run_loader({}, returncode=1)

    def test_wrong_payload_type(self):
        with self.assertRaisesRegex(ValueError, '^DPAPI_CREDENTIAL_SET_INCOMPLETE$'):
            self.run_loader([])

    def test_malformed_payload_is_redacted(self):
        with self.assertRaisesRegex(ValueError, '^DPAPI_PAYLOAD_INVALID$'):
            self.run_loader({}, raw=b'private-secret-not-json')

    def test_missing_file_makes_no_child(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'LOCALAPPDATA': directory}), \
                patch.object(target.subprocess, 'run') as call:
            with self.assertRaisesRegex(ValueError, '^DPAPI_CONFIG_MISSING$'):
                target.market_environment()
            call.assert_not_called()

    def test_loader_timeout_is_redacted_and_does_not_probe(self):
        output = io.StringIO()
        error = subprocess.TimeoutExpired(['private-secret'], 10, output=b'private-secret')
        with patch.object(target, 'market_environment', side_effect=error), \
                patch.object(target.subprocess, 'run') as call, redirect_stdout(output):
            self.assertEqual(target.main([]), 2)
        call.assert_not_called()
        self.assertNotIn('private-secret', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['requests'], 0)

    def test_probe_timeout_never_prints_captured_output(self):
        output = io.StringIO()
        error = subprocess.TimeoutExpired(['private-secret'], 65, output=b'private-secret')
        with patch.object(target, 'market_environment', return_value={'fixture': 'only'}), \
                patch.object(target.subprocess, 'run', side_effect=error), redirect_stdout(output):
            self.assertEqual(target.main([]), 2)
        self.assertNotIn('private-secret', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'QUOTE_FACT_WRAPPER_TIMED_OUT')

    def test_probe_has_explicit_environment_and_no_old_evidence(self):
        output = io.StringIO()
        environment = {'fixture': 'only'}
        result = subprocess.CompletedProcess([], 0, '{"status":"TEST_ONLY"}', '')
        with patch.object(target, 'market_environment', return_value=environment), \
                patch.object(target.subprocess, 'run', return_value=result) as call, redirect_stdout(output):
            self.assertEqual(target.main(['--symbol', 'MSTR', '--include-minute']), 0)
        command = call.call_args.args[0]
        self.assertEqual(call.call_args.kwargs['env'], environment)
        self.assertIn('aware-only', command)
        self.assertIn('MSTR', command)
        self.assertIn('--include-minute', command)
        self.assertNotIn('--timestamp-evidence', command)
        self.assertNotIn('--diagnostic-symbol', command)


if __name__ == '__main__':
    unittest.main()
