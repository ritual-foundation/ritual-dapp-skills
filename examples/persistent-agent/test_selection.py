"""Run with uv run --with eciespy --with eth-abi --with web3 python -m unittest discover -s examples/persistent-agent."""
import argparse
import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch
import helpers

A = '0x' + '11' * 20
B = '0x' + '22' * 20
KEY = b'\x04' + b'\x01' * 64

def service(address=A, *, valid=True, key=KEY, capability=0, endpoint=''):
    return ((address, address, 0, key, endpoint, b'\0' * 32, capability), valid, b'\0' * 32)

class SelectionTests(unittest.TestCase):
    def test_empty_endpoint_is_eligible(self):
        self.assertEqual(helpers.eligible_executor_nodes([service()]), [(A, KEY, '')])

    def test_invalid_missing_key_and_wrong_capability_are_excluded(self):
        self.assertEqual(helpers.eligible_executor_nodes([
            service(valid=False), service(key=b''), service(capability=1), service(helpers.ZERO_ADDRESS)]), [])

    def test_allowlist_and_exclusions(self):
        self.assertEqual(helpers.eligible_executor_nodes([service(), service(B)], B), [(B, KEY, '')])
        self.assertEqual(helpers.eligible_executor_nodes([service()], A, A), [])

    def select(self, **options):
        args=argparse.Namespace(rpc='http://localhost', registry=A, allowed_executors='',
            excluded_executors='', executor_tee_address='', require_health=False, max_agents=10)
        for k,v in options.items(): setattr(args,k,v)
        client=MagicMock()
        client.eth.contract.return_value.functions.getServicesByCapability.return_value.call.return_value=[service()]
        out=io.StringIO()
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client), contextlib.redirect_stdout(out):
            helpers.cmd_select_executor(args)
        return out.getvalue()

    def test_default_does_not_probe(self):
        with patch.object(helpers,'_fetch_health',side_effect=AssertionError('no network probe')):
            self.assertIn('EXECUTOR='+A,self.select())

    def test_pin_cannot_bypass_exclusion(self):
        with self.assertRaises(SystemExit): self.select(executor_tee_address=A,excluded_executors=A)

    def test_pin_cannot_bypass_explicit_health_failure(self):
        with patch.object(helpers,'_fetch_health',side_effect=OSError('unreachable')):
            with self.assertRaises(SystemExit): self.select(executor_tee_address=A,require_health=True)

if __name__=='__main__': unittest.main()
