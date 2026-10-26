"""Actual encoders and exact job observations; no external network or credentials."""
import argparse
import contextlib
import io
import os
import unittest
import tempfile
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

from ecies import decrypt, encrypt, PrivateKey
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
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key_file = str(Path(self.directory.name) / 'output-key')

    def test_literal_builder_canonical_wire_and_executor_encryption(self):
        args = argparse.Namespace(rpc='http://localhost:1', consumer=CONSUMER, owner=OWNER,
            executor_tee_address=EXECUTOR, executor_pubkey=PUBLIC, private_key=PRIVATE,
            da_provider='gcs', agent_id=7, revision=0, agent_runtime='hermes',
            agent_rpc_url='http://container-chain.invalid', heartbeat_chain_contract=EXECUTOR,
            cli_type=5, model='test-model', prompt='bounded test', max_turns=1, max_tokens=64,
            hf_repo_id='', gcs_prefix='test-prefix', output_private_key_file=self.key_file)
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
        output_key = PrivateKey.from_hex("secp256k1", Path(self.key_file).read_text())
        self.assertEqual(payload[4], output_key.public_key.to_bytes(compressed=False))
        self.assertEqual(len(payload[4]), 65)
        self.assertEqual(os.stat(self.key_file).st_mode & 0o777, 0o600)
        self.assertNotIn(output_key.to_hex(), out.getvalue())
        # The actual submitted public key encrypts a response only this file can open.
        private_result = encrypt(payload[4], encode(helpers.RESULT_TYPES, RESULT_VALUES))
        self.assertEqual(decrypt(output_key.to_hex(), private_result), encode(helpers.RESULT_TYPES, RESULT_VALUES))
        with patch.dict(os.environ, env, clear=True), patch.object(helpers, 'Web3', wraps=helpers.Web3, return_value=client), self.assertRaises(FileExistsError):
            helpers.cmd_build_request(args)
        self.assertEqual(Path(self.key_file).read_text(), output_key.to_hex())
        verify_specific(self, values, protocol, payload)

    def test_bad_credentials_fail_read_only_before_output(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY':'sentinel', 'GCS_DA_BUCKET':'test',
            'GCS_DA_SERVICE_ACCOUNT_JSON':'not-json'}, clear=True), self.assertRaises(SystemExit):
            helpers.cmd_check_inputs(argparse.Namespace(da_provider='gcs'))


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key = PrivateKey('secp256k1')
        self.key_file = str(Path(self.directory.name) / 'key')
        Path(self.key_file).write_text(self.key.to_hex())

    def args(self):
        return argparse.Namespace(rpc='http://localhost:1', consumer=CONSUMER, tracker=EXECUTOR,
            tx_hash=ORIGIN, from_block=1, timeout=1, output_private_key_file=self.key_file)

    def test_exact_origin_commitment_and_bare_spc_output(self):
        client = MagicMock()
        client.eth.get_logs.return_value = [{'transactionHash': COMMIT}]
        client.eth.get_transaction_receipt.side_effect = Exception('origin receipt unavailable')
        client.eth.get_transaction.side_effect = lambda h: {'blockNumber':2, 'spcCalls':[
            {'address':helpers.AGENT_PRECOMPILE, 'output':'0x'+encrypt(self.key.public_key.to_bytes(compressed=False), encode(helpers.PHASE1_TYPES, PHASE1_VALUES)).hex()}]} if h==COMMIT else {'blockNumber':1}
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client), contextlib.redirect_stdout(io.StringIO()) as out:
            helpers.cmd_wait_phase1(self.args())
        self.assertIn('JOB_ID='+ORIGIN,out.getvalue())
        self.assertEqual(client.eth.get_logs.call_args.args[0]['topics'][2],ORIGIN)

    def test_foreign_result_is_ignored_and_exact_result_never_leaks_token(self):
        client = MagicMock()
        result = encrypt(self.key.public_key.to_bytes(compressed=False), encode(helpers.RESULT_TYPES, RESULT_VALUES))
        make = lambda job: {'topics':[helpers.Web3.keccak(text=helpers.RESULT_EVENT), job], 'data':'0x'+encode(['bytes'],[result]).hex()}
        client.eth.get_logs.return_value = [make(FOREIGN),make(ORIGIN)]
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client), contextlib.redirect_stdout(io.StringIO()) as out:
            helpers.cmd_wait_result(self.args())
        self.assertIn('SUCCESS=1',out.getvalue())
        self.assertNotIn('secret-gateway-token',out.getvalue())
        self.assertEqual(client.eth.get_logs.call_args.args[0]['topics'][1],ORIGIN)

    def test_plaintext_wrong_key_and_tampered_output_fail_closed(self):
        plain = encode(helpers.RESULT_TYPES, RESULT_VALUES)
        ciphertext = encrypt(self.key.public_key.to_bytes(compressed=False), plain)
        wrong = encrypt(PrivateKey('secp256k1').public_key.to_bytes(compressed=False), plain)
        for value in [plain, wrong, ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])]:
            with self.subTest(value_length=len(value)):
                client = MagicMock()
                client.eth.get_logs.return_value = [{'topics':[helpers.Web3.keccak(text=helpers.RESULT_EVENT), ORIGIN],
                    'data':'0x'+encode(['bytes'],[value]).hex()}]
                with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client), contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
                    helpers.cmd_wait_result(self.args())
                self.assertNotIn('SUCCESS=1', out.getvalue())
                self.assertNotIn('secret-gateway-token',out.getvalue())

class OutputKeyCleanupTests(unittest.TestCase):
    def test_literal_shell_key_directory_is_private_and_removed_on_success_or_failure(self):
        script = Path(__file__).with_name('run.sh').read_text()
        start = script.index('OUTPUT_KEY_DIRECTORY=$(mktemp')
        end = script.index('BUILD+=(--output-private-key-file', start)
        snippet = script[start:end]
        for status in [0, 17]:
            with self.subTest(status=status):
                result = subprocess.run(['bash','-c','set -eu\n'+snippet+
                    '\nstat -c %a "$OUTPUT_KEY_DIRECTORY"\nprintf "%s\\n" "$OUTPUT_KEY_DIRECTORY"\nexit '+str(status)], text=True, capture_output=True)
                self.assertEqual(result.returncode,status)
                mode,directory = result.stdout.splitlines()
                self.assertEqual(mode,'700')
                self.assertFalse(Path(directory).exists())

PAYLOAD_TYPES = helpers.PERSISTENT_PAYLOAD_V1_TYPES
PHASE1_VALUES = ['instance','','','','','0x'+'77'*20]
RESULT_VALUES = ['instance','private-url','container','checkpoint','','secret-gateway-token']

def verify_specific(test, values, protocol, payload):
    test.assertEqual(len(payload),21)
    test.assertEqual(payload[-2:],(7,0))
    test.assertEqual(protocol[11], helpers.Web3.keccak(encode(['uint256','uint64'],[7,0])))
    calldata = bytes.fromhex(values['CALLDATA'][2:])
    test.assertEqual(calldata[:4], helpers.Web3.keccak(text='callPersistentAgent(uint256,uint64,bytes)')[:4])
    test.assertEqual(decode(['uint256','uint64','bytes'],calldata[4:]),(7,0,bytes.fromhex(values['REQUEST_INPUT'][2:])))
