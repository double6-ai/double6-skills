# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""保留旧单文件入口的替换式扩展接口。

源锚渲染器会临时替换扫描入口的样式/绘制回调。实现拆分后，在旧入口
调用前把显式替换和恢复同步到持有实现的模块；普通调用直接使用原函数。
"""
from __future__ import annotations
from functools import wraps
import sys
from types import ModuleType

SCRIPT_INTERFACE = 'internal-module'
SCRIPT_INTERFACE_REASON = '为历史入口的回调替换和恢复提供兼容边界。'


def bind_legacy_exports(namespace, function_owners, component_modules):
    originals = {name: namespace[name] for name in function_owners}
    baseline = {}
    observed = {}

    def sync_overrides():
        for name, original in baseline.items():
            current = namespace.get(name)
            if current is observed.get(name):
                continue
            observed[name] = current
            value = originals.get(name, original) if current is original else current
            for module_name in component_modules:
                module = sys.modules.get(module_name)
                if module is not None and name in vars(module):
                    setattr(module, name, value)

    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            sync_overrides()
            return function(*args, **kwargs)
        return call

    for name, function in originals.items():
        namespace[name] = decorate(function)
    baseline.update({name: value for name, value in namespace.items()
                     if not name.startswith('__') and name not in {'bind_legacy_exports'}})
    observed.update(baseline)

    module = sys.modules.get(namespace.get('__name__'))
    if module is not None and vars(module) is namespace:
        class CompatibleModule(ModuleType):
            def __setattr__(self, name, value):
                super().__setattr__(name, value)
                if name in baseline:
                    sync_overrides()

            def __delattr__(self, name):
                super().__delattr__(name)
                if name in baseline:
                    sync_overrides()
        module.__class__ = CompatibleModule
