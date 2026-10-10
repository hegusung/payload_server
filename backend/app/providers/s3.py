"""
S3-compatible object storage provider.

One implementation covers AWS S3, Cloudflare R2, MinIO, DigitalOcean Spaces,
and Backblaze B2 — the only difference is the endpoint URL (blank for AWS).
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import quote, urlparse

from app.providers import register
from app.providers.base import ConfigField, DeliveryProvider, DeployResult


@register
class S3Provider(DeliveryProvider):
    key = 's3'
    label = 'S3-compatible (AWS S3 / R2 / MinIO / Spaces / B2)'
    config_fields = [
        ConfigField('bucket', 'Bucket', required=True, placeholder='my-payloads',
                    help='Created automatically when saving if it does not exist.'),
        ConfigField('region', 'Region', required=False, placeholder='us-east-1'),
        ConfigField('endpoint_url', 'Endpoint URL', required=False,
                    placeholder='https://<accountid>.r2.cloudflarestorage.com',
                    help='Leave blank for AWS S3. Set for R2, MinIO, Spaces, B2.'),
        ConfigField('access_key_id', 'Access Key ID', secret=True, required=True),
        ConfigField('secret_access_key', 'Secret Access Key', type='password',
                    secret=True, required=True),
        ConfigField('public_base_url', 'Public base URL', required=False,
                    placeholder='https://cdn.example.com',
                    help='Optional CDN/custom domain used to build the public URL. '
                         'Falls back to the bucket endpoint.'),
        ConfigField('prefix', 'Key prefix', required=False, placeholder='staging/',
                    help='Optional prefix prepended to every object key.'),
        ConfigField('public_read', 'Public downloads (AWS S3)', type='bool', required=False,
                    help='Allow anyone with a deployed file URL to download it. '
                         'Requires permission to update the bucket policy and public access settings.'),
    ]

    def _client(self):
        import boto3
        from botocore.config import Config
        cfg = self.config
        return boto3.client(
            's3',
            region_name=cfg.get('region') or None,
            endpoint_url=cfg.get('endpoint_url') or None,
            aws_access_key_id=cfg.get('access_key_id'),
            aws_secret_access_key=cfg.get('secret_access_key'),
            config=Config(signature_version='s3v4', retries={'max_attempts': 3}),
        )

    def _key_for(self, uri: str) -> str:
        prefix = (self.config.get('prefix') or '').lstrip('/')
        return prefix + uri.lstrip('/')

    def provision(self) -> None:
        from botocore.exceptions import ClientError

        if not (self.config.get('bucket') or '').strip():
            raise ValueError('Bucket name is required')
        client = self._client()
        try:
            client.head_bucket(Bucket=self.config['bucket'])
            return
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') not in ('404', 'NoSuchBucket', 'NotFound'):
                raise
        region = self.config.get('region') or client.meta.region_name or 'us-east-1'
        params = {'Bucket': self.config['bucket']}
        if region != 'us-east-1':
            params['CreateBucketConfiguration'] = {'LocationConstraint': region}
        try:
            client.create_bucket(**params)
        except ClientError as exc:
            # Another request may have created this bucket after the existence check.
            if exc.response.get('Error', {}).get('Code') != 'BucketAlreadyOwnedByYou':
                raise
        client.get_waiter('bucket_exists').wait(Bucket=self.config['bucket'])

    def delete_bucket(self) -> None:
        """Delete only an empty bucket; never empty it implicitly."""
        self._client().delete_bucket(Bucket=self.config['bucket'])

    def make_public(self, key: str) -> None:
        """Grant anonymous reads for this object while preserving existing policy statements."""
        from botocore.exceptions import ClientError

        endpoint = self.config.get('endpoint_url') or ''
        host = urlparse(endpoint).hostname or ''
        if endpoint and not (host.endswith('.amazonaws.com') or host.endswith('.amazonaws.com.cn')):
            raise ValueError('Automatic public downloads are supported for AWS S3 only. '
                             'Configure public access with your storage provider and set Public base URL.')
        if any(char in key for char in '*?'):
            raise ValueError('Public object keys cannot contain policy wildcard characters (* or ?)')
        client = self._client()
        bucket = self.config['bucket']
        try:
            policy = json.loads(client.get_bucket_policy(Bucket=bucket)['Policy'])
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'NoSuchBucketPolicy':
                raise
            policy = {'Version': '2012-10-17', 'Statement': []}
        statements = policy.get('Statement', [])
        if isinstance(statements, dict):
            statements = [statements]
        sid = 'PayloadPublicRead' + hashlib.sha256(key.encode()).hexdigest()
        partition = 'aws-cn' if (client.meta.region_name or '').startswith('cn-') else 'aws'
        statement = {'Sid': sid, 'Effect': 'Allow', 'Principal': '*',
                     'Action': 's3:GetObject', 'Resource': f'arn:{partition}:s3:::{bucket}/{key}'}
        policy['Statement'] = [s for s in statements if s.get('Sid') != sid] + [statement]
        # Permit public bucket policies; ACL-based public access stays blocked.
        client.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
            'BlockPublicAcls': True, 'IgnorePublicAcls': True,
            'BlockPublicPolicy': False, 'RestrictPublicBuckets': False,
        })
        try:
            client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        except ClientError as exc:
            raise ValueError('Could not enable public downloads. Check IAM permissions and '
                             f'account/organization Block Public Access settings: {exc}') from exc

    def _public_url(self, key: str) -> str:
        key = quote(key, safe='/')
        cfg = self.config
        base = (cfg.get('public_base_url') or '').rstrip('/')
        if base:
            return f'{base}/{key}'
        endpoint = (cfg.get('endpoint_url') or '').rstrip('/')
        bucket = cfg.get('bucket')
        if endpoint:
            return f'{endpoint}/{bucket}/{key}'
        region = cfg.get('region') or 'us-east-1'
        host = 's3.amazonaws.com' if region == 'us-east-1' else f's3.{region}.amazonaws.com'
        return f'https://{bucket}.{host}/{key}'

    def deploy(self, uri: str, data: bytes, content_type: str, meta: dict) -> DeployResult:
        key = self._key_for(uri)
        client = self._client()
        put = {
            'Bucket': self.config['bucket'],
            'Key': key,
            'Body': data,
            'ContentType': content_type or 'application/octet-stream',
        }
        if meta.get('dl_filename'):
            put['ContentDisposition'] = f'inline; filename="{meta["dl_filename"]}"'
        client.put_object(**put)
        if self.config.get('public_read') is True:
            self.make_public(key)
        return DeployResult(
            public_url=self._public_url(key),
            ref=key,
            extra={'bucket': self.config['bucket']},
        )

    def delete(self, ref: str) -> None:
        client = self._client()
        client.delete_object(Bucket=self.config['bucket'], Key=ref)

    def list_files(self) -> list[dict]:
        client = self._client()
        files = []
        pages = client.get_paginator('list_objects_v2').paginate(
            Bucket=self.config['bucket'], Prefix=(self.config.get('prefix') or '').lstrip('/'))
        for page in pages:
            for obj in page.get('Contents', []):
                modified = obj.get('LastModified')
                files.append({'ref': obj['Key'], 'size': obj['Size'],
                              'modified_at': modified.isoformat() if modified else None,
                              'url': self._public_url(obj['Key'])})
        return files

    def health(self) -> tuple[bool, str]:
        try:
            client = self._client()
            client.head_bucket(Bucket=self.config['bucket'])
            return True, 'bucket reachable'
        except Exception as e:  # noqa: BLE001 — surface any boto/connection error to the UI
            return False, str(e)
