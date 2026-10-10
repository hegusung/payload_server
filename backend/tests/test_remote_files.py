import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault('DATA_DIR', tempfile.gettempdir())
os.environ.setdefault('SECRET_KEY', 'bucket-lifecycle-test')

from app.api.mgmt import RemoteFilesDeleteIn, delete_target_files, target_files
from app.crypto import encrypt_config
from app.db import Base, DeliveryTarget, Deployment
from app.providers.azure import AzureBlobProvider
from app.providers.s3 import S3Provider


class RemoteListingTests(unittest.TestCase):
    def test_s3_listing_consumes_all_pages_and_applies_prefix(self):
        provider = S3Provider({'bucket': 'test', 'prefix': '/staging/'})
        client = MagicMock()
        modified = datetime(2026, 10, 10, tzinfo=timezone.utc)
        client.get_paginator.return_value.paginate.return_value = [
            {'Contents': [{'Key': 'staging/a.txt', 'Size': 3, 'LastModified': modified}]},
            {'Contents': [{'Key': 'staging/b name.txt', 'Size': 4}]}, {}]
        with patch.object(provider, '_client', return_value=client):
            result = provider.list_files()
        client.get_paginator.return_value.paginate.assert_called_once_with(Bucket='test', Prefix='staging/')
        self.assertEqual([file['ref'] for file in result], ['staging/a.txt', 'staging/b name.txt'])
        self.assertEqual(result[0]['modified_at'], modified.isoformat())
        self.assertTrue(result[1]['url'].endswith('staging/b%20name.txt'))

    def test_azure_listing_returns_current_blobs_and_custom_urls(self):
        provider = AzureBlobProvider({'prefix': '/staging/', 'public_base_url': 'https://cdn.example.com/'})
        container = MagicMock()
        container.__enter__.return_value = container
        container.list_blobs.return_value = iter([
            SimpleNamespace(name='staging/a name.txt', size=3, last_modified=None)])
        with patch.object(provider, '_container', return_value=container):
            result = provider.list_files()
        container.list_blobs.assert_called_once_with(name_starts_with='staging/')
        self.assertEqual(result[0]['url'], 'https://cdn.example.com/staging/a%20name.txt')


class RemoteFilesManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.target = DeliveryTarget(name='test', provider_key='s3',
            config_enc=encrypt_config({'bucket': 'test', 'prefix': 'staging/'}))
        self.db.add(self.target)
        self.db.commit()
        for ref in ['staging/a', 'staging/b']:
            self.db.add(Deployment(file_id=1, target_id=self.target.id, uri='/file',
                                   provider_ref=ref, status='deployed'))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_listing_uses_remote_storage(self):
        remote = [{'ref': 'staging/external', 'size': 5, 'url': 'https://example.com/file', 'modified_at': None}]
        with patch.object(S3Provider, 'list_files', return_value=remote):
            result = target_files(self.target.id, self.db)
        self.assertEqual(result, {'files': remote, 'prefix': 'staging/'})

    def test_delete_one_keeps_other_files(self):
        with patch.object(S3Provider, 'delete') as delete:
            result = delete_target_files(self.target.id, RemoteFilesDeleteIn(refs=['staging/a']), self.db)
        delete.assert_called_once_with('staging/a')
        self.assertEqual(result['deleted'], ['staging/a'])
        self.assertEqual(self.db.query(Deployment).one().provider_ref, 'staging/b')

    def test_bulk_delete_only_requested_files_and_deduplicates(self):
        with patch.object(S3Provider, 'delete') as delete:
            result = delete_target_files(self.target.id,
                RemoteFilesDeleteIn(refs=['staging/a', 'staging/b', 'staging/a']), self.db)
        self.assertEqual(delete.call_count, 2)
        self.assertEqual(result['deleted'], ['staging/a', 'staging/b'])
        self.assertEqual(self.db.query(Deployment).count(), 0)
        self.assertEqual(self.db.query(DeliveryTarget).count(), 1)

    def test_partial_failure_preserves_failed_record(self):
        with patch.object(S3Provider, 'delete', side_effect=[None, RuntimeError('denied')]):
            result = delete_target_files(self.target.id,
                RemoteFilesDeleteIn(refs=['staging/a', 'staging/b']), self.db)
        self.assertEqual(result['deleted'], ['staging/a'])
        self.assertEqual(result['errors'], [{'ref': 'staging/b', 'message': 'denied'}])
        self.assertEqual(self.db.query(Deployment).one().provider_ref, 'staging/b')

    def test_outside_prefix_rejected_before_deleting_anything(self):
        with patch.object(S3Provider, 'delete') as delete:
            with self.assertRaises(HTTPException) as caught:
                delete_target_files(self.target.id, RemoteFilesDeleteIn(refs=['staging/a', 'other']), self.db)
        self.assertEqual(caught.exception.status_code, 400)
        delete.assert_not_called()

    def test_pending_deployment_blocks_deletion(self):
        self.db.query(Deployment).first().status = 'pending'
        self.db.commit()
        with patch.object(S3Provider, 'delete') as delete:
            with self.assertRaises(HTTPException) as caught:
                delete_target_files(self.target.id, RemoteFilesDeleteIn(refs=['staging/a']), self.db)
        self.assertEqual(caught.exception.status_code, 409)
        delete.assert_not_called()

    def test_listing_failure_is_reported(self):
        with patch.object(S3Provider, 'list_files', side_effect=RuntimeError('denied')):
            with self.assertRaises(HTTPException) as caught:
                target_files(self.target.id, self.db)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn('denied', caught.exception.detail)


if __name__ == '__main__':
    unittest.main()
