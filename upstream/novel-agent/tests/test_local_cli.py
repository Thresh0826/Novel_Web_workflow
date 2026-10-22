import os
import unittest
from unittest.mock import patch

from src.agents.local_cli import agent_environment


class ProxyTests(unittest.TestCase):
    def test_windows_proxy_with_no_proxy_environment(self):
        if os.name != 'nt':
            self.skipTest('Windows 注册表代理')
        with patch.dict(os.environ, {'NO_PROXY': 'localhost,127.0.0.1'}, clear=True), \
             patch('src.agents.local_cli.getproxies', return_value={'no': 'localhost,127.0.0.1'}), \
             patch('urllib.request.getproxies_registry', return_value={'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}):
            env = agent_environment()
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:7897')
        self.assertEqual(env['NO_PROXY'], 'localhost,127.0.0.1')

    def test_explicit_proxy_is_preserved_and_keys_not_inherited(self):
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:9999', 'OPENAI_API_KEY': 'test-secret'}, clear=True):
            env = agent_environment()
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:9999')
        self.assertNotIn('OPENAI_API_KEY', env)

    def test_app_override_sets_both_case_variants(self):
        with patch.dict(os.environ, {'NOVEL_WORKBENCH_PROXY': 'http://127.0.0.1:7897', 'https_proxy': 'http://old:80'}, clear=True):
            env = agent_environment()
        self.assertEqual(env['HTTPS_PROXY'], env['https_proxy'])
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:7897')
