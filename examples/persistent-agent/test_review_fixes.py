"""Credential separation and runtime config; never submits chain transactions."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import helpers
from eth_abi.abi import encode
ADDRESS = '0x' + '11' * 20
HASH = '0x' + '22' * 32
class RuntimeConfigTests(unittest.TestCase):
    def config_env(self):
        return {'UAHI_MODE': 'events', 'UAHI_APP_ID': 'example',
                'UAHI_MANIFEST_URL': 'https://example.com/connector.json',
                'UAHI_MANIFEST_SHA256': 'a' * 64, 'UAHI_ALLOWED_USERS': 'user-1',
                'APP_CONNECTOR_TOKEN': 'test-token'}

    def test_credential_is_separate_from_public_config(self):
        with patch.dict(os.environ, self.config_env(), clear=True):
            config, secrets = helpers.connector_configuration()
            self.assertEqual(config['mode'], 'events')
            self.assertEqual(secrets, {'APP_CONNECTOR_TOKEN': 'test-token'})
            self.assertNotIn('test-token', json.dumps(config))
            runtime = json.loads(helpers.build_runtime_config(argparse.Namespace(
                agent_runtime='hermes', heartbeat_chain_contract=ADDRESS)))
            self.assertEqual(runtime['uahi'], config)

    def test_missing_secret_and_actor_fail_closed(self):
        for field in ('APP_CONNECTOR_TOKEN', 'UAHI_ALLOWED_USERS'):
            env = self.config_env(); del env[field]
            with patch.dict(os.environ, env, clear=True), self.assertRaises(SystemExit):
                helpers.connector_configuration()

    def test_invalid_manifest_and_secret_reference_fail(self):
        for field, value in [('UAHI_MANIFEST_URL', 'http://example.com/x'),
                             ('UAHI_MANIFEST_SHA256', 'invalid'),
                             ('UAHI_CREDENTIAL_REF', 'MODEL_KEY')]:
            env = self.config_env(); env[field] = value
            with patch.dict(os.environ, env, clear=True), self.assertRaises(SystemExit):
                helpers.connector_configuration()

    def test_hybrid_cadence(self):
        env = self.config_env(); env.update(UAHI_MODE='hybrid', UAHI_CADENCE_EVERY_MS='5000')
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(helpers.connector_configuration()[0]['wake']['cadence']['every_ms'], 5000)
