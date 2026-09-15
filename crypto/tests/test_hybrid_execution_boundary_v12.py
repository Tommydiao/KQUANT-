import unittest
from kquant_crypto.hybrid_execution_boundary_v12 import CredentialReference,inspect_configuration


class ExecutionBoundaryTests(unittest.TestCase):
    def reference(self,environment='testnet',permissions=frozenset({'TRADE','USER_DATA'})):
        return CredentialReference('owner_test_handle',environment,'BINANCE_SPOT_TESTNET',permissions)
    def test_valid_config_still_not_permission(self):
        r=inspect_configuration(environment='testnet',endpoint='https://testnet.binance.vision',reference=self.reference())
        self.assertEqual(r['status'],'CONFIGURATION_VALID_NOT_CONNECTED')
        self.assertFalse(r['request_authorized']);self.assertFalse(r['trade_authorized'])
    def test_production_never_loaded(self):
        for mode in ('live','production_readonly'):
            r=inspect_configuration(environment=mode,endpoint='https://api.binance.com',reference=object())
            self.assertEqual(r['status'],'DENIED')
    def test_wrong_host_or_environment_rejected(self):
        for host in ('https://api.binance.com','https://data-api.binance.vision','https://testnet.binance.vision.evil.test',
                     'https://a:b@testnet.binance.vision','https://testnet.binance.vision:9443','https://testnet.binance.vision/api'):
            with self.assertRaises(ValueError):inspect_configuration(environment='testnet',endpoint=host,reference=self.reference())
        with self.assertRaises(ValueError):inspect_configuration(environment='testnet',endpoint='https://testnet.binance.vision',reference=self.reference('live'))
    def test_forbidden_permissions(self):
        for permission in ('WITHDRAW','TRANSFER','MARGIN','FUTURES'):
            with self.assertRaises(ValueError):inspect_configuration(environment='testnet',endpoint='https://testnet.binance.vision',reference=self.reference(permissions=frozenset({permission})))
    def test_mock_cannot_get_transport(self):
        with self.assertRaises(ValueError):inspect_configuration(environment='mock',endpoint='https://testnet.binance.vision',reference=None)
        self.assertFalse(inspect_configuration(environment='mock',endpoint=None,reference=None)['trade_authorized'])


if __name__=='__main__':unittest.main()
