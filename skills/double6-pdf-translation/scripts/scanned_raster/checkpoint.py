"""可中断扫描翻译的响应断点；只复用模型返回，不复用渲染或验收。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import uuid


class CheckpointError(RuntimeError):
    pass


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')


def implementation_digest(scripts: Path) -> str:
    files = {str(p.relative_to(scripts)): digest(p.read_bytes()) for p in sorted(scripts.rglob('*.py')) if '__pycache__' not in p.parts}
    return digest(encode(files))


def execution_identity(input_sha256: str, args, implementation_sha256: str) -> dict:
    model_fingerprint = str(getattr(args, 'scanned_model_fingerprint', '') or '')
    if not re.fullmatch('[a-f0-9]{64}', model_fingerprint):
        raise CheckpointError('checkpoint requires a SHA-256 fingerprint of the frozen model/provider revision')
    excluded = {'output_dir', 'scanned_checkpoint_dir', 'ignore_translation_cache', 'scanned_max_pages', 'pages'}
    config = {k:v for k,v in vars(args).items() if k not in excluded}
    # 不把配置原值落盘；本地术语/上下文文件变化也必须使缓存失效。
    inputs = {}
    for key in ['context_file', 'glossary', 'glossary_path', 'term_policy', 'term_policy_path', 'entity_map', 'entity_map_path']:
        value = config.get(key)
        if value:
            path = Path(value)
            if not path.is_file():
                raise CheckpointError(f'declared context file missing: {key}')
            inputs[key] = digest(path.read_bytes())
    return {'schema_version':1, 'source_sha256':input_sha256, 'configuration_sha256':digest(encode(config)),
            'context_files_sha256':inputs, 'model_fingerprint':model_fingerprint, 'implementation_sha256':implementation_sha256}


class ResponseCheckpoint:
    """单写者、原子提交、逐条校验；内核释放锁后可在新 attempt 恢复。"""
    def __init__(self, root: Path, identity: dict):
        self.identity = identity
        self.namespace = digest(encode(identity))
        self.directory = root.resolve() / self.namespace
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stats = {'cache_hits':0, 'model_calls':0, 'failed_calls':0, 'corrupt_entries':0}
        self.lock = None

    def __enter__(self):
        import fcntl
        self.lock = (self.directory / 'writer.lock').open('a+b')
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close(); self.lock = None
            raise CheckpointError('checkpoint namespace is in use by a live writer')
        try:
            identity_path = self.directory / 'identity.json'
            if identity_path.exists():
                if identity_path.read_bytes() != encode(self.identity):
                    raise CheckpointError('checkpoint identity file changed')
            else:
                self._commit(identity_path, encode(self.identity))
        except BaseException:
            self.__exit__(None,None,None)
            raise
        return self

    def __exit__(self, *_):
        if self.lock is not None:
            self.lock.close(); self.lock = None

    def _commit(self, path: Path, value: bytes):
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
        with temporary.open('xb') as handle:
            handle.write(value); handle.flush(); os.fsync(handle.fileno())
        # 不覆盖已有证据。进程在 link 前退出，仅留下不参与读取的 pending 文件。
        try:
            os.link(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def translate(self, source: str, args, translator):
        if self.lock is None:
            raise CheckpointError('checkpoint writer lock is not held')
        key = digest(source.encode('utf-8'))
        path = self.directory / (key + '.json')
        if path.exists():
            try:
                if path.stat().st_size > 4*1024*1024:
                    raise ValueError('oversized checkpoint')
                entry = json.loads(path.read_text(encoding='utf-8'))
                response = entry['response']
                if (not isinstance(response, str) or not response.strip() or entry['namespace'] != self.namespace
                    or entry['source_sha256'] != key or entry['response_sha256'] != digest(response.encode('utf-8'))):
                    raise ValueError('checkpoint integrity mismatch')
            except (ValueError, KeyError, TypeError) as exc:
                self.stats['corrupt_entries'] += 1
                raise CheckpointError(f'rejected damaged checkpoint {key}') from exc
            self.stats['cache_hits'] += 1
            return response
        self.stats['model_calls'] += 1
        try:
            response = translator(source, args)
            if not isinstance(response, str) or not response.strip() or len(response.encode('utf-8')) > 3*1024*1024:
                raise ValueError('empty, invalid or oversized model response')
        except BaseException:
            self.stats['failed_calls'] += 1
            raise
        self._commit(path, encode({'namespace':self.namespace, 'source_sha256':key, 'response':response,
                                  'response_sha256':digest(response.encode('utf-8'))}))
        return response

    def report(self) -> dict:
        return {'namespace':self.namespace, 'directory':str(self.directory), **self.stats,
                'scope':'raw_model_responses_only', 'quality_acceptance_reused':False}
