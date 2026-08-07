#!/usr/bin/env python3
"""Double6 工作台制作器的六命令公开 CLI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from double6_runtime import (  # noqa: E402
    ContractError,
    build,
    browser_environment,
    cleanup_transaction,
    clone_confirmed_run,
    evaluate,
    manifest,
    propose,
    read_json,
    read_text_arg,
    respond,
    start_run,
    status,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="double6.py", description=f"Double6 工作台制作器 {manifest()['version']}")
    commands = root.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="新建当前版本任务")
    start.add_argument("--run", required=True)
    start.add_argument("--request")
    start.add_argument("--request-file")
    start.add_argument("--route-file")
    start.add_argument("--clone-from", help="从完全相同的已确认 run 复用产品确认")

    response = commands.add_parser("respond", help="记录回答、确认、修订或视觉反馈")
    response.add_argument("--run", required=True)
    response.add_argument("--event-file", required=True)
    response.add_argument("--sources-file")

    proposal = commands.add_parser("propose", help="提交紧凑产品合同并展示理解稿")
    proposal.add_argument("--run", required=True)
    proposal.add_argument("--product-file", required=True)

    build_command = commands.add_parser("build", help="构建一个推荐方向的单文件候选")
    build_command.add_argument("--run", required=True)

    evaluation = commands.add_parser("evaluate", help="自动完成本地核心验收")
    evaluation.add_argument("--run", required=True)
    evaluation.add_argument("--preflight", action="store_true", help="仅检查 Playwright/Chromium 环境，不改变 run 状态")
    evaluation.add_argument("--skip-browser", action="store_true", help="只跑静态预检；不会写入 local_delivered")

    cleanup = commands.add_parser("cleanup", help="恢复事务 journal 并尽力清理残留 staging")
    cleanup.add_argument("--run", required=True)

    state = commands.add_parser("status", help="查看当前状态和下一步")
    state.add_argument("--run", required=True)
    state.add_argument("--verbose", action="store_true")
    state.add_argument("--environment", action="store_true", help="显示浏览器验收环境预检")

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "start":
            if args.clone_from:
                if args.request or args.request_file or args.route_file:
                    raise ContractError("--clone-from 不能与 request 或 route 参数同时使用")
                result = clone_confirmed_run(Path(args.clone_from), Path(args.run))
            else:
                result = start_run(
                    Path(args.run),
                    read_text_arg(args.request_file, args.request, "request"),
                    read_json(Path(args.route_file)) if args.route_file else None,
                )
        elif args.command == "respond":
            result = respond(
                Path(args.run), read_json(Path(args.event_file)),
                read_json(Path(args.sources_file)) if args.sources_file else None,
            )
        elif args.command == "propose":
            result = propose(Path(args.run), read_json(Path(args.product_file)))
        elif args.command == "build":
            result = build(Path(args.run))
        elif args.command == "evaluate":
            if args.preflight and args.skip_browser:
                raise ContractError("--preflight 与 --skip-browser 不能同时使用")
            result = evaluate(Path(args.run), preflight=args.preflight, skip_browser=args.skip_browser)
        elif args.command == "cleanup":
            result = cleanup_transaction(Path(args.run))
        elif args.command == "status":
            result = status(Path(args.run), args.verbose)
            if args.environment:
                result["environment"] = browser_environment()
        else:
            raise ContractError("未知命令")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("status") not in {"candidate_failed", "evaluation_blocked", "error"} else 1
    except (ContractError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
