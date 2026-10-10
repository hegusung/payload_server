import os
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault('DATA_DIR', tempfile.gettempdir())
os.environ.setdefault('SECRET_KEY', 'bucket-lifecycle-test')

from app.api.mgmt import TargetIn, create_target, delete_target, update_target
from app.crypto import decrypt_config, encrypt_config
from app.db import Base, DeliveryTarget, Deployment
from app.providers.s3 import S3Provider


class BucketProviderTests(unittest.TestCase):
    def test_public_read_preserves_policy_and_limits_access_to_one_object(self):
        provider = S3Provider({'bucket': 'test-bucket'})
        client = MagicMock()
        client.meta.region_name = 'us-east-1'
        original = {'Sid': 'ExistingRule', 'Effect': 'Deny', 'Principal': '*',
                    'Action': 's3:DeleteObject', 'Resource': 'arn:aws:s3:::test-bucket/*'}
        client.get_bucket_policy.return_value = {'Policy': json.dumps({
            'Version': '2012-10-17', 'Statement': [original]})}
        with patch.object(provider, '_client', return_value=client):
            provider.make_public('example.txt')
        policy = json.loads(client.put_bucket_policy.call_args.kwargs['Policy'])
        self.assertEqual(policy['Statement'][0], original)
        self.assertEqual(policy['Statement'][1]['Action'], 's3:GetObject')
        self.assertEqual(policy['Statement'][1]['Resource'], 'arn:aws:s3:::test-bucket/example.txt')
        block = client.put_public_access_block.call_args.kwargs['PublicAccessBlockConfiguration']
        self.assertTrue(block['BlockPublicAcls'])
        self.assertTrue(block['IgnorePublicAcls'])
        self.assertFalse(block['BlockPublicPolicy'])

    def test_public_read_creates_missing_policy(self):
        provider = S3Provider({'bucket': 'test-bucket'})
        client = MagicMock()
        client.meta.region_name = 'us-east-1'
        client.get_bucket_policy.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchBucketPolicy'}}, 'GetBucketPolicy')
        with patch.object(provider, '_client', return_value=client):
            provider.make_public('example.txt')
        policy = json.loads(client.put_bucket_policy.call_args.kwargs['Policy'])
        self.assertEqual(len(policy['Statement']), 1)

    def test_public_read_rejects_wildcards(self):
        with self.assertRaises(ValueError):
            S3Provider({'bucket': 'test-bucket'}).make_public('*')

    def test_public_read_rejects_r2_endpoint(self):
        with self.assertRaises(ValueError):
            S3Provider({'bucket': 'test-bucket',
                        'endpoint_url': 'https://account.r2.cloudflarestorage.com'}).make_public('example.txt')

    def test_deploy_applies_public_read_when_enabled(self):
        provider = S3Provider({'bucket': 'test-bucket', 'public_read': True})
        with patch.object(provider, '_client'), patch.object(provider, 'make_public') as public:
            provider.deploy('/example.txt', b'test', 'text/plain', {})
        public.assert_called_once_with('example.txt')

    def test_deploy_keeps_default_private(self):
        provider = S3Provider({'bucket': 'test-bucket'})
        with patch.object(provider, '_client'), patch.object(provider, 'make_public') as public:
            provider.deploy('/example.txt', b'test', 'text/plain', {})
        public.assert_not_called()

    def provision(self, region, exists=False, error='404', client_region=None):
        client = boto3.client('s3', region_name=client_region or region or 'us-east-1',
                              aws_access_key_id='test', aws_secret_access_key='test')
        provider = S3Provider({'bucket': 'test-bucket', 'region': region})
        with Stubber(client) as stub, patch.object(provider, '_client', return_value=client):
            params = {'Bucket': 'test-bucket'}
            if exists:
                stub.add_response('head_bucket', {'ResponseMetadata': {'HTTPStatusCode': 200}}, params)
            else:
                stub.add_client_error('head_bucket', service_error_code=error,
                                      http_status_code=404 if error == '404' else 403,
                                      expected_params=params)
                if error == '404':
                    create_params = dict(params)
                    actual_region = region or client_region or 'us-east-1'
                    if actual_region != 'us-east-1':
                        create_params['CreateBucketConfiguration'] = {'LocationConstraint': actual_region}
                    stub.add_response('create_bucket', {}, create_params)
                    stub.add_response('head_bucket', {'ResponseMetadata': {'HTTPStatusCode': 200}}, params)
            provider.provision()
            stub.assert_no_pending_responses()

    def test_create_us_east_1(self):
        self.provision('us-east-1')

    def test_create_regional_bucket(self):
        self.provision('eu-west-3')

    def test_create_uses_client_region_when_blank(self):
        self.provision('', client_region='eu-west-1')

    def test_existing_bucket_is_not_recreated(self):
        self.provision('us-east-1', exists=True)

    def test_access_denied_is_not_treated_as_missing(self):
        with self.assertRaises(ClientError):
            self.provision('us-east-1', error='403')

    def test_delete_does_not_empty_bucket(self):
        provider = S3Provider({'bucket': 'test-bucket'})
        client = boto3.client('s3', region_name='us-east-1',
                              aws_access_key_id='test', aws_secret_access_key='test')
        with Stubber(client) as stub, patch.object(provider, '_client', return_value=client):
            stub.add_response('delete_bucket', {}, {'Bucket': 'test-bucket'})
            provider.delete_bucket()
            stub.assert_no_pending_responses()


class BucketManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.target = DeliveryTarget(name='test', provider_key='s3',
            config_enc=encrypt_config({'bucket': 'test-bucket', 'secret_access_key': 'secret'}))
        self.db.add(self.target)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_creation_failure_does_not_save_target(self):
        with patch.object(S3Provider, 'provision', side_effect=RuntimeError('denied')):
            with self.assertRaises(HTTPException) as caught:
                create_target(TargetIn(name='new', provider_key='s3', config={'bucket': 'new'}), self.db)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(self.db.query(DeliveryTarget).count(), 1)

    def test_creation_provisions_before_save(self):
        with patch.object(S3Provider, 'provision') as provision:
            result = create_target(TargetIn(name='new', provider_key='s3', config={'bucket': 'new'}), self.db)
        provision.assert_called_once()
        self.assertEqual(result['config']['bucket'], 'new')

    def test_edit_preserves_masked_credentials(self):
        with patch.object(S3Provider, 'provision'):
            update_target(self.target.id, TargetIn(name='test', provider_key='s3',
                config={'bucket': 'test-bucket', 'secret_access_key': '••••••••'}), self.db)
        self.assertEqual(decrypt_config(self.target.config_enc)['secret_access_key'], 'secret')

    def test_nonempty_bucket_preserves_target_and_records(self):
        self.db.add(Deployment(file_id=1, target_id=self.target.id, uri='/test', status='deployed'))
        self.db.commit()
        error = ClientError({'Error': {'Code': 'BucketNotEmpty'}}, 'DeleteBucket')
        with patch.object(S3Provider, 'delete_bucket', side_effect=error):
            with self.assertRaises(HTTPException) as caught:
                delete_target(self.target.id, delete_bucket=True, db=self.db)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.query(DeliveryTarget).count(), 1)
        self.assertEqual(self.db.query(Deployment).count(), 1)

    def test_delete_bucket_removes_target_after_success(self):
        with patch.object(S3Provider, 'delete_bucket') as delete:
            delete_target(self.target.id, delete_bucket=True, db=self.db)
        delete.assert_called_once()
        self.assertEqual(self.db.query(DeliveryTarget).count(), 0)

    def test_delete_target_alone_does_not_delete_bucket(self):
        with patch.object(S3Provider, 'delete_bucket') as delete:
            delete_target(self.target.id, db=self.db)
        delete.assert_not_called()

    def test_pending_deployment_blocks_bucket_deletion(self):
        self.db.add(Deployment(file_id=1, target_id=self.target.id, uri='/test', status='pending'))
        self.db.commit()
        with patch.object(S3Provider, 'delete_bucket') as delete:
            with self.assertRaises(HTTPException) as caught:
                delete_target(self.target.id, delete_bucket=True, db=self.db)
        self.assertEqual(caught.exception.status_code, 409)
        delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
