import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mockaize_api.errors import ApiError
from mockaize_api.request_log import RequestLog
from mockaize_api.security import Authenticator


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.key = 'installation-key'
        self.digest = hashlib.sha256(self.key.encode()).hexdigest()
        reader = patch('mockaize_api.security.key_digest', side_effect=lambda _: self.digest)
        self.reader = reader.start()
        self.addCleanup(reader.stop)
        self.auth = Authenticator(None, clock=lambda: self.now)

    def assert_status(self, status, operation):
        with self.assertRaises(ApiError) as error:
            operation()
        self.assertEqual(error.exception.status, status)

    def test_key_and_bearer_are_equivalent_alternatives_with_exact_expiration(self):
        context = self.auth.authenticate([self.key], [], required=True)
        self.assertTrue(context.authenticated)
        self.assertEqual(context.method, 'apiKey')
        response = self.auth.issue([self.key], [])
        self.assertEqual(set(response), {'access_token', 'token_type', 'expires_in'})
        self.assertEqual(response['token_type'], 'Bearer')
        self.assertEqual(response['expires_in'], 1800)
        bearer = ['Bearer ' + response['access_token']]
        self.now += 1799.999
        self.assertEqual(self.auth.authenticate([], bearer).method, 'bearer')
        self.now += 0.001
        self.assert_status(401, lambda: self.auth.authenticate([], bearer))
        self.assertEqual(self.auth.authenticate([self.key], []).method, 'apiKey')

    def test_restart_and_key_rotation_invalidate_tokens(self):
        token = self.auth.issue([self.key], [])['access_token']
        self.assert_status(401, lambda: Authenticator(None).authenticate([], ['Bearer ' + token]))
        self.digest = hashlib.sha256(b'new-key').hexdigest()
        self.assert_status(401, lambda: self.auth.authenticate([], ['Bearer ' + token]))
        self.assert_status(401, lambda: self.auth.authenticate([self.key], []))
        self.assertEqual(self.auth.authenticate(['new-key'], []).method, 'apiKey')

    def test_auth_optional_accepts_absence_but_rejects_present_bad_credentials(self):
        context = self.auth.authenticate([], [], required=False)
        self.assertFalse(context.authenticated)
        self.assertEqual(context.method, 'none')
        self.assert_status(401, lambda: self.auth.authenticate([], [], required=True))
        self.assert_status(401, lambda: self.auth.authenticate(['wrong'], [], required=False))
        self.assert_status(401, lambda: self.auth.authenticate([], ['Bearer wrong'], required=False))

    def test_malformed_or_ambiguous_headers_are_rejected_even_when_auth_optional(self):
        cases = [([self.key, self.key], []), ([], ['Bearer a', 'Bearer b']),
                 ([self.key], ['Bearer a']), ([''], []), ([], ['']),
                 ([], ['Basic abc']), ([], ['Bearer']), ([], ['Bearer a b'])]
        for keys, authorizations in cases:
            with self.subTest(keys=keys, authorizations=authorizations):
                self.assert_status(400, lambda: self.auth.authenticate(keys, authorizations, required=False))

    def test_emission_always_requires_the_key_and_uses_one_digest_snapshot(self):
        self.assert_status(401, lambda: self.auth.issue([], []))
        self.assert_status(401, lambda: self.auth.issue(['wrong'], []))
        token = self.auth.issue([self.key], [])['access_token']
        self.assert_status(401, lambda: self.auth.issue([], ['Bearer ' + token]))
        self.reader.reset_mock()
        self.auth.issue([self.key], [])
        self.reader.assert_called_once()

    def test_rotation_between_authorization_and_issuance_does_not_grant_new_key_access(self):
        self.auth.authenticate([self.key], [])
        self.digest = hashlib.sha256(b'new-key').hexdigest()
        self.assert_status(401, lambda: self.auth.issue([self.key], []))

    def test_auth_log_whitelist_discards_credentials_payload_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            RequestLog(Path(directory)).write(event='LOGIN_SUCCESS', authenticated=True, authMethod='apiKey',
                                             access_token='PRIVATE-TOKEN', apiKey='PRIVATE-KEY',
                                             authorization='PRIVATE-BEARER', username='PRIVATE-USER',
                                             payload={'secret': 'PRIVATE-PAYLOAD'})
            content = next(Path(directory).glob('*.txt')).read_text(encoding='utf-8')
        entry = json.loads(content)
        self.assertEqual(entry['event'], 'LOGIN_SUCCESS')
        self.assertTrue(entry['authenticated'])
        self.assertEqual(entry['authMethod'], 'apiKey')
        self.assertNotIn('PRIVATE', content)
