# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-24：回环中间层的真实上游身份（翻译缓存身份绑定）；变更见Skill根目录MODIFICATIONS.md。
"""本项目回环中间层（HY-MT 兼容代理）所转发的真实上游身份。

问题：经本机兼容代理时，后端只看到 ``http://127.0.0.1:<port>/v1``。同一端口、同一模型名先后代理到不同真实上游时，
仅凭本机地址做缓存身份会把甲服务的译文当作乙服务的结果复用。

合同（本项目自己的回环代理，不改上游/后端的 OpenAI 协议）：
- 代理对 ``GET <base_url>/double6/upstream-identity`` 返回 :func:`build_identity` 的 JSON；
- 代理的每个响应（含错误响应）都带头 ``X-Double6-Upstream-Identity``，值为同一 JSON 的紧凑编码；
- 后端翻译器（vendored OpenAITranslator、本项目 qwen-cli 适配器命令串）在任何缓存读写前取得该身份并写入缓存身份；
  之后每个响应都核对头部，不一致（代理重启/端口被换到另一上游）即失败关闭，不写缓存、不复用。

身份只含规范化的上游地址、上游模型与传输方式：去掉 userinfo、片段与凭据类查询参数，绝不含凭据值，
因此仅凭据轮换仍复用缓存。非回环地址不探测（地址本身即真实上游）；回环地址上不是本项目代理的服务
（如直连 LM Studio）返回 404 或不合合同的内容，按直连处理。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

IDENTITY_KIND = "double6_upstream_identity"
IDENTITY_VERSION = 1
IDENTITY_PATH = "/double6/upstream-identity"
IDENTITY_HEADER = "X-Double6-Upstream-Identity"
UPSTREAM_IDENTITY_MISMATCH = "upstream_identity_mismatch"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# 查询参数名按非字母数字切词（小写），任一词属于下列集合即视为凭据类，规范化时整项去掉（值从不进入身份）。
CREDENTIAL_QUERY_WORDS = frozenset({"key", "apikey", "token", "accesstoken", "apitoken", "secret", "password", "passwd",
                                    "auth", "authorization", "signature", "sig", "credential", "credentials", "code"})
_FIELDS = ("kind", "version", "upstream_base_url", "upstream_model", "transport")
_DEFAULT_PORTS = {"http": 80, "https": 443}


class UpstreamIdentityMismatch(RuntimeError):
    """响应声明的上游身份与缓存身份不一致：失败关闭。消息只含身份（地址/模型/传输），不含凭据。"""


def _credential_like(name: str) -> bool:
    return any(word in CREDENTIAL_QUERY_WORDS for word in re.split(r"[^a-z0-9]+", name.lower()))


def normalize_endpoint(url: str | None) -> str:
    """端点的稳定身份：小写 scheme/host、去默认端口、去 userinfo/片段/凭据类查询参数、去末尾斜杠。"""
    text = str(url or "").strip()
    try:
        parts = urlsplit(text)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return text.split("@")[-1].split("?")[0].split("#")[0].rstrip("/")
    scheme = parts.scheme.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{port}" if port and port != _DEFAULT_PORTS.get(scheme) else "")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _credential_like(k)))
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), query, ""))


def is_loopback(url: str | None) -> bool:
    try:
        return urlsplit(str(url or "")).hostname in LOOPBACK_HOSTS
    except ValueError:
        return False


def build_identity(upstream_base_url: str, model: str | None, transport: str | None) -> dict:
    return {"kind": IDENTITY_KIND, "version": IDENTITY_VERSION, "upstream_base_url": normalize_endpoint(upstream_base_url),
            "upstream_model": str(model or ""), "transport": str(transport or "openai_compatible")}


def encode_identity(identity: dict) -> str:
    return json.dumps({name: identity[name] for name in _FIELDS}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def decode_identity(value) -> dict | None:
    """校验并重建身份；不合合同返回 None（只接受已知字段，忽略其它内容）。"""
    try:
        data = json.loads(value) if isinstance(value, (str, bytes)) else value
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("kind") != IDENTITY_KIND or data.get("version") != IDENTITY_VERSION:
        return None
    if not all(isinstance(data.get(name), str) and data.get(name) for name in ("upstream_base_url", "transport")):
        return None
    if not isinstance(data.get("upstream_model"), str):
        return None
    return build_identity(data["upstream_base_url"], data["upstream_model"], data["transport"])


def identity_url(base_url: str) -> str:
    return str(base_url).rstrip("/") + IDENTITY_PATH


def discover(base_url: str | None, timeout: float = 3.0) -> dict | None:
    """回环端点上的本项目代理：取得其真实上游身份。非回环、连不上或不是本项目代理：None。不发送任何凭据。"""
    if not is_loopback(base_url):
        return None
    request = urllib.request.Request(identity_url(str(base_url)), method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = decode_identity(response.read(65536).decode("utf-8", errors="replace"))
            header = decode_identity(response.headers.get(IDENTITY_HEADER))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return body if body is not None and body == header else None


def verify_header(bound: dict | None, header_value: str | None) -> None:
    """核对一次响应的身份头与缓存身份。两者都无：直连，通过；其余不一致：抛 UpstreamIdentityMismatch。"""
    declared = decode_identity(header_value) if header_value is not None else None
    if header_value is not None and declared is None:
        raise UpstreamIdentityMismatch(f"{UPSTREAM_IDENTITY_MISMATCH}: malformed identity header")
    if declared == bound:
        return
    raise UpstreamIdentityMismatch(UPSTREAM_IDENTITY_MISMATCH + ": " + json.dumps(
        {"bound": bound, "response": declared}, ensure_ascii=False, sort_keys=True))


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容代理、翻译器与适配器调用的上游身份职责模块，不提供独立命令。"
