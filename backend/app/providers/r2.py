"""Cloudflare R2 storage with optional managed public downloads."""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from app.providers import register
from app.providers.base import ConfigField
from app.providers.s3 import S3Provider


@register
class R2Provider(S3Provider):
    key = 'r2'
    label = 'Cloudflare R2'
    config_fields = [
        ConfigField('account_id', 'Cloudflare account ID', placeholder='32-character Cloudflare account ID',
                    help='Find in R2 Overview. Use the Cloudflare account ID, not an AWS account number.'),
        ConfigField('bucket', 'Bucket', placeholder='payloads', help='Created when saving if missing.'),
        ConfigField('access_key_id', 'R2 Access Key ID', secret=True,
                    help='Create R2 S3 credentials with Admin Read & Write permission for bucket creation.'),
        ConfigField('secret_access_key', 'R2 Secret Access Key', type='password', secret=True),
        ConfigField('public_read', 'Enable public r2.dev downloads', type='bool', required=False,
                    help='Makes all objects in this bucket readable via its r2.dev domain. Requires a Cloudflare API token. '
                         'r2.dev is intended for development; use a custom domain for production.'),
        ConfigField('api_token', 'Cloudflare API token', type='password', secret=True, required=False,
                    help='Needed only to enable/manage r2.dev access. Use an API token with R2 storage write permission '
                         'for this account. This is separate from the S3 access keys.'),
        ConfigField('public_base_url', 'Public base URL', required=False,
                    placeholder='https://pub-<id>.r2.dev or https://files.example.com',
                    help='Optional enabled r2.dev URL or connected custom domain. Without public access, '
                         'file links are signed and expire after one hour.'),
        ConfigField('prefix', 'Key prefix', required=False, placeholder='staging/'),
    ]

    def __init__(self, config: dict):
        super().__init__(dict(config or {}))
        self.config['region'] = 'auto'
        self.config['endpoint_url'] = f'https://{self.config.get("account_id", "")}.r2.cloudflarestorage.com'
        self._s3_client = None
        self._public_domain = None

    def _validate(self):
        if not re.fullmatch(r'[a-fA-F0-9]{32}', self.config.get('account_id') or ''):
            raise ValueError('Cloudflare account ID must contain 32 hexadecimal characters (not an AWS account number)')
        bucket = self.config.get('bucket') or ''
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
            raise ValueError('R2 bucket name must be 3–63 lowercase letters, numbers, or hyphens')
        for key in ('access_key_id', 'secret_access_key'):
            if not self.config.get(key):
                raise ValueError('R2 Access Key ID and Secret Access Key are required')
        base = (self.config.get('public_base_url') or '').strip().rstrip('/')
        if base:
            parsed = urlparse(base)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment
                    or parsed.username or parsed.password or parsed.hostname.endswith('.r2.cloudflarestorage.com')):
                raise ValueError('Public base URL must be an HTTPS r2.dev URL or custom domain, not the S3 API endpoint')
            self.config['public_base_url'] = base
        if self.config.get('public_read') is True and not self.config.get('api_token'):
            raise ValueError('A Cloudflare API token is required to enable public r2.dev downloads')

    def _client(self):
        import boto3
        from botocore.config import Config

        self._validate()
        if self._s3_client is None:
            self._s3_client = boto3.client('s3', region_name='auto', endpoint_url=self.config['endpoint_url'],
                aws_access_key_id=self.config['access_key_id'], aws_secret_access_key=self.config['secret_access_key'],
                config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                              retries={'max_attempts': 3}, request_checksum_calculation='when_required',
                              response_checksum_validation='when_required'))
        return self._s3_client

    def _managed_domain(self, enable=False):
        self._validate()
        url = (f'https://api.cloudflare.com/client/v4/accounts/{self.config["account_id"]}'
               f'/r2/buckets/{quote(self.config["bucket"], safe="")}/domains/managed')
        request = Request(url, method='PUT' if enable else 'GET',
                          data=json.dumps({'enabled': True}).encode() if enable else None,
                          headers={'Authorization': f'Bearer {self.config["api_token"]}',
                                   'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ValueError(f'Cloudflare public access request failed (HTTP {exc.code}). '
                             'Check the API token’s R2 permissions and account ID.') from exc
        if result.get('success') is not True:
            raise ValueError('Cloudflare could not configure public access. Check API token permissions.')
        domain = result.get('result', {})
        if domain.get('enabled') is not True or not re.fullmatch(r'[a-zA-Z0-9-]+\.r2\.dev', domain.get('domain') or ''):
            raise ValueError('The bucket’s public r2.dev domain is not enabled')
        self._public_domain = 'https://' + domain['domain']
        return self._public_domain

    def provision(self) -> None:
        self._validate()
        super().provision()
        if self.config.get('public_read') is True:
            self._managed_domain(enable=True)

    def make_public(self, key: str) -> None:
        # R2 has no S3 bucket policies or ACLs; public reads use its managed domain.
        if not self._public_domain:
            self._managed_domain(enable=True)

    def _public_url(self, key: str) -> str:
        base = (self.config.get('public_base_url') or '').rstrip('/')
        if not base and self.config.get('public_read') is True:
            base = self._public_domain or self._managed_domain()
        if base:
            return f'{base}/{quote(key, safe="/")}'
        return self._client().generate_presigned_url('get_object',
            Params={'Bucket': self.config['bucket'], 'Key': key}, ExpiresIn=3600)
