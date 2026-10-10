import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from botocore.stub import Stubber
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault('DATA_DIR', tempfile.gettempdir())
os.environ.setdefault('SECRET_KEY', 'bucket-lifecycle-test')

from app.api.mgmt import TargetIn, create_target, delete_target
from app.db import Base, DeliveryTarget
from app.providers import get_provider, list_providers
from app.providers.r2 import R2Provider


class R2ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = {'account_id': 'a' * 32, 'bucket': 'payloads',
                       'access_key_id': 'test', 'secret_access_key': 'secret'}
        self.provider = R2Provider(self.config)

    def test_registered(self):
        self.assertIsInstance(get_provider('r2', self.config), R2Provider)
        self.assertIn('r2', [p['key'] for p in list_providers()])

    def test_endpoint_region_and_checksum_settings(self):
        client = self.provider._client()
        self.addCleanup(client.close)
        self.assertEqual(client.meta.endpoint_url, 'https://' + 'a' * 32 + '.r2.cloudflarestorage.com')
        self.assertEqual(client.meta.region_name, 'auto')
        self.assertEqual(client.meta.config.s3['addressing_style'], 'path')
        self.assertEqual(client.meta.config.request_checksum_calculation, 'when_required')
        self.assertEqual(client.meta.config.response_checksum_validation, 'when_required')

    def test_aws_account_number_rejected(self):
        self.provider.config['account_id'] = '236495453358'
        with self.assertRaisesRegex(ValueError, 'Cloudflare account ID'):
            self.provider.provision()

    def test_public_api_endpoint_rejected(self):
        self.provider.config['public_base_url'] = self.provider.config['endpoint_url']
        with self.assertRaisesRegex(ValueError, 'not the S3 API endpoint'):
            self.provider._validate()

    def test_public_access_requires_api_token_before_bucket_creation(self):
        self.provider.config['public_read'] = True
        with patch.object(self.provider, '_client') as client:
            with self.assertRaisesRegex(ValueError, 'API token is required'):
                self.provider.provision()
        client.assert_not_called()

    def test_missing_bucket_created_with_auto_location(self):
        client = self.provider._client()
        self.addCleanup(client.close)
        with Stubber(client) as stub:
            stub.add_client_error('head_bucket', service_error_code='404', http_status_code=404,
                                  expected_params={'Bucket': 'payloads'})
            stub.add_response('create_bucket', {}, {'Bucket': 'payloads',
                              'CreateBucketConfiguration': {'LocationConstraint': 'auto'}})
            stub.add_response('head_bucket', {'ResponseMetadata': {'HTTPStatusCode': 200}}, {'Bucket': 'payloads'})
            self.provider.provision()
            stub.assert_no_pending_responses()

    def test_private_download_url_is_signed_and_expires(self):
        client = MagicMock()
        client.generate_presigned_url.return_value = 'https://signed.example.com/file'
        with patch.object(self.provider, '_client', return_value=client):
            url = self.provider._public_url('folder/file.txt')
        self.assertEqual(url, 'https://signed.example.com/file')
        client.generate_presigned_url.assert_called_once_with('get_object',
            Params={'Bucket': 'payloads', 'Key': 'folder/file.txt'}, ExpiresIn=3600)

    def test_custom_domain_does_not_include_bucket_name(self):
        self.provider.config['public_base_url'] = 'https://files.example.com'
        self.assertEqual(self.provider._public_url('folder/a b.txt'), 'https://files.example.com/folder/a%20b.txt')

    def test_cloudflare_public_api_uses_correct_method_and_token(self):
        self.provider.config.update(public_read=True, api_token='cloudflare-token')
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'success': True, 'result': {
            'enabled': True, 'domain': 'pub-test.r2.dev'}}).encode()
        with patch('app.providers.r2.urlopen', return_value=response) as request:
            self.provider.make_public('file.txt')
            url = self.provider._public_url('folder/file.txt')
        sent = request.call_args.args[0]
        self.assertEqual(sent.method, 'PUT')
        self.assertTrue(sent.full_url.endswith('/r2/buckets/payloads/domains/managed'))
        self.assertEqual(json.loads(sent.data), {'enabled': True})
        self.assertEqual(sent.get_header('Authorization'), 'Bearer cloudflare-token')
        self.assertEqual(url, 'https://pub-test.r2.dev/folder/file.txt')
        self.assertEqual(request.call_count, 1)

    def test_listing_resolves_managed_domain_only_once(self):
        self.provider.config.update(public_read=True, api_token='cloudflare-token')
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [{'Contents': [
            {'Key': 'a', 'Size': 1}, {'Key': 'b', 'Size': 2}]}]
        def domain():
            self.provider._public_domain = 'https://pub-test.r2.dev'
            return self.provider._public_domain
        with patch.object(self.provider, '_client', return_value=client), \
             patch.object(self.provider, '_managed_domain', side_effect=domain) as lookup:
            files = self.provider.list_files()
        self.assertEqual(len(files), 2)
        lookup.assert_called_once()

    def test_api_failure_is_reported(self):
        self.provider.config.update(public_read=True, api_token='token')
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"success": false}'
        with patch('app.providers.r2.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'Check API token permissions'):
                self.provider.make_public('file')

    def test_management_masks_credentials_and_supports_bucket_delete(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with Session(engine) as db, patch.object(R2Provider, 'provision'):
            config = {**self.config, 'api_token': 'token'}
            result = create_target(TargetIn(name='r2', provider_key='r2', config=config), db)
            for secret in ('access_key_id', 'secret_access_key', 'api_token'):
                self.assertEqual(result['config'][secret], '••••••••')
            with patch.object(R2Provider, 'delete_bucket') as delete:
                delete_target(result['id'], delete_bucket=True, db=db)
            delete.assert_called_once()
            self.assertEqual(db.query(DeliveryTarget).count(), 0)
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
