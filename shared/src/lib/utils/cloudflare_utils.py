#!/usr/bin/env python3

"""
Cloudflare R2 Utilities for VirtualPyTest Resources

Utilities for uploading and downloading files from Cloudflare R2 with public access.

Folder Structure:
- reference-images/{userinterface_id}/{image_name}      # Reference images — keyed by the stable UI id (not name), so renames don't orphan objects
- navigation/{userinterface_name}/{screenshot_name} # Navigation screenshots (public access)
"""

import os
import boto3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List
from urllib.parse import urlparse, unquote
from mimetypes import guess_type
import logging
from botocore.client import Config
from boto3.s3.transfer import TransferConfig

# Force single-part PUTs for everything we upload (report videos cap at 100MB; the proxy allows
# 100M bodies). boto3's default 8MB multipart_threshold splits larger files into part uploads
# (?uploadId&partNumber=…) which the proxy drops with SSL EOF; a single PUT goes through cleanly.
_SINGLE_PART_TRANSFER = TransferConfig(
    multipart_threshold=256 * 1024 * 1024,
    multipart_chunksize=256 * 1024 * 1024,
)
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from botocore.exceptions import SSLError as BotoSSLError
from concurrent.futures import ThreadPoolExecutor, as_completed
import ssl
import time

# Transient network/TLS errors worth retrying once. Things like SSLV3_ALERT_BAD_RECORD_MAC
# (a TLS-record bit-flip in transit) are surfaced as botocore SSLError; connection-reset
# and read-timeout flakes show up as the others. Permanent errors (ClientError 413,
# NoSuchBucket, AccessDenied) deliberately do NOT retry.
_TRANSIENT_UPLOAD_EXCEPTIONS = (
    BotoSSLError,
    ssl.SSLError,
    EndpointConnectionError,
    ConnectionClosedError,
    ReadTimeoutError,
    ConnectionResetError,
    TimeoutError,
)
# The proxy intermittently drops larger uploads mid-stream with "SSLError ... EOF in violation
# of protocol" — it's flaky, not size-deterministic (a 30MB PUT can succeed while a 14MB one
# fails on the same config). Each retry is an independent fresh connection, so several attempts
# make a successful upload overwhelmingly likely. Single-part PUTs (see _SINGLE_PART_TRANSFER)
# make each attempt atomic and cleanly retryable.
_UPLOAD_MAX_ATTEMPTS = 5

# Configure module-specific logging (avoid global basicConfig)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Only add handler if not already present (avoid duplicate handlers)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[@cloudflare_utils:%(funcName)s] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False  # Prevent propagation to root logger

# R2 rejects presigned URLs with X-Amz-Expires >= 604800 seconds (7 days).
# Use a safe ceiling of 604799s to stay under the limit.
MAX_R2_PRESIGN_EXPIRY = 604_799


def normalize_storage_key(path: str, current_bucket_name: str = '') -> str:
    """Normalize storage object paths before signing."""
    normalized = (path or '').lstrip('/')
    bucket_prefix = current_bucket_name.strip('/') if current_bucket_name else ''
    if bucket_prefix and normalized.startswith(f'{bucket_prefix}/'):
        normalized = normalized[len(bucket_prefix) + 1:]

    return normalized

class CloudflareUtils:
    """
    Singleton Cloudflare R2 utility for VirtualPyTest resources.
    Upload and download files and get signed URLs.
    
    This class implements the singleton pattern to ensure only one instance
    exists throughout the application lifecycle, avoiding multiple S3 client
    initializations.
    
    Configuration:
    - Environment variables should be loaded by the main application (app_utils.load_environment_variables)
    - Requires: CLOUDFLARE_R2_ENDPOINT, CLOUDFLARE_R2_ACCESS_KEY_ID, CLOUDFLARE_R2_SECRET_ACCESS_KEY
    - Endpoint URL should NOT include bucket name (e.g., https://account.r2.cloudflarestorage.com)
    - Bucket name is passed separately to boto3 operations
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """Singleton pattern implementation - only create one instance."""
        if cls._instance is None:
            logger.info("Creating new CloudflareUtils singleton instance")
            cls._instance = super().__new__(cls)
        else:
            logger.debug("Returning existing CloudflareUtils singleton instance")
        return cls._instance
    
    def __init__(self):
        """Initialize the utility (only once due to singleton)."""
        # Prevent re-initialization of the singleton instance
        if self._initialized:
            return
            
        logger.info("Initializing CloudflareUtils singleton")

        self.s3_client, self.bucket_name = self._init_s3_client()
        self.presign_client = self._init_presign_client()
        self._initialized = True

    def _init_s3_client(self):
        """Initialize S3 client for Cloudflare R2 or Local MinIO."""
        try:
            # Check if R2 is configured, otherwise fall back to local MinIO
            r2_endpoint = os.environ.get('CLOUDFLARE_R2_ENDPOINT')
            r2_access_key = os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID')
            r2_secret_key = os.environ.get('CLOUDFLARE_R2_SECRET_ACCESS_KEY')

            # Local MinIO configuration (from install_storage.sh)
            minio_endpoint = os.environ.get('MINIO_ENDPOINT', 'http://localhost:9000')
            minio_access_key = os.environ.get('MINIO_ACCESS_KEY', 'admin')
            minio_secret_key = os.environ.get('MINIO_SECRET_KEY', 'admin1234')

            # Determine which storage backend to use
            if all([r2_endpoint, r2_access_key, r2_secret_key]):
                # Use Cloudflare R2
                endpoint_url = r2_endpoint
                access_key = r2_access_key
                secret_key = r2_secret_key
                region = 'auto'  # Required for Cloudflare R2
                bucket_name = os.environ.get('CLOUDFLARE_R2_BUCKET', 'virtualpytest')
                logger.info("Initializing S3 client for Cloudflare R2")
            else:
                # Use local MinIO
                endpoint_url = minio_endpoint
                access_key = minio_access_key
                secret_key = minio_secret_key
                region = 'us-east-1'  # Default for MinIO
                bucket_name = os.environ.get('MINIO_BUCKET', 'virtualpytest')
                logger.info("Initializing S3 client for Local MinIO")

            logger.info(f"Using endpoint: {endpoint_url}")
            logger.info(f"Using bucket: {bucket_name}")

            # Configure timeouts (more aggressive for local MinIO, standard for R2)
            if r2_endpoint:
                # Cloudflare R2 configuration
                config = Config(
                    signature_version='s3v4',
                    connect_timeout=5,
                    read_timeout=10,
                    retries={
                        'max_attempts': 2,
                        'mode': 'standard'
                    }
                )
            else:
                # MinIO via the public proxy (MINIO_ENDPOINT is usually the remote
                # virtualpytest.angelstreet.io, NOT a local MinIO). A 5s read timeout was fine
                # for tiny screenshots but fails large/long-test report videos: a ~14MB+ body
                # from a remote host (e.g. a Raspberry Pi) can block a socket op >5s under TCP
                # backpressure mid-upload, surfacing as "SSLError ... EOF in violation of
                # protocol". 60s gives multi-MB uploads (videos up to the 100MB cap) headroom;
                # it's a max-wait, so small uploads are unaffected.
                config = Config(
                    signature_version='s3v4',
                    connect_timeout=10,
                    read_timeout=60,
                    retries={
                        'max_attempts': 2,
                        'mode': 'standard'
                    }
                )

            client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=config
            )
            return client, bucket_name

        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {str(e)}")
            raise

    def _init_presign_client(self):
        """Initialize a separate S3 client for presigned URL generation.

        When MINIO_PRESIGN_ENDPOINT is set, presigned URLs will use this public-facing
        endpoint so browsers can access them directly. The main s3_client keeps using
        the internal endpoint for uploads and other operations.
        """
        presign_endpoint = os.environ.get('MINIO_PRESIGN_ENDPOINT', '').strip()
        if not presign_endpoint:
            return None  # Use self.s3_client for presigning

        r2_endpoint = os.environ.get('CLOUDFLARE_R2_ENDPOINT')
        if r2_endpoint:
            return None  # R2 doesn't need a separate presign client

        logger.info(f"Initializing separate presign client for: {presign_endpoint}")
        minio_access_key = os.environ.get('MINIO_ACCESS_KEY', 'admin')
        minio_secret_key = os.environ.get('MINIO_SECRET_KEY', 'admin1234')
        config = Config(
            signature_version='s3v4',
            connect_timeout=2,
            read_timeout=5,
            retries={'max_attempts': 1, 'mode': 'standard'}
        )
        return boto3.client(
            's3',
            endpoint_url=presign_endpoint,
            aws_access_key_id=minio_access_key,
            aws_secret_access_key=minio_secret_key,
            region_name='us-east-1',
            config=config
        )

    def upload_files(self, file_mappings: List[Dict], max_workers: int = 10, auto_delete_cold: bool = True, for_report_assets: bool = False) -> Dict:
        """
        Upload files concurrently.
        
        Args:
            file_mappings: List of dicts with 'local_path' and 'remote_path' keys
            max_workers: Max concurrent uploads
            auto_delete_cold: Whether to delete cold storage files after upload
            for_report_assets: If True, return URLs suitable for HTML reports (14-day signed URLs in private mode)
            Optional 'content_type' key to override auto-detection
            max_workers: Maximum number of concurrent upload threads
            auto_delete_cold: If True, automatically delete files from cold storage after successful upload
            
        Returns:
            Dict with upload results
        """
        uploaded_files = []
        failed_uploads = []
        deleted_files = []

        # Report assets are SHARED, durable cold copies (e.g. a capture frame that
        # is both a step screenshot in the script report AND a KPI before/after
        # thumbnail). Whoever uploads first must NOT delete the cold source, or the
        # other consumer's report-build upload finds it gone and falls back to a
        # broken local path. The archiver's cold TTL (~1h) reclaims them instead.
        # Concretely fixed the broken step-screenshot when the KPI report (separate
        # vpt-kpi service, processed late on long/reboot windows) uploaded+deleted
        # `before_action` = the same cold frame the script's step report referenced.
        if for_report_assets and auto_delete_cold:
            auto_delete_cold = False

        # Deduplicate file_mappings by local_path to prevent race conditions
        # Keep first occurrence of each unique local_path
        seen_paths = {}
        deduplicated_mappings = []
        duplicate_count = 0
        
        for mapping in file_mappings:
            local_path = mapping['local_path']
            if local_path not in seen_paths:
                seen_paths[local_path] = mapping
                deduplicated_mappings.append(mapping)
            else:
                duplicate_count += 1
                # Log duplicate for debugging - helps identify the source
                logger.debug(f"Skipping duplicate upload request for {local_path} (remote: {mapping['remote_path']})")
        
        if duplicate_count > 0:
            logger.info(f"Deduplicated {duplicate_count} duplicate file(s) from upload batch (original: {len(file_mappings)}, unique: {len(deduplicated_mappings)})")
        
        # Use deduplicated mappings for upload
        file_mappings = deduplicated_mappings
        
        def upload_single_file(mapping):
            local_path = mapping['local_path']
            remote_path = mapping['remote_path']
            custom_content_type = mapping.get('content_type')
            
            try:
                if not os.path.exists(local_path):
                    return {
                        'success': False,
                        'local_path': local_path,
                        'remote_path': remote_path,
                        'error': f"File not found: {local_path}"
                    }
                
                # Use custom content type if provided, otherwise auto-detect
                if custom_content_type:
                    content_type = custom_content_type
                else:
                    content_type, _ = guess_type(local_path)
                    if not content_type:
                        content_type = 'application/octet-stream'
                
                # NOTE: do NOT attach x-amz-meta-* headers via ExtraArgs.Metadata.
                # boto3 turns underscore-named keys into "x-amz-meta-foo_bar" headers,
                # which Cloudflare/nginx normalize or drop in transit. The receiver
                # then sees a canonical request that no longer matches the signature
                # boto3 computed → MinIO returns 403 "headers present in the request
                # which were not signed". Capture time is tracked elsewhere (filename
                # mtime + DB rows) so it's not load-bearing on the upload itself.
                extra_args = {'ContentType': content_type}
                
                file_size = os.path.getsize(local_path)

                last_transient_exc = None
                for attempt in range(1, _UPLOAD_MAX_ATTEMPTS + 1):
                    try:
                        with open(local_path, 'rb') as f:
                            self.s3_client.upload_fileobj(
                                f,
                                self.bucket_name,
                                remote_path,
                                ExtraArgs=extra_args,
                                Config=_SINGLE_PART_TRANSFER
                            )
                        last_transient_exc = None
                        break
                    except _TRANSIENT_UPLOAD_EXCEPTIONS as transient_exc:
                        last_transient_exc = transient_exc
                        if attempt < _UPLOAD_MAX_ATTEMPTS:
                            logger.warning(
                                f"Transient upload error for {remote_path} "
                                f"(attempt {attempt}/{_UPLOAD_MAX_ATTEMPTS}): {transient_exc}. Retrying."
                            )
                            time.sleep(0.5 * attempt)
                if last_transient_exc is not None:
                    raise last_transient_exc
                
                # Get URL based on use case
                if for_report_assets:
                    # Report assets need long-lived URLs (14-day signed URLs in private mode)
                    file_url = self.get_url_for_report_asset(remote_path)
                else:
                    # Normal uploads use public URL or path
                    file_url = self.get_public_url(remote_path)
                
                result = {
                    'success': True,
                    'local_path': local_path,
                    'remote_path': remote_path,
                    'url': file_url,
                    'size': file_size,
                    'deleted': False
                }
                
                # Auto-delete from cold storage after successful upload
                # Only delete if file is in cold storage (not hot) and contains "capture_" or "thumbnail"
                if auto_delete_cold:
                    is_cold_file = (
                        ('/captures/' in local_path or '/thumbnails/' in local_path) and
                        '/hot/' not in local_path and
                        ('capture_' in os.path.basename(local_path) or 'thumbnail' in os.path.basename(local_path))
                    )
                    
                    if is_cold_file:
                        try:
                            # Check if file still exists before attempting deletion (race condition safety)
                            if os.path.exists(local_path):
                                os.remove(local_path)
                                result['deleted'] = True
                                logger.debug(f"Auto-deleted cold file after upload: {local_path}")
                            else:
                                logger.debug(f"Cold file already deleted (likely by another process): {local_path}")
                        except FileNotFoundError:
                            # File was deleted between the exists check and remove call
                            logger.debug(f"Cold file already deleted during removal: {local_path}")
                        except Exception as del_error:
                            logger.warning(f"Failed to auto-delete cold file {local_path}: {del_error}")
                
                return result
                
            except Exception as e:
                return {
                    'success': False,
                    'local_path': local_path,
                    'remote_path': remote_path,
                    'error': str(e)
                }
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(upload_single_file, mapping) for mapping in file_mappings]
            
            for future in as_completed(futures):
                result = future.result()
                
                if result['success']:
                    uploaded_files.append(result)
                    if result.get('deleted'):
                        deleted_files.append(result['local_path'])
                else:
                    failed_uploads.append(result)
        
        response = {
            'success': len(failed_uploads) == 0,
            'uploaded_count': len(uploaded_files),
            'failed_count': len(failed_uploads),
            'uploaded_files': uploaded_files,
            'failed_uploads': failed_uploads
        }
        
        if deleted_files:
            response['deleted_count'] = len(deleted_files)
            response['deleted_files'] = deleted_files
            logger.info(f"Auto-deleted {len(deleted_files)} cold storage files after upload")
        
        return response
    
    def download_file(self, remote_path: str, local_path: str) -> Dict:
        """
        Download a file from R2.
        
        Args:
            remote_path: Path in R2 (e.g., 'reference/android_mobile/default_capture.png')
            local_path: Path to save the file locally
            
        Returns:
            Dict with success status, local file path, and ETag
        """
        start_time = time.time()
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            logger.debug(f"Starting download: {remote_path}")
            
            # Download file using bucket name and get response metadata
            # With config timeouts: connect_timeout=5s, read_timeout=10s, max 2 attempts
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=remote_path
            )
            
            fetch_time = time.time() - start_time
            if fetch_time > 1.0:
                logger.warning(f"Slow R2 fetch: {remote_path} took {fetch_time:.2f}s to get response")
            
            # Write file content
            with open(local_path, 'wb') as f:
                f.write(response['Body'].read())
            
            write_time = time.time() - start_time - fetch_time
            total_time = time.time() - start_time
            
            # Extract ETag from response metadata
            etag = response.get('ETag', '').strip('"')
            file_size = os.path.getsize(local_path)
            
            # Log with timing details
            if total_time > 2.0:
                logger.warning(f"Downloaded: {remote_path} -> {local_path} (ETag: {etag[:8]}...) - SLOW: {total_time:.2f}s (fetch: {fetch_time:.2f}s, write: {write_time:.2f}s, size: {file_size} bytes)")
            else:
                logger.info(f"Downloaded: {remote_path} -> {local_path} (ETag: {etag[:8]}...) - {total_time:.2f}s ({file_size} bytes)")
            
            return {
                'success': True,
                'remote_path': remote_path,
                'local_path': local_path,
                'size': file_size,
                'etag': etag,
                'download_time': total_time
            }
            
        except ClientError as e:
            elapsed = time.time() - start_time
            if e.response['Error']['Code'] == '404':
                logger.error(f"File not found in R2: {remote_path} (failed after {elapsed:.2f}s)")
                return {'success': False, 'error': f"File not found in R2: {remote_path}"}
            else:
                logger.error(f"Download failed: {str(e)} (failed after {elapsed:.2f}s)")
                return {'success': False, 'error': str(e)}
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Download failed: {str(e)} (failed after {elapsed:.2f}s)")
            return {'success': False, 'error': str(e)}
    
    def head_file(self, remote_path: str) -> Dict:
        """
        Get file metadata from R2 without downloading (HTTP HEAD request).
        Useful for checking if file changed (via ETag) or getting Last-Modified date.
        
        Args:
            remote_path: Path in R2 (e.g., 'reference-images/example_tv/apps_oneplus.jpg')
            
        Returns:
            Dict with success status, etag, last_modified, and content_length
        """
        start_time = time.time()
        try:
            # HEAD request with same timeout config as downloads (5s connect, 10s read)
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=remote_path
            )
            
            elapsed = time.time() - start_time
            
            etag = response.get('ETag', '').strip('"')
            last_modified = response.get('LastModified')
            content_length = response.get('ContentLength', 0)
            
            if elapsed > 1.0:
                logger.warning(f"HEAD: {remote_path} (ETag: {etag[:8]}..., Size: {content_length} bytes) - SLOW: {elapsed:.2f}s")
            else:
                logger.debug(f"HEAD: {remote_path} (ETag: {etag[:8]}..., Size: {content_length} bytes) - {elapsed:.2f}s")
            
            return {
                'success': True,
                'etag': etag,
                'last_modified': last_modified,
                'content_length': content_length,
                'request_time': elapsed
            }
            
        except ClientError as e:
            elapsed = time.time() - start_time
            if e.response['Error']['Code'] == '404':
                logger.error(f"File not found in R2: {remote_path} (failed after {elapsed:.2f}s)")
                return {'success': False, 'error': f"File not found in R2: {remote_path}"}
            else:
                logger.error(f"HEAD request failed: {str(e)} (failed after {elapsed:.2f}s)")
                return {'success': False, 'error': str(e)}
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"HEAD request failed: {str(e)} (failed after {elapsed:.2f}s)")
            return {'success': False, 'error': str(e)}
    
    def copy_file(self, source_path: str, destination_path: str) -> Dict:
        """
        Copy a file within R2 storage (server-side copy).
        
        Args:
            source_path: Source path in R2 (e.g., 'navigation/android_mobile/Home.jpg')
            destination_path: Destination path in R2 (e.g., 'navigation/example_mobile/Home.jpg')
            
        Returns:
            Dict with success status and new file URL
        """
        try:
            # Use S3 copy_object for efficient server-side copy
            copy_source = {
                'Bucket': self.bucket_name,
                'Key': source_path
            }
            
            self.s3_client.copy_object(
                CopySource=copy_source,
                Bucket=self.bucket_name,
                Key=destination_path
            )
            
            new_url = self.get_public_url(destination_path)
            
            logger.info(f"Copied in R2: {source_path} -> {destination_path}")
            
            return {
                'success': True,
                'source_path': source_path,
                'destination_path': destination_path,
                'url': new_url
            }
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.error(f"Source file not found in R2: {source_path}")
                return {'success': False, 'error': f"Source file not found: {source_path}"}
            else:
                logger.error(f"Copy failed: {str(e)}")
                return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"Copy failed: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def is_public_mode(self) -> bool:
        """
        Check if public URL mode is enabled.

        Returns:
            True if public URL env var is set (R2 or MinIO)
            False if private mode (use signed URLs)
        """
        r2_endpoint = os.environ.get('CLOUDFLARE_R2_ENDPOINT')
        if r2_endpoint:
            # R2: check if public URL is configured
            return bool(os.environ.get('CLOUDFLARE_R2_PUBLIC_URL', '').strip())
        else:
            # MinIO: check if public URL is configured
            return bool(os.environ.get('MINIO_PUBLIC_URL', '').strip())
    
    def get_file_url_or_path(self, remote_path: str) -> str:
        """
        Get the appropriate reference for a file in R2.
        
        In PUBLIC mode (CLOUDFLARE_R2_PUBLIC_URL is set):
            Returns full public URL: https://pub-xxx.r2.dev/captures/file.jpg
        
        In PRIVATE mode (CLOUDFLARE_R2_PUBLIC_URL is NOT set):
            Returns just the path: captures/file.jpg
            (Frontend will use this path to request signed URLs)
        
        Args:
            remote_path: Path in R2 (e.g., 'captures/device1/screenshot.jpg')
            
        Returns:
            Full public URL (public mode) or just the path (private mode)
        """
        public_url_base = os.environ.get('CLOUDFLARE_R2_PUBLIC_URL', '').strip()
        
        if public_url_base:
            # PUBLIC MODE: Return full URL
            base_url = public_url_base.rstrip('/')
            return f"{base_url}/{remote_path}"
        else:
            # PRIVATE MODE: Return just the path
            # Frontend will use this to request signed URLs from backend
            logger.debug(f"Private mode: returning path only for {remote_path}")
            return remote_path
    
    def get_public_url(self, remote_path: str) -> str:
        """
        Get a public URL for a file in R2 or MinIO.

        DEPRECATED: Use get_file_url_or_path() instead for mode-aware behavior.
        This method is kept for backwards compatibility.

        Args:
            remote_path: Path in storage

        Returns:
            Public URL string (if public mode) or path (if private mode)
        """
        # Check if using local MinIO
        r2_endpoint = os.environ.get('CLOUDFLARE_R2_ENDPOINT')
        if not r2_endpoint:
            minio_public_url = os.environ.get('MINIO_PUBLIC_URL', '').strip()
            if minio_public_url:
                # Public URL configured (e.g., https://domain.com/minio)
                return f"{minio_public_url.rstrip('/')}/{self.bucket_name}/{remote_path.lstrip('/')}"
            else:
                # MinIO private mode — return path only (frontend will request signed URL)
                logger.debug(f"MinIO private mode: returning path only for {remote_path}")
                return remote_path

        # Delegate to new mode-aware method for R2
        return self.get_file_url_or_path(remote_path)
    
    def get_url_for_report_asset(self, remote_path: str) -> str:
        """
        Get URL for assets embedded in HTML reports (screenshots, videos).

        In PUBLIC mode: Returns public URL
        In PRIVATE mode: Returns signed URL with 14-day expiry

        This is specifically for HTML reports where we need working URLs
        that last longer than the typical 1-hour signed URL expiry.

        Args:
            remote_path: Path in R2 (e.g., 'script-reports/device/report/screenshot.jpg')

        Returns:
            URL string that works for 14 days (public URL or long-expiry signed URL)
        """
        # Check if using MinIO (no Cloudflare R2 endpoint)
        r2_endpoint = os.environ.get('CLOUDFLARE_R2_ENDPOINT')
        if not r2_endpoint:
            minio_public_url = os.environ.get('MINIO_PUBLIC_URL', '').strip()
            if minio_public_url:
                return f"{minio_public_url.rstrip('/')}/{self.bucket_name}/{remote_path.lstrip('/')}"
            else:
                # MinIO private mode — generate presigned URL for report assets
                result = self.generate_presigned_url(remote_path, expires_in=MAX_R2_PRESIGN_EXPIRY)
                if result.get('success'):
                    logger.debug(f"Generated long-expiry signed URL for MinIO report asset: {remote_path}")
                    return result['url']
                logger.warning(f"Failed to generate signed URL for {remote_path}, using path")
                return remote_path

        if self.is_public_mode():
            # PUBLIC MODE: Return full public URL
            public_url_base = os.environ.get('CLOUDFLARE_R2_PUBLIC_URL', '').strip()
            base_url = public_url_base.rstrip('/')
            return f"{base_url}/{remote_path}"
        else:
            # PRIVATE MODE: Return signed URL capped at R2 max (must be < 604800s)
            result = self.generate_presigned_url(remote_path, expires_in=MAX_R2_PRESIGN_EXPIRY)

            if result.get('success'):
                logger.debug(f"Generated 14-day signed URL for report asset: {remote_path}")
                return result['url']
            else:
                # Fallback to path (will fail in browser but at least report generates)
                logger.warning(f"Failed to generate signed URL for {remote_path}, using path")
                return remote_path
    
    def generate_presigned_url(self, remote_path: str, expires_in: int = 3600) -> Dict:
        """
        Generate a pre-signed URL for secure, time-limited access to a private R2 file.
        
        This method creates a cryptographically signed URL that grants temporary access
        to a file in a private R2 bucket. The URL includes authentication parameters
        that R2 validates, eliminating the need for the bucket to be public.
        
        Args:
            remote_path: Path in R2 (e.g., 'captures/device1/capture_123.jpg')
            expires_in: URL expiration time in seconds (default: 3600 = 1 hour)
                       Common values: 1800 (30min), 3600 (1hr), 7200 (2hr), 86400 (24hr)
        
        Returns:
            Dict with:
                - success: bool - Whether URL generation succeeded
                - url: str - Pre-signed URL (if success=True)
                - expires_in: int - Seconds until expiration
                - expires_at: str - ISO timestamp of expiration
                - error: str - Error message (if success=False)
        
        Example:
            result = uploader.generate_presigned_url('verification/test.jpg', expires_in=7200)
            if result['success']:
                url = result['url']  # Valid for 2 hours
                # URL format: https://account.r2.cloudflarestorage.com/bucket/file.jpg?
                #             X-Amz-Algorithm=AWS4-HMAC-SHA256&
                #             X-Amz-Credential=...&
                #             X-Amz-Date=...&
                #             X-Amz-Expires=7200&
                #             X-Amz-SignedHeaders=host&
                #             X-Amz-Signature=...
        
        Notes:
            - Works with both public and private buckets
            - No API call to R2 - URL generated locally using credentials
            - URL can be cached until near expiration (save backend calls)
            - Free operation (no R2 API charges)
            - Requires CLOUDFLARE_R2_ACCESS_KEY_ID and SECRET_ACCESS_KEY
        """
        try:
            if not self.s3_client:
                logger.error("S3 client not initialized")
                return {
                    'success': False,
                    'error': 'R2 client not initialized'
                }
            
            clean_remote_path = normalize_storage_key(remote_path, self.bucket_name)
            
            # Use presign_client (public endpoint) if available, else s3_client
            client = self.presign_client or self.s3_client
            presigned_url = client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': clean_remote_path
                },
                ExpiresIn=expires_in
            )
            
            # Calculate expiration timestamp
            from datetime import datetime, timedelta
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            logger.info(f"Generated pre-signed URL for {remote_path} (expires in {expires_in}s)")
            
            return {
                'success': True,
                'url': presigned_url,
                'expires_in': expires_in,
                'expires_at': expires_at.isoformat() + 'Z',
                'remote_path': remote_path
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            logger.error(f"Failed to generate pre-signed URL for {remote_path}: {error_code} - {error_msg}")
            return {
                'success': False,
                'error': f"R2 error: {error_code} - {error_msg}"
            }
        except Exception as e:
            logger.error(f"Failed to generate pre-signed URL for {remote_path}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def generate_presigned_urls_batch(self, remote_paths: List[str], expires_in: int = 3600) -> Dict:
        """
        Generate multiple pre-signed URLs in a single call (for efficiency).
        
        Args:
            remote_paths: List of R2 paths
            expires_in: URL expiration time in seconds (default: 3600 = 1 hour)
        
        Returns:
            Dict with:
                - success: bool - Whether all URLs generated successfully
                - urls: List[Dict] - List of {path, url, expires_at} for successful URLs
                - failed: List[Dict] - List of {path, error} for failed URLs
                - generated_count: int
                - failed_count: int
        
        Example:
            paths = ['capture1.jpg', 'capture2.jpg', 'capture3.jpg']
            result = uploader.generate_presigned_urls_batch(paths, expires_in=3600)
            for item in result['urls']:
                print(f"{item['path']} -> {item['url']}")
        """
        urls = []
        failed = []
        
        for remote_path in remote_paths:
            result = self.generate_presigned_url(remote_path, expires_in)
            
            if result['success']:
                urls.append({
                    'path': remote_path,
                    'url': result['url'],
                    'expires_at': result['expires_at'],
                    'expires_in': expires_in
                })
            else:
                failed.append({
                    'path': remote_path,
                    'error': result.get('error', 'Unknown error')
                })
        
        logger.info(f"Generated {len(urls)}/{len(remote_paths)} pre-signed URLs (batch)")
        
        return {
            'success': len(failed) == 0,
            'urls': urls,
            'failed': failed,
            'generated_count': len(urls),
            'failed_count': len(failed)
        }
    
    def delete_file(self, remote_path: str) -> bool:
        """Delete a file from R2."""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=remote_path)
            logger.info(f"Deleted: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"Delete failed: {str(e)}")
            return False

    def delete_prefix(self, prefix: str) -> Dict:
        """Delete every object under a key prefix (i.e. a whole "folder").

        Paginates list_objects_v2 and batch-deletes each page (delete_objects
        caps at 1000 keys/call; a paginator page is already <= 1000, so one
        batch per page is safe). Returns {'success', 'deleted', 'error'?}.
        """
        prefix = (prefix or '').lstrip('/')
        if not prefix:
            return {'success': False, 'deleted': 0, 'error': 'empty prefix'}
        try:
            deleted = 0
            paginator = self.s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                objs = [{'Key': o['Key']} for o in page.get('Contents', [])]
                if not objs:
                    continue
                self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': objs, 'Quiet': True},
                )
                deleted += len(objs)
            logger.info(f"Deleted prefix '{prefix}': {deleted} object(s)")
            return {'success': True, 'deleted': deleted}
        except Exception as e:
            logger.error(f"delete_prefix('{prefix}') failed: {str(e)}")
            return {'success': False, 'deleted': 0, 'error': str(e)}
    
    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists in R2."""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=remote_path)
            return True
        except ClientError:
            return False
    
    def test_connection(self) -> Dict:
        """Test the R2 connection and return diagnostic information."""
        try:
            # Test 1: List buckets
            response = self.s3_client.list_buckets()
            bucket_names = [bucket['Name'] for bucket in response['Buckets']]
            
            # Test 2: Check if our target bucket exists
            bucket_exists = self.bucket_name in bucket_names
            
            # Test 3: Try to access the bucket
            can_access_bucket = False
            try:
                self.s3_client.head_bucket(Bucket=self.bucket_name)
                can_access_bucket = True
            except Exception as e:
                logger.error(f"Cannot access bucket: {e}")
            
            return {
                'success': True,
                'buckets_found': len(bucket_names),
                'bucket_names': bucket_names,
                'target_bucket_exists': bucket_exists,
                'can_access_bucket': can_access_bucket,
                'endpoint': os.environ.get('CLOUDFLARE_R2_ENDPOINT', 'NOT_SET'),
                'bucket_name': self.bucket_name
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'endpoint': os.environ.get('CLOUDFLARE_R2_ENDPOINT', 'NOT_SET'),
            }

    def resolve_remote_path(self, url_or_path: str) -> str:
        """
        Resolve an object key from either a storage URL or a direct path.

        Supports:
        - direct keys (e.g. script-logs/dev/file.txt)
        - MinIO URLs (public or endpoint URLs)
        - Cloudflare R2 public URLs
        - Cloudflare/MinIO signed URLs
        """
        if not url_or_path:
            return ""

        value = str(url_or_path).strip()
        if not value:
            return ""

        # Start with raw value for direct paths, or URL path for full URLs.
        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            path = unquote(parsed.path or "").lstrip("/")
        else:
            path = value.lstrip("/")

        if not path:
            return ""

        # Remove known base path prefixes from configured endpoints/public URLs.
        env_base_urls = [
            os.environ.get("MINIO_PUBLIC_URL", "").strip(),
            os.environ.get("MINIO_ENDPOINT", "").strip(),
            os.environ.get("CLOUDFLARE_R2_PUBLIC_URL", "").strip(),
            os.environ.get("CLOUDFLARE_R2_ENDPOINT", "").strip(),
        ]
        for base_url in env_base_urls:
            if not base_url:
                continue
            base_path = urlparse(base_url).path.strip("/")
            if base_path and path.startswith(f"{base_path}/"):
                path = path[len(base_path) + 1:]
                break

        # Remove bucket prefix if present.
        bucket_prefix = f"{self.bucket_name}/"
        if path.startswith(bucket_prefix):
            path = path[len(bucket_prefix):]
        else:
            # Also support prefixed paths like /minio/<bucket>/key or /proxy/x/<bucket>/key.
            parts = [p for p in path.split("/") if p]
            if self.bucket_name in parts:
                bucket_idx = parts.index(self.bucket_name)
                if bucket_idx < len(parts) - 1:
                    path = "/".join(parts[bucket_idx + 1:])
                else:
                    path = ""

        return path

    def read_text_file(self, url_or_path: str, encoding: str = "utf-8") -> Dict:
        """Read text content from storage by URL or direct object path."""
        remote_path = self.resolve_remote_path(url_or_path)
        if not remote_path:
            return {
                "success": False,
                "error": "Could not resolve storage path",
                "remote_path": "",
            }

        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=remote_path)
            body = response["Body"].read()
            text = body.decode(encoding, errors="replace")
            return {
                "success": True,
                "text": text,
                "remote_path": remote_path,
            }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            return {
                "success": False,
                "error": f"{error_code}: {error_msg}",
                "remote_path": remote_path,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "remote_path": remote_path,
            }

# Singleton getter function
def get_cloudflare_utils() -> CloudflareUtils:
    """Get the singleton instance of CloudflareUtils."""
    return CloudflareUtils()

def delete_userinterface_storage(userinterface_id: str, userinterface_name: str = None) -> Dict:
    """Remove every bucket object owned by a userinterface.

    Called when a userinterface is deleted so its reference/navigation folders
    don't orphan in R2/MinIO. Two prefixes (see the module folder-structure doc):
      - reference-images/{userinterface_id}/   reference images (stable-id keyed,
                                               incl. greyscale/binary derivatives
                                               and the history/ version snapshots)
      - navigation/{userinterface_name}/       navigation screenshots (name keyed)

    Best-effort: returns a summary dict and never raises, so a storage hiccup
    can't block the DB delete (the DB is the source of truth).
    """
    uploader = get_cloudflare_utils()
    details = {}
    total = 0
    if userinterface_id:
        r = uploader.delete_prefix(f"reference-images/{userinterface_id}/")
        details['reference_images'] = r
        total += r.get('deleted', 0)
    if userinterface_name:
        r = uploader.delete_prefix(f"navigation/{userinterface_name}/")
        details['navigation'] = r
        total += r.get('deleted', 0)
    return {
        'success': all(v.get('success') for v in details.values()) if details else True,
        'deleted': total,
        'details': details,
    }

def convert_to_signed_url(url_or_path: str) -> str:
    """
    Convert R2 URL or path to signed URL. Simple utility like frontend's getR2Url.

    Args:
        url_or_path: R2 URL or path, supports:
            - Full URLs: 'https://pub-xxx.r2.dev/path/file.jpg', 'https://xxx.r2.cloudflarestorage.com/bucket/path/file.jpg'
            - R2 paths: 'script-reports/device/report/file.jpg', 'navigation/ui/screenshot.jpg', 'audio-analysis/file.wav'
            - MinIO public URLs: returned as-is (no signing needed for public bucket)

    Returns:
        Signed URL (returns original on error)
    """
    if not url_or_path:
        return url_or_path

    # If URL is already a MinIO public URL, return as-is (bucket is public, no signing needed)
    minio_public_url = os.environ.get('MINIO_PUBLIC_URL', '').strip()
    if minio_public_url and minio_public_url in url_or_path:
        return url_or_path

    # Known R2 path prefixes that should be signed
    R2_PATH_PREFIXES = (
        'script-reports/',
        'navigation/',
        'reference-images/',
        'audio-analysis/',
        'kpi_measurement/',
        'heatmaps/',
        'restart-reports/',
        'script-logs/',
        'alerts/',
    )
    
    presign_endpoint = os.environ.get('MINIO_PRESIGN_ENDPOINT', '').strip().rstrip('/')

    # Check if this is a full storage URL or a known storage path
    is_r2_url = 'r2.dev' in url_or_path or 'r2.cloudflarestorage.com' in url_or_path
    is_minio_presign_url = bool(presign_endpoint) and url_or_path.startswith(presign_endpoint + '/')
    is_r2_path = url_or_path.startswith(R2_PATH_PREFIXES)
    
    if not is_r2_url and not is_minio_presign_url and not is_r2_path:
        return url_or_path
    
    try:
        if is_r2_url or is_minio_presign_url:
            # Parse full URL to extract path
            from urllib.parse import urlparse
            parsed = urlparse(url_or_path)
            r2_path = parsed.path.lstrip('/')
            
        else:
            # Already a path, use directly
            r2_path = url_or_path.lstrip('/')

        uploader = get_cloudflare_utils()

        r2_path = normalize_storage_key(r2_path, uploader.bucket_name)
        result = uploader.generate_presigned_url(r2_path, expires_in=MAX_R2_PRESIGN_EXPIRY)
        return result['url'] if result.get('success') else url_or_path
    except Exception as e:
        logger.warning(f"Failed to convert to signed URL: {e}")
        return url_or_path


def fetch_text_from_storage(url_or_path: str, encoding: str = "utf-8") -> Dict:
    """
    Fetch UTF-8 text from storage (R2/MinIO) using shared helper logic.

    Args:
        url_or_path: Storage URL or object path.
        encoding: Text encoding to use while decoding bytes.

    Returns:
        Dict with:
            - success: bool
            - text: decoded text (on success)
            - remote_path: resolved object key
            - error: error details (on failure)
    """
    try:
        helper = get_cloudflare_utils()
        return helper.read_text_file(url_or_path, encoding=encoding)
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "remote_path": "",
        }

# Utility functions for common upload patterns

def upload_reference_image(local_path: str, ui_folder: str, image_name: str) -> Dict:
    """
    Upload a reference image to R2 under reference-images/{ui_folder}/.

    Args:
        local_path: Local path to the reference image file
        ui_folder: Stable storage key for the UI — pass the userinterface *id*
            (resolve via reference_storage_key), NOT the mutable name, so a
            rename never orphans the object.
        image_name: Filename for the reference image (e.g., 'logo.jpg', 'button_play.jpg')

    Returns:
        Dict with success status, url, remote_path, and size
    """
    uploader = get_cloudflare_utils()
    remote_path = f"reference-images/{ui_folder}/{image_name}"
    file_mappings = [{'local_path': local_path, 'remote_path': remote_path}]
    result = uploader.upload_files(file_mappings)
    
    # Return single file format for compatibility
    if result['uploaded_files']:
        return {
            'success': True,
            'url': result['uploaded_files'][0]['url'],
            'remote_path': result['uploaded_files'][0]['remote_path'],
            'size': result['uploaded_files'][0]['size']
        }
    else:
        return {
            'success': False,
            'error': result['failed_uploads'][0]['error'] if result['failed_uploads'] else 'Upload failed'
        }

def download_reference_image(ui_folder: str, image_name: str, local_path: str) -> Dict:
    """
    Download a reference image from R2 under reference-images/{ui_folder}/.

    Args:
        ui_folder: Stable storage key for the UI — the userinterface *id* (resolve via
            reference_storage_key), NOT the mutable name.
        image_name: Filename of the reference image
        local_path: Local path where the file should be saved
    
    Returns:
        Dict with success status and local file path
    """
    downloader = get_cloudflare_utils()
    remote_path = f"reference-images/{ui_folder}/{image_name}"
    return downloader.download_file(remote_path, local_path)

def upload_navigation_screenshot(local_path: str, userinterface_name: str, screenshot_name: str) -> Dict:
    """
    Upload a navigation screenshot to R2 in the navigation/{userinterface_name} folder.
    
    Args:
        local_path: Local path to the screenshot file
        userinterface_name: Name of the user interface (e.g., 'example_mobile', 'example_web')
        screenshot_name: Filename for the screenshot (e.g., 'Home_Screen.jpg')
    
    Returns:
        Dict with success status, url, remote_path, and size
    """
    uploader = get_cloudflare_utils()
    remote_path = f"navigation/{userinterface_name}/{screenshot_name}"
    file_mappings = [{'local_path': local_path, 'remote_path': remote_path}]
    result = uploader.upload_files(file_mappings)
    
    # Return single file format for compatibility
    if result['uploaded_files']:
        return {
            'success': True,
            'url': result['uploaded_files'][0]['url'],
            'remote_path': result['uploaded_files'][0]['remote_path'],
            'size': result['uploaded_files'][0]['size']
        }
    else:
        return {
            'success': False,
            'error': result['failed_uploads'][0]['error'] if result['failed_uploads'] else 'Upload failed'
        }

def upload_heatmap_html(html_content: str, timestamp: str, server_path: str = None) -> Dict:
    """Upload heatmap HTML to R2 in the heatmaps folder.

    Args:
        html_content: The HTML string to upload.
        timestamp: Time key (e.g. "1306") used as part of the storage path.
        server_path: Server name (e.g. "RPI1-server"). When provided the HTML
            is stored at heatmaps/{server_path}/{timestamp}.html matching the
            new-style layout used by the heatmap processor.
    """
    try:
        uploader = get_cloudflare_utils()

        # Use new-style path when server_path is available
        if server_path:
            html_path = f"heatmaps/{server_path}/{timestamp}.html"
        else:
            html_path = f"heatmaps/{timestamp}/mosaic.html"
        
        # Create temporary HTML file
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8', newline='\n') as temp_file:
            temp_file.write(html_content)
            temp_file_path = temp_file.name
        
        try:
            # Upload HTML file with 14-day signed URL in private mode
            file_mappings = [{'local_path': temp_file_path, 'remote_path': html_path}]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
            
            # Convert to single file result
            if upload_result['uploaded_files']:
                result = {
                    'success': True,
                    'url': upload_result['uploaded_files'][0]['url'],
                    'remote_path': upload_result['uploaded_files'][0]['remote_path']
                }
            else:
                result = {
                    'success': False,
                    'error': upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Upload failed'
                }
            
            if result['success']:
                logger.info(f"Uploaded heatmap HTML: {html_path}")
                return {
                    'success': True,
                    'html_path': html_path,
                    'html_url': result['url']
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Upload failed')
                }
                
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Heatmap HTML upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def _build_script_artifact_folder_name(script_name: str, timestamp: str, script_result_id: Optional[str] = None) -> str:
    """Build a stable folder name for script artifacts.

    Prefer script_result_id to guarantee one folder per DB row/run.
    Fall back to timestamp-based naming for backward compatibility.
    """
    if script_result_id and str(script_result_id).strip():
        return f"{script_name}_{str(script_result_id).strip()}"

    date_str = timestamp[:8]  # YYYYMMDD from YYYYMMDDHHMMSS*
    return f"{script_name}_{date_str}_{timestamp}"


def upload_script_report(
    html_content: str,
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None
) -> Dict:
    """Upload script report HTML to R2 in the script-reports folder."""
    try:
        uploader = get_cloudflare_utils()
        
        # Create report folder path. Use script_result_id when available to avoid
        # collisions across runs that complete in the same second.
        folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
        report_path = f"script-reports/{device_model}/{folder_name}/report.html"
        
        # Create temporary HTML file
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8', newline='\n') as temp_file:
            temp_file.write(html_content)
            temp_file_path = temp_file.name
        
        try:
            # Upload HTML report with 14-day signed URL in private mode
            file_mappings = [{'local_path': temp_file_path, 'remote_path': report_path}]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
            
            # Convert to single file result
            if upload_result['uploaded_files']:
                result = {
                    'success': True,
                    'url': upload_result['uploaded_files'][0]['url'],
                    'remote_path': upload_result['uploaded_files'][0]['remote_path']
                }
            else:
                result = {
                    'success': False,
                    'error': upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Upload failed'
                }
            
            if result['success']:
                logger.info(f"Uploaded script report: {result['url']}")
                return {
                    'success': True,
                    'report_path': report_path,
                    'report_url': result['url'],
                    'folder_path': f"script-reports/{device_model}/{folder_name}"
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Upload failed')
                }
                
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Script report upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def upload_test_video(
    local_video_path: str,
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None
) -> Dict:
    """Upload test execution video MP4 to R2 in the same folder as the script report."""
    try:
        uploader = get_cloudflare_utils()

        # Create video path in same folder as script report.
        folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
        video_path = f"script-reports/{device_model}/{folder_name}/video.mp4"

        # Compress if over the threshold; skip upload if it stays over the proxy ceiling.
        from shared.src.lib.utils.video_utils import compress_video_for_upload
        prep = compress_video_for_upload(local_video_path)
        if not prep['success']:
            logger.warning(
                f"Test video skipped (not uploaded): {prep['error']} "
                f"[original={prep['original_size_mb']}MB, final={prep['final_size_mb']}MB, path={local_video_path}]"
            )
            return {'success': False, 'error': prep['error']}
        upload_source_path = prep['path']
        if prep['compressed']:
            logger.info(
                f"Test video compressed before upload: "
                f"{prep['original_size_mb']}MB -> {prep['final_size_mb']}MB ({upload_source_path})"
            )

        # Upload video file with proper content type (14-day signed URL in private mode)
        file_mappings = [{
            'local_path': upload_source_path,
            'remote_path': video_path,
            'content_type': 'video/mp4'
        }]

        try:
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
        finally:
            if prep['compressed'] and os.path.exists(upload_source_path):
                try: os.remove(upload_source_path)
                except OSError: pass
        
        # Convert to single file result
        if upload_result['uploaded_files']:
            result = {
                'success': True,
                'url': upload_result['uploaded_files'][0]['url'],
                'remote_path': upload_result['uploaded_files'][0]['remote_path']
            }
            logger.info(f"Uploaded test video: {video_path}")
            return {
                'success': True,
                'video_path': video_path,
                'video_url': result['url']
            }
        else:
            return {
                'success': False,
                'error': upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Video upload failed'
            }
            
    except Exception as e:
        logger.error(f"Failed to upload test video: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def upload_restart_video(local_video_path: str, timestamp: str) -> Dict:
    """Upload restart video MP4 to R2 in the same folder as the report."""
    try:
        uploader = get_cloudflare_utils()

        # Create video path in same folder as report: restart-reports/{timestamp}/video.mp4
        video_path = f"restart-reports/{timestamp}/video.mp4"

        # Compress if over the threshold; skip upload if it stays over the proxy ceiling.
        from shared.src.lib.utils.video_utils import compress_video_for_upload
        prep = compress_video_for_upload(local_video_path)
        if not prep['success']:
            logger.warning(
                f"Restart video skipped (not uploaded): {prep['error']} "
                f"[original={prep['original_size_mb']}MB, final={prep['final_size_mb']}MB, path={local_video_path}]"
            )
            return {'success': False, 'error': prep['error']}
        upload_source_path = prep['path']
        if prep['compressed']:
            logger.info(
                f"Restart video compressed before upload: "
                f"{prep['original_size_mb']}MB -> {prep['final_size_mb']}MB ({upload_source_path})"
            )

        # Upload video file with proper content type (14-day signed URL in private mode)
        file_mappings = [{
            'local_path': upload_source_path,
            'remote_path': video_path,
            'content_type': 'video/mp4'
        }]

        try:
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
        finally:
            if prep['compressed'] and os.path.exists(upload_source_path):
                try: os.remove(upload_source_path)
                except OSError: pass
        
        # Convert to single file result
        if upload_result['uploaded_files']:
            result = {
                'success': True,
                'url': upload_result['uploaded_files'][0]['url'],
                'remote_path': upload_result['uploaded_files'][0]['remote_path']
            }
            logger.info(f"Uploaded restart video: {video_path}")
            return {
                'success': True,
                'video_path': video_path,
                'video_url': result['url']
            }
        else:
            return {
                'success': False,
                'error': upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Video upload failed'
            }
            
    except Exception as e:
        logger.error(f"Failed to upload restart video: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def upload_restart_report(html_content: str, host_name: str, device_id: str, timestamp: str) -> Dict:
    """Upload restart video report HTML to R2 in the restart-reports folder."""
    try:
        uploader = get_cloudflare_utils()
        
        # Create report folder path: restart-reports/{timestamp}/
        # Use timestamp-based structure like script reports, not device-based
        report_path = f"restart-reports/{timestamp}/restart_video.html"
        
        # Create temporary HTML file
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8', newline='\n') as temp_file:
            temp_file.write(html_content)
            temp_file_path = temp_file.name
        
        try:
            # Upload HTML report with 14-day signed URL in private mode
            file_mappings = [{'local_path': temp_file_path, 'remote_path': report_path}]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
            
            # Convert to single file result
            if upload_result['uploaded_files']:
                result = {
                    'success': True,
                    'url': upload_result['uploaded_files'][0]['url'],
                    'remote_path': upload_result['uploaded_files'][0]['remote_path']
                }
            else:
                result = {
                    'success': False,
                    'error': upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Upload failed'
                }
            
            if result['success']:
                logger.info(f"Uploaded restart report: {report_path}")
                return {
                    'success': True,
                    'report_path': report_path,
                    'report_url': result['url'],
                    'folder_path': f"restart-reports/{timestamp}"
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Upload failed')
                }
                
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Restart report upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def upload_script_logs(
    log_content: str,
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None
) -> Dict:
    """Upload script execution logs to R2."""
    try:
        uploader = get_cloudflare_utils()
        
        # Create report folder path (same as reports for consistency).
        folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
        remote_path = f"script-logs/{device_model}/{folder_name}/execution.txt"
        
        logger.info(f"Uploading script logs to R2: {remote_path}")
        
        # Create temporary log file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8', newline='\n') as temp_file:
            temp_file.write(log_content)
            temp_log_path = temp_file.name
        
        try:
            # Upload with explicit text/plain content type for inline browser display
            # Use 14-day signed URL in private mode (report asset)
            file_mappings = [{
                'local_path': temp_log_path, 
                'remote_path': remote_path,
                'content_type': 'text/plain; charset=utf-8'
            }]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
            
            # Clean up temporary file
            os.unlink(temp_log_path)
            
            if upload_result['success'] and upload_result['uploaded_files']:
                uploaded_file = upload_result['uploaded_files'][0]
                logger.info(f"Uploaded script logs: {uploaded_file['url']}")
                return {
                    'success': True,
                    'url': uploaded_file['url'],
                    'path': remote_path
                }
            else:
                error_msg = 'Upload failed'
                if upload_result['failed_uploads']:
                    error_msg = upload_result['failed_uploads'][0]['error']
                logger.error(f"Script logs upload failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except Exception as upload_error:
            # Clean up temporary file on error
            if os.path.exists(temp_log_path):
                os.unlink(temp_log_path)
            raise upload_error
            
    except Exception as e:
        logger.error(f"Script logs upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def upload_verification_review_markdown(
    markdown_content: str,
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None,
    remote_path: Optional[str] = None,
) -> Dict:
    """Upload AI verification review markdown to R2/MinIO."""
    try:
        uploader = get_cloudflare_utils()

        if not remote_path:
            folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
            remote_path = f"script-logs/{device_model}/{folder_name}/verification_review.md"

        logger.info(f"Uploading verification review markdown to R2: {remote_path}")

        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8', newline='\n') as temp_file:
            temp_file.write(markdown_content or '')
            temp_md_path = temp_file.name

        try:
            file_mappings = [{
                'local_path': temp_md_path,
                'remote_path': remote_path,
                'content_type': 'text/markdown; charset=utf-8'
            }]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
            os.unlink(temp_md_path)

            if upload_result['success'] and upload_result['uploaded_files']:
                uploaded_file = upload_result['uploaded_files'][0]
                logger.info(f"Uploaded verification review markdown: {uploaded_file['url']}")
                return {
                    'success': True,
                    'url': uploaded_file['url'],
                    'path': remote_path
                }

            error_msg = 'Upload failed'
            if upload_result['failed_uploads']:
                error_msg = upload_result['failed_uploads'][0]['error']
            logger.error(f"Verification markdown upload failed: {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }

        except Exception as upload_error:
            if os.path.exists(temp_md_path):
                os.unlink(temp_md_path)
            raise upload_error

    except Exception as e:
        logger.error(f"Verification markdown upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def upload_script_metadata_artifact(
    metadata: Dict,
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None,
    remote_path: Optional[str] = None,
) -> Dict:
    """Upload the final script metadata dict as metadata.json alongside other script log artifacts."""
    try:
        uploader = get_cloudflare_utils()

        if not remote_path:
            folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
            remote_path = f"script-logs/{device_model}/{folder_name}/metadata.json"

        logger.info(f"Uploading script metadata to R2: {remote_path}")

        import tempfile
        import json as _json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8', newline='\n') as temp_file:
            _json.dump(metadata or {}, temp_file, indent=2, default=str, ensure_ascii=False)
            temp_json_path = temp_file.name

        try:
            file_mappings = [{
                'local_path': temp_json_path,
                'remote_path': remote_path,
                'content_type': 'application/json; charset=utf-8'
            }]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
            os.unlink(temp_json_path)

            if upload_result['success'] and upload_result['uploaded_files']:
                uploaded_file = upload_result['uploaded_files'][0]
                logger.info(f"Uploaded script metadata: {uploaded_file['url']}")
                return {
                    'success': True,
                    'url': uploaded_file['url'],
                    'path': remote_path
                }

            error_msg = 'Upload failed'
            if upload_result['failed_uploads']:
                error_msg = upload_result['failed_uploads'][0]['error']
            logger.error(f"Script metadata upload failed: {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }

        except Exception as upload_error:
            if os.path.exists(temp_json_path):
                os.unlink(temp_json_path)
            raise upload_error

    except Exception as e:
        logger.error(f"Script metadata upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def upload_script_source_artifact(
    local_source_path: str,
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None,
    remote_path: Optional[str] = None,
) -> Dict:
    """Upload the executed script source alongside other script log artifacts."""
    try:
        if not local_source_path or not os.path.exists(local_source_path):
            return {
                'success': False,
                'error': f'Source file not found: {local_source_path}',
            }

        uploader = get_cloudflare_utils()

        if not remote_path:
            folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
            remote_path = f"script-logs/{device_model}/{folder_name}/script_source.py"

        logger.info(f"Uploading script source artifact to storage: {remote_path}")

        file_mappings = [{
            'local_path': local_source_path,
            'remote_path': remote_path,
            'content_type': 'text/plain; charset=utf-8',
        }]
        upload_result = uploader.upload_files(file_mappings, for_report_assets=True)

        if upload_result['success'] and upload_result['uploaded_files']:
            uploaded_file = upload_result['uploaded_files'][0]
            logger.info(f"Uploaded script source artifact: {uploaded_file['url']}")
            return {
                'success': True,
                'url': uploaded_file['url'],
                'path': remote_path,
            }

        error_msg = 'Upload failed'
        if upload_result['failed_uploads']:
            error_msg = upload_result['failed_uploads'][0]['error']
        logger.error(f"Script source artifact upload failed: {error_msg}")
        return {
            'success': False,
            'error': error_msg,
        }
    except Exception as e:
        logger.error(f"Script source artifact upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e),
        }

def upload_validation_screenshots(
    screenshot_paths: list,
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None
) -> Dict:
    """Upload validation screenshots to R2 using batch upload."""
    uploader = get_cloudflare_utils()
    
    # Create report folder path
    folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
    base_folder = f"script-reports/{device_model}/{folder_name}"
    
    # Prepare file mappings for batch upload
    file_mappings = []
    
    for local_path in screenshot_paths:
        # Skip None or missing paths
        if not local_path or not os.path.exists(local_path):
            continue
        
        # Add main screenshot
        filename = os.path.basename(local_path)
        file_mappings.append({
            'local_path': local_path,
            'remote_path': f"{base_folder}/{filename}"
        })
        
        # Add thumbnail if exists
        thumbnail_path = local_path.replace('.jpg', '_thumbnail.jpg')
        if os.path.exists(thumbnail_path):
            thumbnail_filename = os.path.basename(thumbnail_path)
            file_mappings.append({
                'local_path': thumbnail_path,
                'remote_path': f"{base_folder}/{thumbnail_filename}"
            })
    
    if not file_mappings:
        return {
            'success': False,
            'error': 'No valid files found',
            'uploaded_count': 0,
            'failed_count': 0,
            'uploaded_screenshots': [],
            'failed_uploads': []
        }
    
    # Upload all files with report asset URLs (14-day signed URLs in private mode)
    batch_result = uploader.upload_files(file_mappings, for_report_assets=True)
    
    return {
        'success': batch_result['success'],
        'uploaded_count': batch_result['uploaded_count'],
        'failed_count': batch_result['failed_count'],
        'uploaded_screenshots': [
            {
                'local_path': f['local_path'],
                'remote_path': f['remote_path'],
                'url': f['url']
            } for f in batch_result['uploaded_files']
        ],
        'failed_uploads': [
            {
                'path': f['local_path'],
                'error': f['error']
            } for f in batch_result['failed_uploads']
        ],
        'folder_path': base_folder
    }

def get_script_report_folder_url(
    device_model: str,
    script_name: str,
    timestamp: str,
    script_result_id: Optional[str] = None
) -> str:
    """Get base URL for script report folder."""
    uploader = get_cloudflare_utils()
    folder_name = _build_script_artifact_folder_name(script_name, timestamp, script_result_id)
    folder_path = f"script-reports/{device_model}/{folder_name}"
    return uploader.get_public_url(folder_path)


def upload_kpi_thumbnails(thumbnails: Dict[str, str], execution_result_id: str, timestamp: str) -> Dict:
    """
    Upload KPI thumbnails to R2.
    
    Args:
        thumbnails: Dict with keys ('before_action', 'after_action', 'before_match', 'match', 'match_original') pointing to local paths
        execution_result_id: Execution result ID
        timestamp: Timestamp string (YYYYMMDDHHMMSS)
        
    Returns:
        Dict with same keys containing R2 URLs
    """
    try:
        uploader = get_cloudflare_utils()
        
        # Create file mappings for batch upload
        file_mappings = []
        for thumb_type, local_path in thumbnails.items():
            if local_path and os.path.exists(local_path):
                logger.info(f"📁 Uploading {thumb_type}: {local_path}")
                remote_path = f"kpi_measurement/{execution_result_id[:8]}/{timestamp}_{thumb_type}.jpg"
                file_mappings.append({
                    'local_path': local_path,
                    'remote_path': remote_path,
                    'content_type': 'image/jpeg'
                })
            else:
                logger.warning(f"⚠️  Skipping {thumb_type}: file not found at {local_path}")
        
        if not file_mappings:
            logger.warning(f"⚠️  No images to upload for {execution_result_id[:8]}")
            return {}
        
        # Batch upload with 14-day signed URLs in private mode
        upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
        
        # Extract URLs and log them
        urls = {}
        for uploaded in upload_result.get('uploaded_files', []):
            remote_path = uploaded['remote_path']
            url = uploaded['url']
            # Extract type from filename (e.g., "20251023120221_before_action.jpg" → "before_action")
            filename = os.path.basename(remote_path)  # Get just the filename
            # Remove timestamp prefix and .jpg extension
            # Format: "20251023120221_before_action.jpg" → "before_action"
            if '_' in filename:
                thumb_type = '_'.join(filename.split('_')[1:]).replace('.jpg', '')
            else:
                thumb_type = 'unknown'
            urls[thumb_type] = url
            logger.info(f"✅ Uploaded {thumb_type}: {url}")
        
        logger.info(f"✓ Uploaded {len(urls)}/{len(thumbnails)} images to R2")
        return urls
        
    except Exception as e:
        logger.error(f"KPI thumbnails upload failed: {str(e)}")
        return {}


def upload_kpi_report(html_content: str, execution_result_id: str, timestamp: str) -> Dict:
    """
    Upload KPI measurement report HTML to R2.
    
    Args:
        html_content: HTML report content
        execution_result_id: Execution result ID
        timestamp: Timestamp string (YYYYMMDDHHMMSS)
        
    Returns:
        Dict with 'success', 'report_url', 'report_path'
    """
    try:
        uploader = get_cloudflare_utils()
        
        # R2 path: kpi_measurement/{timestamp}_{exec_result_id_prefix}.html
        # Timestamp-first + flat (one level under kpi_measurement/) so the MinIO
        # console lists every report as an OBJECT (with size + last-modified)
        # sorted by recency — prefix "folders" never show last-modified, so the
        # old nested kpi_measurement/{exec_id}/{timestamp}.html layout hid the
        # latest report. Applies to both success and failure reports.
        report_path = f"kpi_measurement/{timestamp}_{execution_result_id[:8]}.html"
        
        # Create temporary HTML file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as temp_file:
            temp_file.write(html_content)
            temp_file_path = temp_file.name
        
        try:
            # Upload HTML report with 14-day signed URL in private mode
            file_mappings = [{
                'local_path': temp_file_path, 
                'remote_path': report_path,
                'content_type': 'text/html; charset=utf-8'
            }]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
            
            # Convert to single file result
            if upload_result['uploaded_files']:
                result = {
                    'success': True,
                    'url': upload_result['uploaded_files'][0]['url'],
                    'remote_path': upload_result['uploaded_files'][0]['remote_path']
                }
            else:
                result = {
                    'success': False,
                    'error': upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Upload failed'
                }
            
            if result['success']:
                logger.info(f"Uploaded KPI report: {report_path}")
                return {
                    'success': True,
                    'report_path': report_path,
                    'report_url': result['url']
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Upload failed'),
                    'report_url': ''
                }
                
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"KPI report upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'report_url': ''
        }


def upload_zap_report(html_content: str, report_id: str, timestamp: str) -> Dict:
    """
    Upload a per-event zap measurement report HTML to R2.

    Mirrors upload_kpi_report. Single path used by both automatic and scripted zaps
    (via zap_report_generator.generate_and_upload_zap_report).

    Args:
        html_content: HTML report content
        report_id: Namespacing token (e.g. capture folder or device name)
        timestamp: Timestamp string (YYYYMMDDHHMMSS[%f])

    Returns:
        Dict with 'success', 'report_url', 'report_path'
    """
    try:
        uploader = get_cloudflare_utils()

        # R2 path: zap-reports/{report_id}/{timestamp}.html
        report_path = f"zap-reports/{report_id}/{timestamp}.html"

        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8', newline='\n') as temp_file:
            temp_file.write(html_content)
            temp_file_path = temp_file.name

        try:
            # Upload HTML report with 14-day signed URL in private mode
            file_mappings = [{
                'local_path': temp_file_path,
                'remote_path': report_path,
                'content_type': 'text/html; charset=utf-8'
            }]
            upload_result = uploader.upload_files(file_mappings, for_report_assets=True)

            if upload_result['uploaded_files']:
                logger.info(f"Uploaded zap report: {report_path}")
                return {
                    'success': True,
                    'report_path': report_path,
                    'report_url': upload_result['uploaded_files'][0]['url']
                }
            else:
                return {
                    'success': False,
                    'error': upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Upload failed',
                    'report_url': ''
                }
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        logger.error(f"Zap report upload failed: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'report_url': ''
        }
