import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException

os.environ.setdefault('DATA_DIR', tempfile.gettempdir())
os.environ.setdefault('SECRET_KEY', 'bucket-lifecycle-test')

from app.api.mgmt import TargetIn, create_target, delete_target, update_target
from app.crypto import decrypt_config
from app.db import Base, DeliveryTarget, Deployment
from app.providers import get_provider, list_providers
from app.providers.azure import AzureBlobProvider


class AzureProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = AzureBlobProvider({'account_url': 'https://example.blob.core.windows.net',
                                          'account_key': 'test-key', 'container': 'payloads'})
        self.container = MagicMock()
        self.container.__enter__.return_value = self.container
        self.container.get_container_access_policy.return_value = {'signed_identifiers': []}
        self.mock_container = patch.object(self.provider, '_container', return_value=self.container)
        self.mock_container.start()
        self.addCleanup(self.mock_container.stop)

    def test_registry_exposes_azure_and_secret_key(self):
        self.assertIsInstance(get_provider('azure', {}), AzureBlobProvider)
        schema = next(p for p in list_providers() if p['key'] == 'azure')
        field = next(f for f in schema['config_fields'] if f['key'] == 'account_key')
        self.assertTrue(field['secret'])

    def test_create_private_container_by_default(self):
        self.provider.provision()
        self.container.create_container.assert_called_once_with(public_access=None)

    def test_create_public_container_without_listing(self):
        self.provider.config['public_read'] = True
        self.provider.provision()
        self.container.create_container.assert_called_once_with(public_access='blob')

    def test_existing_container_preserves_sas_policies(self):
        self.container.create_container.side_effect = ResourceExistsError('exists')
        policy = object()
        self.container.get_container_access_policy.return_value = {
            'signed_identifiers': [SimpleNamespace(id='existing', access_policy=policy)]}
        self.provider.config['public_read'] = True
        self.provider.provision()
        self.container.set_container_access_policy.assert_called_once_with(
            signed_identifiers={'existing': policy}, public_access='blob')

    def test_disable_public_access_on_existing_container(self):
        self.container.create_container.side_effect = ResourceExistsError('exists')
        self.provider.config['public_read'] = False
        self.provider.provision()
        self.container.set_container_access_policy.assert_called_once_with(
            signed_identifiers={}, public_access=None)

    def test_upload_preserves_content_headers_and_prefix(self):
        self.provider.config['prefix'] = 'staging/'
        blob = self.container.get_blob_client.return_value
        blob.url = 'https://example.blob.core.windows.net/payloads/staging/file.txt'
        result = self.provider.deploy('/file.txt', b'bytes', 'text/plain', {'dl_filename': 'download.txt'})
        self.container.get_blob_client.assert_called_once_with('staging/file.txt')
        args = blob.upload_blob.call_args
        self.assertEqual(args.args, (b'bytes',))
        self.assertTrue(args.kwargs['overwrite'])
        self.assertEqual(args.kwargs['content_settings'].content_type, 'text/plain')
        self.assertEqual(args.kwargs['content_settings'].content_disposition, 'inline; filename="download.txt"')
        self.assertEqual(result.ref, 'staging/file.txt')
        self.assertEqual(result.public_url, blob.url)

    def test_custom_base_url_encodes_blob_name(self):
        self.provider.config['public_base_url'] = 'https://cdn.example.com/payloads/'
        result = self.provider.deploy('/folder/file name.txt', b'bytes', '', {})
        self.assertEqual(result.public_url, 'https://cdn.example.com/payloads/folder/file%20name.txt')

    def test_delete_blob_includes_snapshots_and_is_idempotent(self):
        self.container.delete_blob.side_effect = ResourceNotFoundError('missing')
        self.provider.delete('file.txt')
        self.container.delete_blob.assert_called_once_with('file.txt', delete_snapshots='include')

    def test_container_delete_requires_empty_container(self):
        self.container.list_blobs.return_value = iter([object()])
        with self.assertRaises(ValueError):
            self.provider.delete_container()
        self.container.delete_container.assert_not_called()

    def test_empty_container_can_be_deleted(self):
        self.container.list_blobs.return_value = iter([])
        self.provider.delete_container()
        self.container.delete_container.assert_called_once()

    def test_health_failure_surfaces_message(self):
        self.container.get_container_properties.side_effect = HttpResponseError('access denied')
        ok, message = self.provider.health()
        self.assertFalse(ok)
        self.assertIn('access denied', message)

    def test_invalid_url_and_container_rejected_before_connection(self):
        for config in [
            {'account_url': 'https://example.blob.core.windows.net/payloads', 'container': 'payloads'},
            {'account_url': 'https://example.blob.core.windows.net?sig=secret', 'container': 'payloads'},
            {'account_url': 'https://example.blob.core.windows.net', 'container': 'UPPERCASE'},
        ]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                AzureBlobProvider({**config, 'account_key': 'test-key'})._container()


class AzureManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.body = TargetIn(name='azure', provider_key='azure', config={
            'account_url': 'https://example.blob.core.windows.net',
            'container': 'payloads', 'account_key': 'secret'})

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_save_masks_key_and_edit_preserves_it(self):
        with patch.object(AzureBlobProvider, 'provision'):
            result = create_target(self.body, self.db)
            self.assertEqual(result['config']['account_key'], '••••••••')
            self.body.config['account_key'] = '••••••••'
            update_target(result['id'], self.body, self.db)
        row = self.db.get(DeliveryTarget, result['id'])
        self.assertEqual(decrypt_config(row.config_enc)['account_key'], 'secret')

    def test_provision_failure_does_not_save_target(self):
        with patch.object(AzureBlobProvider, 'provision', side_effect=HttpResponseError('denied')):
            with self.assertRaises(HTTPException) as caught:
                create_target(self.body, self.db)
        self.assertIn('Container creation failed', caught.exception.detail)
        self.assertEqual(self.db.query(DeliveryTarget).count(), 0)

    def test_nonempty_container_keeps_target_and_deployments(self):
        with patch.object(AzureBlobProvider, 'provision'):
            result = create_target(self.body, self.db)
        self.db.add(Deployment(file_id=1, target_id=result['id'], uri='/file', status='deployed'))
        self.db.commit()
        with patch.object(AzureBlobProvider, 'delete_container', side_effect=ValueError('Container is not empty')):
            with self.assertRaises(HTTPException) as caught:
                delete_target(result['id'], db=self.db, delete_container=True)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.query(DeliveryTarget).count(), 1)
        self.assertEqual(self.db.query(Deployment).count(), 1)

    def test_delete_empty_container_removes_target(self):
        with patch.object(AzureBlobProvider, 'provision'):
            result = create_target(self.body, self.db)
        with patch.object(AzureBlobProvider, 'delete_container') as delete:
            delete_target(result['id'], db=self.db, delete_container=True)
        delete.assert_called_once()
        self.assertEqual(self.db.query(DeliveryTarget).count(), 0)


if __name__ == '__main__':
    unittest.main()
