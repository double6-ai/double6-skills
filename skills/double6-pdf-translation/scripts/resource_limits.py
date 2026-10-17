# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：2.0.0-rc.3 新增；变更见Skill根目录MODIFICATIONS.md。
"""有界作业的内存/时限配置：命令行 > 环境变量 > 平台默认值。

内存口径：Linux 默认按进程树 PSS（按共享页比例分摊）计量。pdf2zh/BabelDOC 会 fork
出与父进程共享大量只读页的子进程，逐进程 RSS 相加会把共享页重复计算（实测 RSS 和
5.16 GiB 对应 PSS 2.64 GiB）。macOS 保持 RSS 口径与原 3 GiB/120 s 合同不变。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Mapping

GIB = 1024 ** 3
MIB = 1024 ** 2
LEGACY_CONTRACT = {'task_rss_bytes': 3 * GIB, 'per_job_seconds': 120, 'concurrency': 1}
PLATFORM_DEFAULTS = {
    'darwin': {'task_rss_bytes': 3 * GIB, 'per_job_seconds': 120, 'memory_metric': 'rss'},
    'linux': {'task_rss_bytes': 4 * GIB, 'per_job_seconds': 300, 'memory_metric': 'pss'},
}
FALLBACK_DEFAULT = {'task_rss_bytes': 4 * GIB, 'per_job_seconds': 300, 'memory_metric': 'rss'}
MEMORY_BOUNDS = (512 * MIB, 64 * GIB)
SECONDS_BOUNDS = (30, 7200)
METRICS = ('rss', 'pss')
# 默认值不超过物理内存的 25%（原项目授权阈值）；显式配置最多放宽到 50%。
DEFAULT_TOTAL_FRACTION = 0.25
EXPLICIT_TOTAL_FRACTION = 0.50
ENV_MEMORY = 'PAPER_TRANSLATION_TASK_MEMORY_MIB'
ENV_SECONDS = 'PAPER_TRANSLATION_JOB_TIMEOUT_SECONDS'
ENV_METRIC = 'PAPER_TRANSLATION_MEMORY_METRIC'


class ResourceLimitError(ValueError):
    pass


def platform_key(platform: str | None = None) -> str:
    platform = platform or sys.platform
    return 'darwin' if platform.startswith('darwin') else 'linux' if platform.startswith('linux') else platform


def _int(value: Any, name: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ResourceLimitError(f'invalid_{name}: {value!r}') from exc


def resolve_limits(*, memory_mib: int | None = None, timeout_seconds: int | None = None,
                   memory_metric: str | None = None, platform: str | None = None,
                   environ: Mapping[str, str] | None = None, total_memory: int | None = None) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    key = platform_key(platform)
    base = dict(PLATFORM_DEFAULTS.get(key, FALLBACK_DEFAULT))
    source = {'task_rss_bytes': 'platform_default', 'per_job_seconds': 'platform_default', 'memory_metric': 'platform_default'}
    if memory_mib is not None:
        base['task_rss_bytes'] = _int(memory_mib, 'memory_mib') * MIB; source['task_rss_bytes'] = 'cli'
    elif environ.get(ENV_MEMORY):
        base['task_rss_bytes'] = _int(environ[ENV_MEMORY], ENV_MEMORY) * MIB; source['task_rss_bytes'] = 'env'
    if timeout_seconds is not None:
        base['per_job_seconds'] = _int(timeout_seconds, 'timeout_seconds'); source['per_job_seconds'] = 'cli'
    elif environ.get(ENV_SECONDS):
        base['per_job_seconds'] = _int(environ[ENV_SECONDS], ENV_SECONDS); source['per_job_seconds'] = 'env'
    if memory_metric is not None:
        base['memory_metric'] = memory_metric; source['memory_metric'] = 'cli'
    elif environ.get(ENV_METRIC):
        base['memory_metric'] = environ[ENV_METRIC].strip().lower(); source['memory_metric'] = 'env'
    if base['memory_metric'] not in METRICS:
        raise ResourceLimitError(f"invalid_memory_metric: {base['memory_metric']!r} (expected rss or pss)")
    if not MEMORY_BOUNDS[0] <= base['task_rss_bytes'] <= MEMORY_BOUNDS[1]:
        raise ResourceLimitError(f"task_memory_limit_out_of_bounds: {base['task_rss_bytes'] // MIB} MiB "
                                 f"(allowed {MEMORY_BOUNDS[0] // MIB}–{MEMORY_BOUNDS[1] // MIB} MiB)")
    if not SECONDS_BOUNDS[0] <= base['per_job_seconds'] <= SECONDS_BOUNDS[1]:
        raise ResourceLimitError(f"job_timeout_out_of_bounds: {base['per_job_seconds']} s "
                                 f"(allowed {SECONDS_BOUNDS[0]}–{SECONDS_BOUNDS[1]} s)")
    explicit_memory = source['task_rss_bytes'] != 'platform_default'
    if total_memory is None:
        try:
            import psutil
            total_memory = psutil.virtual_memory().total
        except Exception:
            total_memory = None
    clamped = False
    if total_memory:
        if explicit_memory:
            if base['task_rss_bytes'] > total_memory * EXPLICIT_TOTAL_FRACTION:
                raise ResourceLimitError(
                    f"task_memory_limit_exceeds_host_authorization: {base['task_rss_bytes'] // MIB} MiB > "
                    f"{int(EXPLICIT_TOTAL_FRACTION * 100)}% of physical memory ({total_memory // MIB} MiB)")
        elif base['task_rss_bytes'] > total_memory * DEFAULT_TOTAL_FRACTION:
            base['task_rss_bytes'] = int(total_memory * DEFAULT_TOTAL_FRACTION) // MIB * MIB
            clamped = True
    return {**base, 'concurrency': 1, 'platform': key, 'source': source,
            'clamped_to_host_fraction': clamped,
            'max_total_fraction': EXPLICIT_TOTAL_FRACTION if explicit_memory else DEFAULT_TOTAL_FRACTION}


def contract_from_limits(limits: Mapping[str, Any]) -> dict[str, Any]:
    return {'task_rss_bytes': limits['task_rss_bytes'], 'per_job_seconds': limits['per_job_seconds'], 'concurrency': 1}


def validate_resource_contract(contract: Any) -> dict[str, Any]:
    """FREEZE 中的资源合同：接受旧 3 GiB/120 s 合同，或边界内的显式合同；并发恒为 1。"""
    if contract == LEGACY_CONTRACT:
        return dict(contract)
    if not isinstance(contract, dict) or set(contract) - {'task_rss_bytes', 'per_job_seconds', 'concurrency', 'memory_metric'}:
        raise ValueError('frozen resource contract differs from current workflow')
    rss, seconds = contract.get('task_rss_bytes'), contract.get('per_job_seconds')
    if (type(rss) is not int or type(seconds) is not int or contract.get('concurrency') != 1
            or not MEMORY_BOUNDS[0] <= rss <= MEMORY_BOUNDS[1] or not SECONDS_BOUNDS[0] <= seconds <= SECONDS_BOUNDS[1]
            or contract.get('memory_metric', 'rss') not in METRICS):
        raise ValueError('frozen resource contract differs from current workflow')
    return dict(contract)


def backend_timeouts(per_job_seconds: int) -> dict[str, int]:
    """后端自身超时须留在作业预算内；120 s 时与原合同 110/90 一致。"""
    return {'timeout': max(20, per_job_seconds - 10), 'openai_timeout': max(15, per_job_seconds - 30)}
