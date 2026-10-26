"""Actual encoders and exact job observations; no external network or credentials."""
import argparse
import contextlib
import io
import os
import unittest
from unittest.mock import MagicMock, patch

from ecies import decrypt
from eth_abi.abi import decode, encode
from eth_account import Account
from eth_keys import keys
import helpers

PRIVATE = '0x' + '01' * 32
OWNER = Account.from_key(PRIVATE).address
CONSUMER = '0x' + '22' * 20
EXECUTOR = '0x' + '33' * 20
PUBLIC = '0x04' + keys.PrivateKey(bytes.fromhex(PRIVATE[2:])).public_key.to_bytes().hex()
ORIGIN = '0x' + '44' * 32
COMMIT = '0x' + '55' * 32
FOREIGN = '0x' + '66' * 32


class RequestTests(unittest.TestCase):
    def test_literal_builder_canonical_wire_and_executor_encryption(self):
        args = argparse.Namespace(rpc='http://localhost:1', consumer=CONSUMER, owner=OWNER,
            executor_tee_address=EXECUTOR, executor_pubkey=PUBLIC, private_key=PRIVATE,
            da_provider='gcs', agent_id=7, revision=0, agent_runtime='hermes',
            agent_rpc_url='http://container-chain.invalid', heartbeat_chain_contract=EXECUTOR,
            cli_type=5, model='test-model', prompt='bounded test', max_turns=1, max_tokens=64,
            hf_repo_id='', gcs_prefix='test-prefix')
        client = MagicMock(); client.eth.chain_id = 784
        env = {'ANTHROPIC_API_KEY':'sentinel-provider', 'MODEL':'test-model', 'UAHI_MODE':'off',
            'GCS_DA_BUCKET':'test-bucket', 'GCS_DA_SERVICE_ACCOUNT_JSON':'{"type":"service_account"}'}
        with patch.dict(os.environ, env, clear=True), patch.object(helpers, 'Web3', wraps=helpers.Web3, return_value=client), contextlib.redirect_stdout(io.StringIO()) as out:
            helpers.cmd_build_request(args)
        values = dict(line.split('=',1) for line in out.getvalue().splitlines() if '=' in line)
        envelope = bytes.fromhex(values['REQUEST_INPUT'][2:])
        protocol = decode(helpers.AGENT_ENVELOPE_TYPES, envelope)
        self.assertEqual(protocol[1].lower(), OWNER.lower())
        self.assertEqual(protocol[5].lower(), CONSUMER.lower())
        self.assertTrue(protocol[4]); self.assertEqual(protocol[10], 0)
        self.assertEqual(encode(helpers.AGENT_ENVELOPE_TYPES, protocol), envelope)
        payload = decode(PAYLOAD_TYPES, protocol[12])
        self.assertEqual(payload[0], 1)
        self.assertEqual(payload[1][0].lower(), OWNER.lower())
        plain = decrypt(PRIVATE, payload[2][0])
        self.assertIn(b'sentinel-provider', plain)
        self.assertNotIn('sentinel-provider', out.getvalue())
        self.assertEqual(helpers.ECIES_CONFIG.symmetric_nonce_length, 12)
        verify_specific(self, values, protocol, payload)

    def test_bad_credentials_fail_read_only_before_output(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY':'sentinel', 'GCS_DA_BUCKET':'test',
            'GCS_DA_SERVICE_ACCOUNT_JSON':'not-json'}, clear=True), self.assertRaises(SystemExit):
            helpers.cmd_check_inputs(argparse.Namespace(da_provider='gcs'))


class ObservationTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(rpc='http://localhost:1', consumer=CONSUMER, tracker=EXECUTOR,
            tx_hash=ORIGIN, from_block=1, timeout=1)

    def test_exact_origin_commitment_and_bare_spc_output(self):
        client = MagicMock()
        client.eth.get_logs.return_value = [{'transactionHash': COMMIT}]
        client.eth.get_transaction_receipt.side_effect = Exception('origin receipt unavailable')
        client.eth.get_transaction.side_effect = lambda h: {'blockNumber':2, 'spcCalls':[
            {'address':helpers.AGENT_PRECOMPILE, 'output':'0x'+encode(helpers.PHASE1_TYPES, PHASE1_VALUES).hex()}]} if h==COMMIT else {'blockNumber':1}
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client), contextlib.redirect_stdout(io.StringIO()) as out:
            helpers.cmd_wait_phase1(self.args())
        self.assertIn('JOB_ID='+ORIGIN,out.getvalue())
        self.assertEqual(client.eth.get_logs.call_args.args[0]['topics'][2],ORIGIN)

    def test_foreign_result_is_ignored_and_exact_result_never_leaks_token(self):
        client = MagicMock()
        result = encode(helpers.RESULT_TYPES, RESULT_VALUES)
        make = lambda job: {'topics':[helpers.Web3.keccak(text=helpers.RESULT_EVENT), job], 'data':'0x'+encode(['bytes'],[result]).hex()}
        client.eth.get_logs.return_value = [make(FOREIGN),make(ORIGIN)]
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client), contextlib.redirect_stdout(io.StringIO()) as out:
            helpers.cmd_wait_result(self.args())
        self.assertIn('SUCCESS=1',out.getvalue())
        self.assertNotIn('secret-gateway-token',out.getvalue())
        self.assertEqual(client.eth.get_logs.call_args.args[0]['topics'][1],ORIGIN)

PAYLOAD_TYPES = helpers.SOVEREIGN_V1_PAYLOAD_TYPES
PHASE1_VALUES = ['task-1']
RESULT_VALUES = [True,'','bounded response',('','',''),('','',''),[]]

def verify_specific(test, values, protocol, payload):
    test.assertEqual(len(payload),16)
    test.assertEqual(protocol[11], b'\0'*32)
    calldata = bytes.fromhex(values['CALLDATA'][2:])
    test.assertEqual(calldata[:4], helpers.Web3.keccak(text='callSovereignAgent(bytes)')[:4])
    test.assertEqual(decode(['bytes'],calldata[4:])[0],bytes.fromhex(values['REQUEST_INPUT'][2:]))
