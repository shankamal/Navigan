"""Bounded immutable GitHub file bundles. Never execute or render repository code."""
import base64
import hashlib
import re
import time
from pathlib import PurePosixPath
from .deployment_sources import get_json

class CollectionError(Exception):
    def __init__(self, code): self.code=code;super().__init__(code)


def safe_path(path):
    if not isinstance(path,str) or not path or path.startswith('/') or '\\' in path or any(ord(c)<32 for c in path) or any(p in {'.','..',''} for p in path.split('/')):
        raise CollectionError('UNSAFE_REPOSITORY_PATH')
    return path


def collect(source, token=None, fetch=get_json):
    repo, commit, path = source.get('repository',''),source.get('commit',''),safe_path(source.get('filePath'))
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo) or not re.fullmatch(r'[a-f0-9]{40}',commit):
        raise CollectionError('INVALID_REPOSITORY_REFERENCE')
    prefix=f'https://api.github.com/repos/{repo}'
    deadline=time.monotonic()+120
    tree=fetch(prefix+'/git/trees/'+commit+'?recursive=1',token)
    if tree.get('truncated'):
        raise CollectionError('REPOSITORY_TREE_LIMIT')
    entries={safe_path(e['path']):e for e in tree.get('tree',[])}
    if path not in entries:
        raise CollectionError('DEFINITION_NOT_FOUND')
    parent=str(PurePosixPath(path).parent)
    # Chart/Kustomize bundles include local sibling content. Remote dependencies
    # and deploy-time values are explicitly NOT verified by this copy operation.
    bundle_directory=source.get('format') in {'HELM','KUSTOMIZE'} or PurePosixPath(path).name.lower() in {'chart.yaml','kustomization.yaml','kustomization.yml'}
    chosen=[e for p,e in entries.items() if e.get('type')!='tree' and (p==path or (bundle_directory and (parent=='.' or p.startswith(parent+'/'))))]
    if len(chosen)>50 or sum(e.get('size',0) for e in chosen)>5_000_000:
        raise CollectionError('REPOSITORY_BUNDLE_LIMIT')
    files=[];total=0
    for entry in sorted(chosen,key=lambda e:e['path']):
        if time.monotonic()>deadline:
            raise CollectionError('COLLECTION_TIME_LIMIT')
        if entry.get('type')!='blob' or entry.get('mode') not in {'100644','100755'}:
            raise CollectionError('UNSUPPORTED_REPOSITORY_ENTRY')
        sha=entry.get('sha','')
        if not re.fullmatch(r'[a-f0-9]{40}',sha) or entry.get('size',0)>1_000_000:
            raise CollectionError('REPOSITORY_BLOB_LIMIT')
        blob=fetch(prefix+'/git/blobs/'+sha,token)
        if blob.get('encoding')!='base64':
            raise CollectionError('INVALID_REPOSITORY_BLOB')
        raw=base64.b64decode(''.join(blob.get('content','').split()),validate=True)
        total+=len(raw)
        if len(raw)>1_000_000 or total>5_000_000:
            raise CollectionError('REPOSITORY_BUNDLE_LIMIT')
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=sha or len(raw)!=entry.get('size'):
            raise CollectionError('REPOSITORY_INTEGRITY_FAILED')
        files.append(dict(path=entry['path'],gitBlob=sha,sha256=hashlib.sha256(raw).hexdigest(),contentBase64=base64.b64encode(raw).decode()))
    return dict(schemaVersion=1,format='REPOSITORY_FILE_BUNDLE',repository=repo,commit=commit,entrypoint=path,files=files,
                validation=dict(integrity='VERIFIED',deploymentRevision='NOT_VERIFIED',dependencies='REVIEW_REQUIRED',targetReady=False))
