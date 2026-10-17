from __future__ import annotations

import argparse
import json
from pathlib import Path

from .acceptance import acceptance_template, build_acceptance
from .promotion import APPLY_APPROVAL_PHRASE, build_receipt, next_action_for, preflight_decision, promote_transaction


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="论文翻译 strict cutover")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--preflight", type=Path, required=True)
    packet = sub.add_parser("packet")
    packet.add_argument("--packet", type=Path, required=True)
    accept = sub.add_parser("accept")
    accept.add_argument("--packet", type=Path, required=True)
    accept.add_argument("--output", type=Path, required=True)
    accept.add_argument("--reviewer", required=True)
    accept.add_argument("--decision", choices=["accepted"], required=True)
    promote = sub.add_parser("promote")
    promote.add_argument("--case", action="append", required=True)
    promote.add_argument("--receipt", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--preflight", type=Path, required=True)
    run.add_argument("--receipt", type=Path, required=True)
    run.add_argument("--case", action="append", default=[])
    run.add_argument("--apply", action="store_true")
    run.add_argument("--approval-phrase")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "packet":
        print(json.dumps(acceptance_template(args.packet), ensure_ascii=False, indent=2))
        return 0
    if args.command == "accept":
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
        result = build_acceptance(packet, args.reviewer, args.decision)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0
    preflight = json.loads(args.preflight.read_text(encoding="utf-8")) if hasattr(args, "preflight") else {}
    status, blockers = preflight_decision(preflight)
    if args.command == "audit":
        print(json.dumps({"status": status, "blockers": blockers}, ensure_ascii=False, indent=2))
        return 0 if not blockers else 1
    if args.command == "promote":
        result = promote_transaction(args.case, args.receipt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "promoted" else 1
    apply_allowed = bool(args.apply and args.approval_phrase == APPLY_APPROVAL_PHRASE and status == "ready_for_cutover_apply" and not blockers)
    steps = []
    if apply_allowed:
        steps.append(promote_transaction(args.case, args.receipt))
    receipt = build_receipt(status=status, apply_requested=args.apply, apply_allowed=apply_allowed, blockers=blockers, steps=steps, preflight=preflight)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if (not args.apply or apply_allowed) and not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["APPLY_APPROVAL_PHRASE", "build_receipt", "next_action_for", "preflight_decision", "main"]
