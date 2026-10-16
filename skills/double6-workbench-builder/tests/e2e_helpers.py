"""端到端测试辅助：只在临时目录里驱动公开 CLI，按 SKILL.md 的六步流程走完一次构建。

注意：这里生成的“按推荐”回答、产品确认与视觉确认只用于自动化测试的临时 run，
不得写入生产 run，也不代表任何真实用户确认（见 runtime-contract.md“事件与产品合同”）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / "scripts" / "double6.py"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


class CliError(AssertionError):
    pass


def cli(*args: str, env: dict[str, str] | None = None, ok_codes: tuple[int, ...] = (0,)) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=SKILL_ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, **(env or {})},
        check=False,
    )
    stream = result.stdout if result.stdout.strip() else result.stderr
    if result.returncode not in ok_codes:
        raise CliError(f"{' '.join(args[:3])} exit={result.returncode}: {result.stderr or result.stdout}")
    return json.loads(stream)


def route_catalog(tmp: Path) -> list[dict[str, Any]]:
    return cli("start", "--run", str(tmp / "catalog-probe"), "--request", "做一个个人工作台")["route_options"]


def _write(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _events(run: Path) -> list[dict[str, Any]]:
    return json.loads((run / "events.json").read_text(encoding="utf-8"))["events"]


def _next_turn(run: Path) -> int:
    return max(int(row.get("turn_index", 0)) for row in _events(run)) + 1


def respond(run: Path, event: dict[str, Any]) -> dict[str, Any]:
    event = {"turn_index": _next_turn(run), **event}
    return cli("respond", "--run", str(run), "--event-file", str(_write(run.parent / f"{run.name}-event.json", event)))


def product_from_snapshot(run: Path, product_id: str, title: str) -> dict[str, Any]:
    """按不可变推荐快照组装最小合规产品合同（surface/starter 由 CLI 从快照补全）。"""
    from double6_runtime.workflow import draft_product_from_snapshot
    requirements = json.loads((run / "requirements.json").read_text(encoding="utf-8"))
    events = json.loads((run / "events.json").read_text(encoding="utf-8"))
    return draft_product_from_snapshot(requirements, events, product_id=product_id, title=title)


def run_to_candidate(tmp: Path, name: str, request: str, route: dict[str, Any], title: str) -> tuple[Path, dict[str, Any]]:
    """start → （按推荐回答）→ propose → approve_product → build → approve_visual。"""
    run = tmp / name
    request_file = tmp / f"{name}-request.txt"
    request_file.write_text(request, encoding="utf-8")
    route_file = _write(tmp / f"{name}-route.json", route)
    started = cli("start", "--run", str(run), "--request-file", str(request_file), "--route-file", str(route_file))
    guard = 0
    while started.get("state") == "clarifying" or json.loads((run / "run.json").read_text(encoding="utf-8"))["state"] == "clarifying":
        guard += 1
        if guard > 9:
            raise CliError("澄清超出五个普通问题与四类必要授权确认")
        requirements = json.loads((run / "requirements.json").read_text(encoding="utf-8"))
        pending = next(row for row in requirements["critical_decisions"] if row["status"] == "missing")
        started = respond(run, {"event_id": f"answer-{guard}", "raw_text": "按推荐", "intent": "answer",
                                "decision_id": pending["decision_id"], "normalized_value": "recommended"})
    product_file = _write(tmp / f"{name}-product.json", product_from_snapshot(run, name.replace("--", "-"), title))
    cli("propose", "--run", str(run), "--product-file", str(product_file))
    product = json.loads((run / "product.json").read_text(encoding="utf-8"))
    respond(run, {"event_id": "approve-product", "raw_text": "确认，按这个做", "intent": "approve_product",
                  "presented_content_sha256": product["presentation"]["content_sha256"]})
    built = cli("build", "--run", str(run))
    respond(run, {"event_id": "approve-visual", "raw_text": "看过了，可以", "intent": "approve_visual",
                  "presented_candidate_sha256": built["candidate_sha256"]})
    return run, built


def browser_ready() -> bool:
    try:
        from double6_runtime import browser_environment  # type: ignore
    except ImportError:
        sys.path.insert(0, str(SKILL_ROOT / "scripts"))
        from double6_runtime import browser_environment  # type: ignore
    return browser_environment()["status"] == "ready"
