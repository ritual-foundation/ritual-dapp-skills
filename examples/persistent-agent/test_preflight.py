"""Ensure wrong-chain/empty-code failures cannot submit transactions."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).with_name('run.sh').resolve()

class PreflightTests(unittest.TestCase):
    def run_case(self, expected, code):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); trace=root/'calls'; trace.touch()
            forge=root/'forge'; forge.write_text('#!/bin/bash\nexit 99\n'); forge.chmod(0o755)
            cast=root/'cast'
            cast.write_text('''#!/bin/bash
printf '%s\\n' "$1" >> "$CALL_TRACE"
case "$1" in
 wallet) echo 0x1111111111111111111111111111111111111111;;
 chain-id) echo 784;;
 code) echo "$MOCK_CODE";;
 *) exit 99;;
esac
''');cast.chmod(0o755)
            env={**os.environ,'PATH':str(root)+':'+os.environ['PATH'],
                 'CALL_TRACE':str(trace),'MOCK_CODE':code,'RPC_URL':'http://localhost:1',
                 'PRIVATE_KEY':'test-key-never-sent','DA_PROVIDER':'gcs',
                 'ASYNC_DELIVERY_ADDRESS':'0x1111111111111111111111111111111111111111'}
            if expected is None: env.pop('EXPECTED_CHAIN_ID',None)
            else: env['EXPECTED_CHAIN_ID']=expected
            result=subprocess.run(['bash',str(SCRIPT)],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertNotIn('send',trace.read_text().splitlines())
            return result.stdout+result.stderr

    def test_expected_chain_required(self):
        self.assertIn('EXPECTED_CHAIN_ID is required',self.run_case(None,'0x01'))

    def test_wrong_chain_fails_before_transactions(self):
        self.assertIn('differs from expected',self.run_case('999','0x01'))

    def test_missing_contract_fails_before_transactions(self):
        self.assertIn('has no deployed bytecode',self.run_case('784','0x'))
