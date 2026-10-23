"""共享 run_command 的受控子进程入口；登记身份后原位执行目标命令。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import psutil


def main() -> int:
    receipt, nonce, *command = sys.argv[1:]
    if not command:
        raise ValueError("bounded launch requires a command")
    if os.name == "posix":
        os.setsid()
    current = psutil.Process()
    identity = {"nonce": nonce, "pid": current.pid, "parent_pid": current.ppid(),
                "created_at": current.create_time(), "process_group": os.getpgrp() if os.name == "posix" else None}
    # 启动顺序的单调证据（不受墙钟跳变影响；取不到则不写，核实端按证据缺失失败关闭）——PR #21 review-2。
    try:
        from launch_clock import start_evidence
        evidence = start_evidence(current.pid)
    except Exception:  # noqa: BLE001 - 证据缺失不影响启动
        evidence = None
    if evidence:
        identity["start_evidence"] = evidence
    # 发布完整 JSON 后才能被监控端读取；已有 attempt 不可覆盖。
    path = Path(receipt)
    temporary = path.with_suffix(".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(identity, stream)
    if path.exists():
        raise FileExistsError(path)
    temporary.rename(path)
    if path.with_suffix(".cancel").exists():
        return 130
    os.execvpe(command[0], command, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
