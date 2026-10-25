# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-24：凭据入口与后端原生传参（凭据不进入子进程 argv）；变更见Skill根目录MODIFICATIONS.md。
"""翻译服务凭据的唯一入口与各后端的原生非 argv 通道。

- 用户入口只有环境变量 ``LOCAL_TRANSLATION_API_KEY``（``run_pdf_translation.py --api-key`` 仅为兼容保留，
  它本身会出现在该进程 argv 中，不推荐）。``OPENAI_API_KEY`` 不再被静默采用。
- 回环地址（localhost / 127.0.0.1 / ::1）且未提供凭据时使用占位 ``local-no-auth``，它不是凭据；
  其它地址未提供凭据时在启动任何子进程前以稳定错误 ``remote_backend_requires_explicit_api_key`` 停止。
- PDF 后端（vendored PDFMathTranslate-next 2.8.2）原生读取 ``PDF2ZH_OPENAI_API_KEY``
  （``pdf2zh_next/config/main.py`` ``parse_env_vars`` 前缀 ``PDF2ZH_``）；本项目 Qwen 适配器读取
  ``LOCAL_TRANSLATION_API_KEY``。凭据只经子进程环境传递。

边界：同一用户（及 root）可读取 ``/proc/<pid>/environ``，环境变量不是保密隔离边界；本模块只保证凭据
不进入子进程 argv、日志、回执、清单、异常与翻译缓存，不宣称完全隔离。
"""
from __future__ import annotations

from typing import Mapping, MutableMapping
from urllib.parse import urlsplit

CREDENTIAL_ENV = "LOCAL_TRANSLATION_API_KEY"
PDF_BACKEND_CREDENTIAL_ENV = "PDF2ZH_OPENAI_API_KEY"
LOCAL_NO_AUTH_PLACEHOLDER = "local-no-auth"
REMOTE_REQUIRES_KEY = "remote_backend_requires_explicit_api_key"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# 子进程不需要、且可能被后端以其它方式读取或打印的变量：每次显式重设，不从外部继承。
# PDF2ZH_DEBUG 会让 pdf2zh_next 以 DEBUG 记录完整 settings（含 openai_api_key）。
BACKEND_ENV_STRIP = (PDF_BACKEND_CREDENTIAL_ENV, CREDENTIAL_ENV, "OPENAI_API_KEY", "PDF2ZH_DEBUG")


def is_loopback_endpoint(base_url: str | None) -> bool:
    try:
        return urlsplit(str(base_url or "")).hostname in LOOPBACK_HOSTS
    except ValueError:
        return False


def resolve_credential(explicit: str | None, base_url: str | None) -> str:
    """返回要交给后端的值：显式凭据、回环占位，或抛出稳定错误（不含任何凭据值）。"""
    if explicit:
        return explicit
    if is_loopback_endpoint(base_url):
        return LOCAL_NO_AUTH_PLACEHOLDER
    raise ValueError(REMOTE_REQUIRES_KEY)


def credential_source(environ: Mapping[str, str]) -> dict:
    """只报告来源与是否存在，从不记录值。"""
    present = bool(environ.get(CREDENTIAL_ENV))
    ignored = [name for name in ("OPENAI_API_KEY",) if environ.get(name)]
    return {"variable": CREDENTIAL_ENV, "source": ("env:" + CREDENTIAL_ENV) if present else "none",
            "present": present, "ignored_variables_present": ignored, "value_recorded": False}


def scrub_backend_env(env: MutableMapping[str, str]) -> MutableMapping[str, str]:
    for name in BACKEND_ENV_STRIP:
        env.pop(name, None)
    return env


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由翻译入口调用的凭据职责模块，不提供独立命令。"
