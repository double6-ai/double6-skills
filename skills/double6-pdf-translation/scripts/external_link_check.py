"""只读、去重、限时检查 PDF 外链；访问限制和网络错误不冒称失效。"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from daily_skill_research.execution import run_command
import fitz
from paragraph_link_rebind import checked_ref, reference

POLICY = {'id': 'bounded-external-link-check-v2', 'maximum_urls_per_batch': 5,
          'deadline_seconds': 10, 'connect_seconds': 4, 'maximum_redirects': 5,
          'maximum_body_bytes': 262144, 'retry_count': 0, 'case_overrides_allowed': False}

def classify(code, returncode, challenge=False, body_sample_bytes=0):
    if code in (404, 410): return 'unavailable', 'http_resource_missing'
    if code in (401, 403, 407, 429, 451): return 'unverified', 'access_restricted'
    if 200 <= code < 300 and challenge: return 'unverified', 'challenge_page'
    # curl 63 表示达到已声明正文上限；已收到成功响应仍证明 HTTP 可达。
    if 200 <= code < 300 and returncode in (0, 63): return 'reachable', 'http_success'
    if 200 <= code < 300 and body_sample_bytes > 0:
        return 'reachable', 'http_success_partial_transfer'
    if 500 <= code < 600: return 'unverified', 'server_error'
    if returncode: return 'unverified', 'network_or_redirect_error'
    if 300 <= code < 400: return 'unverified', 'unresolved_redirect'
    return 'unverified', 'unexpected_http_status'

def validate_url(url):
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url):
        raise ValueError('external_url_invalid')
    parts = urlsplit(url)
    if parts.scheme == 'mailto':
        if parts.query or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', parts.path):
            raise ValueError('external_mailto_invalid')
        return parts.scheme
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('external_public_http_url_required')
    return parts.scheme

def check_one(url, *, receipt_dir):
    kind = validate_url(url)
    if kind == 'mailto':
        return {'uri': url, 'status': 'not_applicable', 'reason': 'mailto_syntax_valid_no_message_sent'}
    with tempfile.TemporaryDirectory(prefix='pdf-public-link-') as temp:
        body = Path(temp) / 'body'
        result = run_command(['/usr/bin/curl', '--silent', '--show-error', '--location',
            '--max-redirs', str(POLICY['maximum_redirects']), '--max-time', str(POLICY['deadline_seconds']),
            '--connect-timeout', str(POLICY['connect_seconds']), '--max-filesize', str(POLICY['maximum_body_bytes']),
            '--range', '0-262143', '--proto', '=http,https', '--proto-redir', '=http,https',
            '--user-agent', 'PDF-Link-Audit/1.0 (read-only; bounded GET)',
            '--output', str(body), '--write-out', '%{json}', '--', url],
            timeout_seconds=POLICY['deadline_seconds'] + 2, receipt_dir=receipt_dir,
            operation='public-external-link-' + hashlib.sha256(url.encode()).hexdigest()[:16])
        try: metadata = json.loads(result.stdout)
        except (ValueError, TypeError): metadata = {}
        content = body.read_bytes() if body.exists() else b''
        text = content.decode('utf-8', errors='replace')
        title_match = re.search(r'<title\b[^>]*>(.*?)</title>', text, re.I | re.S)
        title = re.sub(r'\s+', ' ', title_match.group(1)).strip()[:200] if title_match else None
        challenge = bool(re.search(r'<title[^>]*>\s*(?:Just a moment|Access Denied|Robot Check|Attention Required)|cf-chl-|id="challenge-form"', text, re.I))
        code = int(metadata.get('http_code', 0))
        status, reason = classify(code, result.returncode, challenge, len(content))
        return {'uri': url, 'status': status, 'reason': reason, 'http_status': code,
                'returncode': result.returncode, 'final_url': metadata.get('url_effective', url),
                'redirects': metadata.get('num_redirects'), 'duration_seconds': metadata.get('time_total'),
                'content_type': metadata.get('content_type'), 'title': title,
                'body_sample_bytes': len(content), 'body_sample_sha256': hashlib.sha256(content).hexdigest(),
                'challenge_detected': challenge, 'failure_receipt': result.failure_receipt_path,
                'content_equivalence_verified': False}

def verify_inventory(inventory):
    path=checked_ref(inventory['candidate'])
    with fitz.open(path) as document:
        actual={(n+1,a['xref'],a['uri']) for n in range(len(document))
                for a in document[n].get_links() if a['kind']==fitz.LINK_URI}
    expected={(a['page'],a['xref'],a['uri']) for a in inventory['annotations'] if a.get('uri')}
    if len(expected)!=sum(bool(a.get('uri')) for a in inventory['annotations']) or actual!=expected:
        raise ValueError('external_inventory_does_not_equal_actual_saved_pdf')
    return {'candidate':reference(path),'uri_annotations':len(actual),'unique_uris':len({r[2] for r in actual}),
            'status':'pass','actual_pdf_scope_verified':True}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('--start', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.inventory.stat().st_size>16*1024*1024: raise ValueError('external_inventory_size_limit')
    raw = args.inventory.read_bytes(); inventory = json.loads(raw)
    actual_scope=verify_inventory(inventory)
    urls = sorted({a['uri'] for a in inventory['annotations'] if a.get('uri')})
    own = urls[args.start:args.start + POLICY['maximum_urls_per_batch']]
    if args.start < 0 or not own or args.output.exists(): raise ValueError('external_batch_invalid_or_exists')
    rows = [check_one(url, receipt_dir=args.output.parent / 'network_receipts') for url in own]
    for row in rows:
        row['annotations'] = [{'page': a['page'], 'xref': a['xref']} for a in inventory['annotations'] if a.get('uri') == row['uri']]
    report = {'schema_version': 'external-link-check@1', 'policy': POLICY,
              'candidate': inventory['candidate'], 'inventory': {'path': str(args.inventory.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()},
              'checked_at': datetime.now(timezone.utc).isoformat(), 'start': args.start,
              'actual_scope':actual_scope,
              'unique_total': len(urls), 'rows': rows, 'counts': dict(Counter(r['status'] for r in rows)),
              'quality_pass': False, 'strict_delivery': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'counts': report['counts']}, ensure_ascii=False))

if __name__ == '__main__': main()
