"""Azure Blob Storage delivery to a container in an existing storage account."""
from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from app.providers import register
from app.providers.base import ConfigField, DeliveryProvider, DeployResult


@register
class AzureBlobProvider(DeliveryProvider):
    key = 'azure'
    label = 'Azure Blob Storage'
    config_fields = [
        ConfigField('account_url', 'Storage account Blob URL',
                    placeholder='https://<account>.blob.core.windows.net',
                    help='Use an existing storage account. Enter its Blob service URL without a container or SAS token.'),
        ConfigField('account_key', 'Storage account access key', type='password', secret=True,
                    help='Find under Storage account → Access keys. Stored encrypted.'),
        ConfigField('container', 'Container', placeholder='payloads',
                    help='Created when saving if missing. Use 3–63 lowercase letters, numbers, or single hyphens.'),
        ConfigField('public_read', 'Public downloads', type='bool', required=False,
                    help='Allow anonymous reads of all blobs in this container, without allowing listing or writes. '
                         'The storage account must allow Blob anonymous access.'),
        ConfigField('public_base_url', 'Public base URL', required=False,
                    placeholder='https://cdn.example.com/payloads',
                    help='Optional CDN/custom domain pointing to this container. The blob name is appended.'),
        ConfigField('prefix', 'Blob prefix', required=False, placeholder='staging/',
                    help='Optional prefix prepended to every blob name.'),
    ]

    def _container(self):
        from azure.storage.blob import ContainerClient

        account_url = (self.config.get('account_url') or '').strip().rstrip('/')
        parsed = urlparse(account_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.path
                or parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError('Use an HTTPS Blob service URL, such as https://<account>.blob.core.windows.net, '
                             'without a container path or SAS token')
        container = self.config.get('container') or ''
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]', container) or '--' in container:
            raise ValueError('Container name must be 3–63 lowercase letters, numbers, or single hyphens')
        if not self.config.get('account_key'):
            raise ValueError('Storage account access key is required')
        return ContainerClient(account_url, container, credential=self.config['account_key'],
                               connection_timeout=10, read_timeout=30)

    def _set_access(self, container):
        if 'public_read' not in self.config:
            return
        # Preserve stored SAS policies when changing anonymous access.
        policy = container.get_container_access_policy()
        identifiers = {item.id: item.access_policy for item in policy['signed_identifiers']}
        container.set_container_access_policy(
            signed_identifiers=identifiers,
            public_access='blob' if self.config.get('public_read') is True else None,
        )

    def provision(self) -> None:
        from azure.core.exceptions import ResourceExistsError

        with self._container() as container:
            try:
                container.create_container(public_access='blob' if self.config.get('public_read') is True else None)
            except ResourceExistsError:
                container.get_container_properties()
                self._set_access(container)

    def deploy(self, uri: str, data: bytes, content_type: str, meta: dict) -> DeployResult:
        from azure.storage.blob import ContentSettings

        key = (self.config.get('prefix') or '').lstrip('/') + uri.lstrip('/')
        disposition = f'inline; filename="{meta["dl_filename"]}"' if meta.get('dl_filename') else None
        with self._container() as container:
            self._set_access(container)
            blob = container.get_blob_client(key)
            blob.upload_blob(data, overwrite=True, content_settings=ContentSettings(
                content_type=content_type or 'application/octet-stream', content_disposition=disposition))
            base = (self.config.get('public_base_url') or '').rstrip('/')
            url = f'{base}/{quote(key, safe="/")}' if base else blob.url
        return DeployResult(public_url=url, ref=key, extra={'container': self.config['container']})

    def delete(self, ref: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        with self._container() as container:
            try:
                container.delete_blob(ref, delete_snapshots='include')
            except ResourceNotFoundError:
                pass  # Idempotent removal of an already-deleted deployment.

    def delete_container(self) -> None:
        with self._container() as container:
            if next(iter(container.list_blobs(include=['snapshots', 'versions'], results_per_page=1)), None) is not None:
                raise ValueError('Container is not empty. Remove its blobs, snapshots, and versions first.')
            container.delete_container()

    def list_files(self) -> list[dict]:
        files = []
        base = (self.config.get('public_base_url') or '').rstrip('/')
        with self._container() as container:
            for blob in container.list_blobs(name_starts_with=(self.config.get('prefix') or '').lstrip('/')):
                files.append({'ref': blob.name, 'size': blob.size,
                              'modified_at': blob.last_modified.isoformat() if blob.last_modified else None,
                              'url': f'{base}/{quote(blob.name, safe="/")}' if base else container.get_blob_client(blob.name).url})
        return files

    def health(self) -> tuple[bool, str]:
        try:
            with self._container() as container:
                container.get_container_properties()
            return True, 'container reachable'
        except Exception as exc:
            return False, str(exc)
