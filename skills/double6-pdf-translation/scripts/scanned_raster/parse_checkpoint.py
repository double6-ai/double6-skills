"""逐页/逐档解析断点；保留原始解析证据引用，每次重做策略、渲染与验收。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .checkpoint import CheckpointError, ResponseCheckpoint, digest, encode


def file_sha(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def parse_identity(source_sha: str, args, implementation_sha: str) -> dict:
    fingerprint = str(getattr(args, 'scanned_parser_fingerprint', '') or '')
    if not re.fullmatch('[a-f0-9]{64}', fingerprint):
        raise CheckpointError('parse checkpoint requires frozen parser packages/models/service evidence SHA-256')
    keys = ['scanned_parser', 'mineru_tier', 'mineru_runtime', 'allow_cloud_layout',
            'emit_mineru_render_candidates', 'scanned_page_profile']
    return {'schema_version': 1, 'stage': 'raw_page_parser', 'source_sha256': source_sha,
            'parser_fingerprint': fingerprint, 'implementation_sha256': implementation_sha,
            'configuration_sha256': digest(encode({k: getattr(args, k, None) for k in keys}))}


def artifacts(payload: dict) -> dict[str, str]:
    """引用原 attempt 的原始解析文件；枚举和字节数均有界，拒绝符号链接。"""
    paths = set()
    raw = payload.get('raw_output_dir')
    roots = [Path(raw)] if raw else []
    candidates = payload.get('render_candidates') or []
    if not isinstance(candidates, list) or any(not isinstance(p, str) for p in candidates):
        raise CheckpointError('invalid parser render candidate paths')
    for root in roots:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise CheckpointError('raw parser directory missing or invalid')
        for p in root.rglob('*'):
            if p.is_symlink():
                raise CheckpointError('symlink in parser evidence')
            if p.is_file():
                paths.add(p)
            if len(paths) > 1000:
                raise CheckpointError('parser evidence file limit exceeded')
    paths.update(Path(p) for p in candidates)
    if len(paths) > 1000:
        raise CheckpointError('parser evidence file limit exceeded')
    total = 0
    result = {}
    for p in sorted(paths):
        if not p.is_absolute() or p.is_symlink() or not p.is_file():
            raise CheckpointError('parser evidence file missing or invalid')
        total += p.stat().st_size
        if total > 512 * 1024**2:
            raise CheckpointError('parser evidence byte limit exceeded')
        result[str(p)] = file_sha(p)
    return result


class ParseCheckpoint(ResponseCheckpoint):
    def __init__(self, root: Path, identity: dict):
        super().__init__(root, identity)
        self.stats = {'cache_hits': 0, 'parser_calls': 0, 'failed_calls': 0, 'corrupt_entries': 0}

    def capture(self, request: dict, producer, *, source_pdf: Path):
        if self.lock is None:
            raise CheckpointError('parse checkpoint writer lock is not held')
        if file_sha(source_pdf) != self.identity['source_sha256']:
            raise CheckpointError('source PDF changed before parsing')
        key = digest(encode(request))
        path = self.directory / (key + '.json')
        if path.exists():
            try:
                if path.stat().st_size > 16 * 1024**2:
                    raise ValueError('oversized parse checkpoint')
                entry = json.loads(path.read_text())
                value = entry['payload']
                if (not isinstance(value, dict) or entry['namespace'] != self.namespace
                        or entry['request'] != request or entry['payload_sha256'] != digest(encode(value))
                        or artifacts(value) != entry['artifacts_sha256']):
                    raise ValueError('parse checkpoint identity/content/evidence mismatch')
            except (ValueError, KeyError, TypeError, OSError, CheckpointError) as exc:
                self.stats['corrupt_entries'] += 1
                raise CheckpointError(f'rejected damaged parse checkpoint {key}') from exc
            self.stats['cache_hits'] += 1
            return value
        self.stats['parser_calls'] += 1
        try:
            value = producer()
            if not isinstance(value, dict) or len(encode(value)) > 12 * 1024**2:
                raise CheckpointError('invalid or oversized parser payload')
            evidence = artifacts(value)
            if file_sha(source_pdf) != self.identity['source_sha256']:
                raise CheckpointError('source PDF changed during parsing')
            self._commit(path, encode({'namespace': self.namespace, 'request': request, 'payload': value,
                                      'payload_sha256': digest(encode(value)), 'artifacts_sha256': evidence}))
        except BaseException:
            self.stats['failed_calls'] += 1
            raise
        # Decouple saved raw results from in-place geometry/translation policy mutations.
        return json.loads(encode(value))

    def report(self) -> dict:
        return {'namespace': self.namespace, 'directory': str(self.directory), **self.stats,
                'scope': 'raw_page_parser_results', 'raw_artifacts': 'original_attempt_retained_and_sha_verified',
                'quality_acceptance_reused': False}
