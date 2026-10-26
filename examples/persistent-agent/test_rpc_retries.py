"""Transient observation failures must not abort or resubmit a launched agent."""
import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from requests.exceptions import ConnectionError, Timeout
from ecies import PrivateKey, encrypt
from eth_abi.abi import encode
import helpers

ADDRESS='0x'+'11'*20
ORIGIN='0x'+'22'*32
COMMIT='0x'+'33'*32

class ObservationRetryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.key=PrivateKey('secp256k1')
        self.path=Path(self.directory.name)/'key';self.path.write_text(self.key.to_hex())
        self.args=argparse.Namespace(rpc='http://localhost:1',tracker=ADDRESS,consumer=ADDRESS,
            tx_hash=ORIGIN,from_block=1,timeout=5,output_private_key_file=str(self.path))

    def test_phase1_recovers_connection_failure_and_finds_exact_commitment(self):
        ciphertext=encrypt(self.key.public_key.to_bytes(compressed=False),encode(helpers.PHASE1_TYPES,['pending','','','','',ADDRESS]))
        client=MagicMock()
        client.eth.get_logs.side_effect=[ConnectionError('temporary'),[{'transactionHash':COMMIT}]]
        def receipt(tx):
            return None if tx==ORIGIN else {'status':1,'spcCalls':[{'address':helpers.AGENT_PRECOMPILE,'output':ciphertext}]}
        client.eth.get_transaction_receipt.side_effect=receipt
        client.eth.get_transaction.return_value=None
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client),patch.object(helpers.time,'sleep'),contextlib.redirect_stdout(io.StringIO()) as out:
            helpers.cmd_wait_phase1(self.args)
        self.assertIn('PRELAUNCH_WALLET='+ADDRESS,out.getvalue())
        self.assertEqual(client.eth.get_logs.call_count,2)
        client.eth.send_raw_transaction.assert_not_called()

    def test_phase2_recovers_timeout_and_decrypts_original_job_callback(self):
        ciphertext=encrypt(self.key.public_key.to_bytes(compressed=False),encode(helpers.RESULT_TYPES,['agent-test','private-url','container','checkpoint','','secret-token']))
        log={'topics':[helpers.Web3.keccak(text=helpers.RESULT_EVENT),ORIGIN],'data':encode(['bytes'],[ciphertext])}
        client=MagicMock();client.eth.get_logs.side_effect=[Timeout('temporary'),[log]]
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client),patch.object(helpers.time,'sleep'),contextlib.redirect_stdout(io.StringIO()) as out:
            helpers.cmd_wait_result(self.args)
        self.assertIn('SUCCESS=1',out.getvalue());self.assertNotIn('secret-token',out.getvalue())
        self.assertEqual(client.eth.get_logs.call_count,2)
        client.eth.send_raw_transaction.assert_not_called()

    def test_persistent_transport_failure_stops_at_observation_deadline(self):
        client=MagicMock();client.eth.get_logs.side_effect=ConnectionError('temporary')
        self.args.timeout=1
        with patch.object(helpers,'Web3',wraps=helpers.Web3,return_value=client),patch.object(helpers.time,'monotonic',side_effect=[0,0,2]),patch.object(helpers.time,'sleep'),contextlib.redirect_stderr(io.StringIO()) as err,self.assertRaises(SystemExit):
            helpers.cmd_wait_result(self.args)
        self.assertIn('do not blindly submit',err.getvalue())
        client.eth.send_raw_transaction.assert_not_called()

    def test_non_transport_error_is_not_hidden(self):
        client=MagicMock();client.eth.get_logs.side_effect=ValueError('bad RPC parameters')
        with self.assertRaisesRegex(ValueError,'bad RPC parameters'):
            helpers.observation_logs(client,{})

if __name__=='__main__':unittest.main()
