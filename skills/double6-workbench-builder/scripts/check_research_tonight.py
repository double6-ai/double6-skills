#!/usr/bin/env python3
"""拦研究首页：必须是写下今晚这条带出处的结论，不能是空资料库或无来源已证实。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_research_tonight_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "research-evidence-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "research-evidence-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    profiles = (SKILL / "references" / "scene-profiles.json").read_text(encoding="utf-8")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    errors: list[str] = []
    start = renderers.find("def _research_tonight")
    end = renderers.find("RENDERERS =")
    tonight = renderers[start:end] if start >= 0 and end > start else ""
    if "def _research_tonight" not in renderers:
        errors.append("缺少研究今晚专用 renderer")
    for marker, label in (
        ("data-research-tonight-board", "研究今晚专用板"),
        ("data-research-claim-form", "今晚这条结论"),
        ("data-research-evidence-form", "出处"),
        ("data-research-question-form", "今晚这个问题"),
        ("data-research-warmth", "每日一句"),
    ):
        if marker not in renderers and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderResearchTonight" not in helpers:
        errors.append("没有 renderResearchTonight")
    if "data-research-claim-form" not in listeners:
        errors.append("没有留下今晚这条结论的监听")
    if "标缺口" not in listeners and "标缺口" not in tonight:
        errors.append("没有出处时必须能标缺口")
    if "不能空着写成已证实" not in listeners and "不能写成已证实" not in listeners:
        errors.append("无出处结论必须被拦住")
    if "research-evidence-runtime-v1" not in packs:
        errors.append("pack 未绑定研究今晚 runtime")
    if "research_tonight_dashboard" not in packs:
        errors.append("pack 未使用研究今晚专用 dashboard")
    if "composition-object-pipeline-v1" in tonight:
        errors.append("研究今晚不得再用通用对象链当主活动")
    if "打开就做今晚这一件" in tonight:
        errors.append("研究今晚首页还在用通用空板文案")
    denied = tonight.replace("也不要写已发表", "").replace("不要写已发表", "")
    if "已发表" in denied or "已同步知识库" in tonight:
        errors.append("研究今晚不得声称已发表或已同步知识库")
    if "不要写已发表" not in tonight and "也不要写已发表" not in tonight:
        errors.append("首页必须写明不要写成已发表")
    if "insert_today_workboard=False" not in tonight:
        errors.append("研究今晚首页必须关掉通用今天待办板")
    if "research-evidence-warmth" not in library:
        errors.append("激励库缺少研究今晚暖话")
    if "打开就写下今晚这条带出处的结论" not in packs:
        errors.append("pack 主规则必须是今晚带出处的结论")
    profile_slice = profiles[profiles.find("scene.research-knowledge.evidence-to-report") :]
    if "executable_ready" not in profile_slice[:800]:
        errors.append("场景成熟度未升到 executable_ready")
    return errors


def check_all() -> dict:
    errors = check_research_tonight_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查研究今晚结论板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"研究今晚检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页是今晚这条带出处的结论，缺出处就标缺口。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
