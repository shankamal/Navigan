#!/usr/bin/env python3
"""Run authenticated, read-only DEV/PROD API smoke checks.

Tokens are prompted without echo and are never written or printed. Every request
uses GET; this script cannot create, update, approve, execute or delete data.
"""
import argparse
import getpass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


BASE_PATHS = (
    '/v1/api/v1/customers/summary',
    '/v1/api/v1/environments/summary',
    '/v1/api/v1/clusters/summary',
    '/v1/api/v1/migrations',
    '/v1/api/v1/source-clusters',
)


def require(value, message):
    if not value:
        raise RuntimeError(message)


def origin(value):
    parsed = urlparse(value)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.path.rstrip('/')
            and not parsed.query and not parsed.fragment and not parsed.username and not parsed.password,
            'API origin must be an HTTPS origin without path, query or credentials')
    return value.rstrip('/')


def paths(migration_id=None, source_cluster_id=None):
    result = list(BASE_PATHS)
    if migration_id:
        item = quote(migration_id, safe='')
        result.extend((f'/v1/api/v1/migrations/{item}', f'/v1/api/v1/migrations/{item}/source-inventory',
                       f'/v1/api/v1/migrations/{item}/target-assessment',
                       f'/v1/api/v1/migrations/{item}/target-compatibility'))
    if source_cluster_id:
        item = quote(source_cluster_id, safe='')
        result.extend((f'/v1/api/v1/source-clusters/{item}',
                       f'/v1/api/v1/source-clusters/{item}/deployment-sources'))
    return result


def check(label, api_origin, token, endpoints, timeout=30, opener=urlopen):
    require(token and '\n' not in token and '\r' not in token, 'Bearer token is empty or malformed')
    token = token.removeprefix('Bearer ').strip()
    results = []
    for path in endpoints:
        request = Request(api_origin + path, method='GET', headers={
            'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
            'User-Agent': 'navigan-authenticated-read-validation/1'})
        try:
            with opener(request, timeout=timeout) as response:
                raw = response.read(5 * 1024 * 1024 + 1)
                require(len(raw) <= 5 * 1024 * 1024, 'Response exceeds smoke-test size limit')
                require(response.status == 200, 'Unexpected success status')
                value = json.loads(raw)
                require(isinstance(value, (dict, list)), 'Response is not a JSON object or list')
                results.append({'path': path, 'status': response.status, 'jsonType': type(value).__name__})
        except HTTPError as error:
            results.append({'path': path, 'status': error.code, 'error': 'HTTP_ERROR'})
        except (URLError, TimeoutError):
            results.append({'path': path, 'status': None, 'error': 'CONNECTION_ERROR'})
        except (UnicodeDecodeError, json.JSONDecodeError):
            results.append({'path': path, 'status': None, 'error': 'INVALID_JSON'})
        except RuntimeError:
            results.append({'path': path, 'status': None, 'error': 'VALIDATION_ERROR'})
    return {'environment': label, 'passed': all(r.get('status') == 200 for r in results), 'requests': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dev-origin', required=True); parser.add_argument('--prod-origin', required=True)
    parser.add_argument('--dev-migration-id'); parser.add_argument('--prod-migration-id')
    parser.add_argument('--dev-source-cluster-id'); parser.add_argument('--prod-source-cluster-id')
    parser.add_argument('--shared-token', action='store_true', help='Prompt once when both APIs use the same identity token')
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args()
    require(1 <= args.timeout <= 120, 'Timeout must be between 1 and 120 seconds')
    dev_token = getpass.getpass('DEV bearer token (hidden): ')
    prod_token = dev_token if args.shared_token else getpass.getpass('PROD bearer token (hidden): ')
    reports = [
        check('dev', origin(args.dev_origin), dev_token,
              paths(args.dev_migration_id, args.dev_source_cluster_id), args.timeout),
        check('prod', origin(args.prod_origin), prod_token,
              paths(args.prod_migration_id, args.prod_source_cluster_id), args.timeout),
    ]
    output = {'readOnly': True, 'passed': all(r['passed'] for r in reports), 'environments': reports}
    print(json.dumps(output, indent=2))
    print('Authenticated read-path validation ' + ('passed.' if output['passed'] else 'failed; inspect statuses above.'))
    return 0 if output['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
