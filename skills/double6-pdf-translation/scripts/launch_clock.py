"""进程启动顺序的单调证据（不受墙钟回拨/前跳影响），供有界任务的遗留进程核实使用（PR #21 review-2）。

- Linux：``/proc/<pid>/stat`` 第 22 字段 starttime（开机以来的时钟滴答数），同一次开机内单调；
  开机标识为 ``/proc/sys/kernel/random/boot_id``。
- macOS：``proc_pid_rusage(RUSAGE_INFO_V0).ri_proc_start_abstime``（mach 绝对时间），同一次开机内单调；
  开机标识为 ``sysctl kern.bootsessionuuid``。
- 其它平台或读取失败：返回 None（调用方必须按“证据缺失”处理，不得据此排除任何进程）。

只用于“证明某进程启动早于本次启动根进程”（因而不可能是其后代）；读不到或开机标识不同即无证据。"""
from __future__ import annotations

import os
import sys
from typing import Any

LINUX_CLOCK = "linux_proc_starttime_ticks"
DARWIN_CLOCK = "darwin_proc_start_abstime"


def boot_key() -> str | None:
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as stream:
                return stream.read().strip() or None
        if sys.platform == "darwin":
            import ctypes
            libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
            size = ctypes.c_size_t(64)
            buf = ctypes.create_string_buffer(64)
            if libc.sysctlbyname(b"kern.bootsessionuuid", buf, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
                return None
            return buf.value.decode("ascii", "replace") or None
    except Exception:  # noqa: BLE001 - 证据缺失
        return None
    return None


def _linux_start(pid: int) -> int | None:
    with open(f"/proc/{int(pid)}/stat", encoding="ascii", errors="replace") as stream:
        raw = stream.read()
    fields = raw[raw.rindex(")") + 2:].split()
    return int(fields[19])   # 第 22 字段（状态字段为第 3 字段，即 ')' 后第 0 个）


def _darwin_start(pid: int) -> int | None:
    import ctypes

    class RusageInfoV0(ctypes.Structure):
        _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [(name, ctypes.c_uint64) for name in (
            "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups", "ri_pageins",
            "ri_wired_size", "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime", "ri_proc_exit_abstime")]
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    info = RusageInfoV0()
    if lib.proc_pid_rusage(ctypes.c_int(int(pid)), ctypes.c_int(0), ctypes.byref(info)) != 0:
        return None
    return int(info.ri_proc_start_abstime) or None


def start_clock(pid: int) -> int | None:
    """进程启动时刻的单调读数；取不到返回 None。"""
    try:
        if sys.platform.startswith("linux"):
            return _linux_start(pid)
        if sys.platform == "darwin":
            return _darwin_start(pid)
    except Exception:  # noqa: BLE001 - 证据缺失
        return None
    return None


def start_evidence(pid: int | None = None) -> dict[str, Any] | None:
    """{"clock", "boot", "start"}：本进程（默认）或指定进程的启动单调证据；任一项取不到返回 None。"""
    pid = os.getpid() if pid is None else int(pid)
    clock = LINUX_CLOCK if sys.platform.startswith("linux") else DARWIN_CLOCK if sys.platform == "darwin" else None
    boot = boot_key()
    start = start_clock(pid)
    if clock is None or boot is None or start is None:
        return None
    return {"clock": clock, "boot": boot, "start": start}


def started_before(pid: int, reference: dict[str, Any] | None) -> bool | None:
    """True：同一次开机内 pid 的启动单调读数严格早于参考（不可能是参考进程的后代）；
    False：不早于参考；None：无法判断（无参考、时钟类型/开机标识不同、读不到）。"""
    if not isinstance(reference, dict) or not isinstance(reference.get("start"), int):
        return None
    current = start_evidence(pid)
    if current is None or current["clock"] != reference.get("clock") or current["boot"] != reference.get("boot"):
        return None
    return current["start"] < reference["start"]
