# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-24：LaTeX 直连后端的回环凭据转发（真实凭据不进入子进程 argv）；变更见Skill根目录MODIFICATIONS.md。
"""本进程内、只绑定 127.0.0.1 的 OpenAI-compatible 透明转发器。

用途：``pdf2zh_skill.cli``（LaTeX 直连后端，本仓库未随包分发）只接受 ``--translation-api-key`` argv，
其非 argv 凭据通道无法核实。需要真实凭据时，子进程改连本转发器，argv 中只出现本次运行的一次性访问令牌；
转发器按用户显式给出的上游地址原样转发请求体（模型、参数不改），并在本进程内附加真实上游凭据。

- 只接受携带一次性令牌的请求（``Authorization: Bearer <token>``），否则 401，不转发；
- 路径 ``/v1/<rest>`` → ``<upstream_base_url>/<rest>``；请求体、方法、Content-Type 原样；上游状态码与响应体原样返回；
- 生命周期：调用方在 finally 中 ``shutdown()``；它是本进程线程，不产生新进程，原进程树回收合同不变；
- 错误响应与日志从不包含凭据或令牌。

边界：一次性令牌在子进程 argv 中，可被能读取该进程 argv 的主体在运行期间用于经本转发器发请求，但拿不到真实凭据；
同用户环境（/proc/<pid>/environ、进程内存）不是保密边界。
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIND_HOST = "127.0.0.1"
FORWARDER_UNAVAILABLE = "latex_direct_credential_forwarder_unavailable"


class _Handler(BaseHTTPRequestHandler):
    server_version = "LoopbackCredentialForwarder/1"

    def log_message(self, format, *args):  # noqa: A002 - 不写访问日志
        return

    def _reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, kind: str) -> None:
        self._reply(status, json.dumps({"error": {"type": kind}}).encode("utf-8"))

    def _forward(self, method: str) -> None:
        server: CredentialForwarder = self.server  # type: ignore[assignment]
        presented = self.headers.get("Authorization", "")
        if not hmac.compare_digest(presented.encode("utf-8"), ("Bearer " + server.access_token).encode("utf-8")):
            server.stats["rejected_unauthorized"] += 1
            return self._error(401, "forwarder_access_token_required")
        if not self.path.startswith("/v1/") and self.path != "/v1":
            return self._error(404, "forwarder_path_not_under_v1")
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")) if method == "POST" else None
        headers = {"Authorization": "Bearer " + server.credential}
        if self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]
        url = server.upstream_base_url + self.path[len("/v1"):]
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        server.stats["forwarded_requests"] += 1
        try:
            with urllib.request.urlopen(request, timeout=server.timeout) as response:
                payload = response.read()
                self._reply(response.status, payload, response.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as exc:
            server.stats["upstream_http_errors"] += 1
            self._reply(exc.code, exc.read(), exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            server.stats["upstream_unreachable"] += 1
            self._error(502, "forwarder_upstream_unreachable:" + type(exc).__name__)

    def do_POST(self) -> None:
        self._forward("POST")

    def do_GET(self) -> None:
        self._forward("GET")


class CredentialForwarder(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, upstream_base_url: str, credential: str, timeout: float):
        super().__init__((BIND_HOST, 0), _Handler)
        self.upstream_base_url = upstream_base_url.rstrip("/")
        self.credential = credential
        self.access_token = "fwd-" + secrets.token_urlsafe(24)
        self.timeout = float(timeout)
        self.stats = {"forwarded_requests": 0, "rejected_unauthorized": 0, "upstream_http_errors": 0, "upstream_unreachable": 0}
        self._thread = threading.Thread(target=self.serve_forever, name="credential-forwarder", daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://{BIND_HOST}:{self.server_address[1]}/v1"

    def describe(self) -> dict:
        """可写入清单的描述：不含凭据与令牌。"""
        return {"mode": "loopback_credential_forwarder", "bind_host": BIND_HOST, "port": int(self.server_address[1]),
                "upstream_base_url": self.upstream_base_url, "credential_recorded": False,
                "access_token_recorded": False, "stats": dict(self.stats)}

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)


def start_credential_forwarder(upstream_base_url: str, credential: str, *, timeout: float) -> CredentialForwarder:
    if not credential:
        raise ValueError("credential required for forwarder")
    server = CredentialForwarder(upstream_base_url, credential, timeout)
    server._thread.start()
    return server


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由 LaTeX 直连渲染调用的回环转发职责模块，不提供独立命令。"
