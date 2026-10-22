"""Digest-pinned OCI archives, verified without extracting or executing images."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
from .deployment_sources import image_parts
from .repository_collector import CollectionError

MAX_ARCHIVE = 10 * 1024**3
PART_SIZE = 16 * 1024**2


def source_reference(source):
    parts = image_parts(source.get('reference', ''))
    host, repository, digest = parts['registry'], parts['repository'], source.get('digest')
    if (not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', host) or host == 'localhost'
            or not re.fullmatch(r'[a-z0-9]+(?:[._-]+[a-z0-9]+)*(?:/[a-z0-9]+(?:[._-]+[a-z0-9]+)*)*', repository)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest or '')):
        raise CollectionError('INVALID_IMAGE_REFERENCE')
    if parts.get('digest') and parts['digest'] != digest:
        raise CollectionError('IMAGE_DIGEST_CONFLICT')
    return parts, host+'/'+repository+'@'+digest


def copy_archive(source, directory, auth=None, check=lambda: None, timeout=1800):
    parts, reference = source_reference(source)
    directory = Path(directory)
    if shutil.disk_usage(directory).free < 2*MAX_ARCHIVE+512*1024**2:
        raise CollectionError('IMAGE_DISK_SPACE_REQUIRED')
    authfile = directory/'auth.json'
    fd = os.open(authfile, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'auths': {parts['registry']: {'auth': auth}} if auth else {}}, stream)
    archive = directory/'image.tar'
    command = ['skopeo', 'copy', '--all', '--preserve-digests', '--src-tls-verify=true',
               '--src-authfile', str(authfile), 'docker://'+reference, 'oci-archive:'+str(archive)+':navigan']
    environment = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(directory),
                   'XDG_RUNTIME_DIR': str(directory), 'XDG_CONFIG_HOME': str(directory), 'TMPDIR': str(directory)}
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment)
        started = time.monotonic()
        while process.poll() is None:
            check()
            if time.monotonic()-started > timeout:
                raise CollectionError('IMAGE_TRANSFER_TIMEOUT')
            if (shutil.disk_usage(directory).free < 512*1024**2
                    or sum(p.stat().st_size for p in directory.rglob('*') if p.is_file()) > 2*MAX_ARCHIVE):
                raise CollectionError('IMAGE_SIZE_LIMIT')
            time.sleep(2)
        check()
        if process.returncode:
            raise CollectionError('IMAGE_PULL_FAILED')
        if not archive.is_file() or not 0 < archive.stat().st_size <= MAX_ARCHIVE:
            raise CollectionError('IMAGE_SIZE_LIMIT')
        return archive
    except FileNotFoundError:
        raise CollectionError('IMAGE_TOOL_UNAVAILABLE') from None
    finally:
        if process is not None and process.poll() is None:
            process.kill(); process.wait(timeout=10)
        authfile.unlink(missing_ok=True)


def validate_archive(path, expected_digest, check=lambda: None):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', expected_digest or ''):
        raise CollectionError('INVALID_IMAGE_DIGEST')
    members = set(); sizes = {}; documents = {}; total = 0; document_bytes = 0
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            check()
            name = member.name
            while name.startswith('./'): name = name[2:]
            if member.isdir(): name = name.rstrip('/')
            if name in {'', '.'} and member.isdir(): continue
            if (name in members or name.startswith('/') or '\\' in name
                    or any(p in {'', '..', '.'} for p in name.split('/'))
                    or not (member.isfile() or member.isdir()) or member.issparse()):
                raise CollectionError('UNSAFE_OCI_ARCHIVE')
            if len(members) >= 50000:
                raise CollectionError('IMAGE_CONTENT_LIMIT')
            members.add(name)
            if member.isdir(): continue
            total += member.size
            if total > MAX_ARCHIVE:
                raise CollectionError('IMAGE_SIZE_LIMIT')
            if name not in {'oci-layout', 'index.json'} and not re.fullmatch(r'blobs/sha256/[a-f0-9]{64}', name):
                raise CollectionError('UNSUPPORTED_OCI_CONTENT')
            stream = archive.extractfile(member); sha = hashlib.sha256(); pieces = []
            while chunk := stream.read(1024*1024):
                check(); sha.update(chunk)
                if member.size <= 8*1024*1024: pieces.append(chunk)
            if name.startswith('blobs/') and sha.hexdigest() != name.rsplit('/', 1)[1]:
                raise CollectionError('IMAGE_BLOB_DIGEST_MISMATCH')
            sizes[name] = member.size
            if pieces and b''.join(pieces).lstrip().startswith(b'{'):
                document_bytes += member.size
                if document_bytes > 64*1024*1024:
                    raise CollectionError('IMAGE_CONTENT_LIMIT')
                documents[name] = b''.join(pieces)
    try:
        if json.loads(documents['oci-layout']).get('imageLayoutVersion') != '1.0.0': raise ValueError()
        index = json.loads(documents['index.json'])
        if index.get('schemaVersion') != 2: raise ValueError()
        platforms = set(); visited = set(); manifests = 0
        def document(descriptor):
            digest = descriptor['digest']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest): raise ValueError()
            key = 'blobs/sha256/'+digest.split(':')[1]
            if sizes.get(key) != descriptor['size']: raise ValueError()
            return digest, key
        def walk(descriptor, depth=0):
            nonlocal manifests
            if depth > 10: raise ValueError()
            digest, key = document(descriptor)
            if digest in visited: return
            visited.add(digest)
            node = json.loads(documents[key])
            if node.get('schemaVersion') != 2: raise ValueError()
            if 'manifests' in node:
                if not node['manifests']: raise ValueError()
                for child in node['manifests']: walk(child, depth+1)
            else:
                _, configkey = document(node['config']); config = json.loads(documents[configkey])
                if not config.get('os') or not config.get('architecture'): raise ValueError()
                platform = descriptor.get('platform', {})
                for field in ('os', 'architecture', 'variant'):
                    if platform.get(field) and config.get(field) and platform[field] != config[field]: raise ValueError()
                variant = config.get('variant') or platform.get('variant')
                if config['os'] != 'unknown' and config['architecture'] != 'unknown':
                    platforms.add(config['os']+'/'+config['architecture']+('/'+variant if variant else ''))
                for layer in node['layers']: document(layer)
                manifests += 1
        if not index.get('manifests'): raise ValueError()
        for descriptor in index['manifests']: walk(descriptor)
        if expected_digest not in visited or not manifests or not platforms: raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, AttributeError):
        raise CollectionError('IMAGE_CONTENT_INCOMPLETE') from None
    return dict(format='OCI_ARCHIVE', digest=expected_digest, integrity='VERIFIED', content='COMPLETE',
                platforms=sorted(platforms), manifestCount=manifests, targetPlatformStatus='NOT_VERIFIED', targetReady=False)


def upload_archive(client, path, bucket, key_id, owner, key, check=lambda: None):
    size = Path(path).stat().st_size
    if not 0 < size <= MAX_ARCHIVE: raise CollectionError('IMAGE_SIZE_LIMIT')
    args = dict(Bucket=bucket, Key=key, ExpectedBucketOwner=owner)
    upload_id = None; complete = False; full = hashlib.sha256(); part_hashes = []; parts = []
    try:
        upload_id = client.create_multipart_upload(**args, ContentType='application/vnd.oci.image.layout.v1.tar',
                    ServerSideEncryption='aws:kms', SSEKMSKeyId=key_id, ChecksumAlgorithm='SHA256', ChecksumType='COMPOSITE')['UploadId']
        with open(path, 'rb') as stream:
            while chunk := stream.read(PART_SIZE):
                check(); full.update(chunk); digest = hashlib.sha256(chunk).digest(); checksum = base64.b64encode(digest).decode()
                part = client.upload_part(**args, UploadId=upload_id, PartNumber=len(parts)+1, Body=chunk, ChecksumSHA256=checksum)
                if part.get('ChecksumSHA256') != checksum: raise CollectionError('IMAGE_UPLOAD_CHECKSUM_FAILED')
                part_hashes.append(digest); parts.append(dict(PartNumber=len(parts)+1, ETag=part['ETag'], ChecksumSHA256=checksum))
        check()
        expected = base64.b64encode(hashlib.sha256(b''.join(part_hashes)).digest()).decode()+'-'+str(len(parts))
        result = client.complete_multipart_upload(**args, UploadId=upload_id, MultipartUpload={'Parts': parts}, ChecksumType='COMPOSITE', IfNoneMatch='*')
        complete = True; version = result.get('VersionId')
        if not version or version == 'null': raise CollectionError('WORKSPACE_VERSIONING_REQUIRED')
        stored = client.head_object(**args, VersionId=version, ChecksumMode='ENABLED')
        if (stored.get('ChecksumSHA256') != expected or stored.get('ContentLength') != size or stored.get('ServerSideEncryption') != 'aws:kms'):
            raise CollectionError('IMAGE_UPLOAD_CHECKSUM_FAILED')
        check()
        return dict(key=key, version=version, sha256=full.hexdigest(), size=size)
    finally:
        if upload_id and not complete:
            try: client.abort_multipart_upload(**args, UploadId=upload_id)
            except Exception: pass  # Bucket lifecycle also removes abandoned multipart uploads.
