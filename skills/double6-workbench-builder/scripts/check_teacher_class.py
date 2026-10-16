#!/usr/bin/env python3
"""拦班主任首页：必须是今天的班务、考勤和待跟进，不能套小学三站或减脂三卡。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
CODE = re.compile(r"小[A-Z甲乙丙丁一二三四五六七八九十]")
FORBIDDEN = re.compile(
    r"学籍|实验小学|滨江|杭州|G20\d{6,}|(?<![家])学校|(?<![小])[张李王陈刘赵杨黄周吴徐孙胡朱高林何郭罗郑梁谢宋唐韩冯曹彭许邓沈蒋袁蔡吕方苏叶贺董魏邱][\u4e00-\u9fff]{1,2}"
)
EXCEPTION_STATUS = {"假", "迟"}
EXCEPTION_HINT = ("未交", "请假", "迟到", "假")


def _seed_text(row: dict) -> str:
    values = row.get("values") or {}
    return " ".join(str(values.get(key) or "") for key in ("title", "details", "status", "due", "date"))


def check_teacher_tonight_cast(pack: dict) -> list[str]:
    errors: list[str] = []
    seeds = pack.get("tonight_seeds") or []
    duties = [row for row in seeds if row.get("module_id") == "teaching-daily"]
    attendance = [row for row in seeds if row.get("module_id") == "teaching-attendance"]
    follows = [row for row in seeds if row.get("module_id") == "teaching-students"]
    if not duties or not attendance or not follows:
        errors.append("开箱必须同时有班务、考勤和跟进种子")
        return errors
    codes: list[str] = []
    for row in attendance:
        title = str((row.get("values") or {}).get("title") or "").strip()
        if not CODE.fullmatch(title):
            errors.append(f"考勤标题必须是合成代号，现在是「{title}」")
            continue
        codes.append(title)
        blob = _seed_text(row)
        if FORBIDDEN.search(blob):
            errors.append(f"考勤种子含真名、真校或学籍：{blob}")
    if len(set(codes)) < 2:
        errors.append("开箱考勤至少要有两个合成代号，才能看出共用而不是一条孤名")
    code_set = set(codes)
    follow_codes: set[str] = set()
    for row in follows:
        blob = _seed_text(row)
        if FORBIDDEN.search(blob):
            errors.append(f"跟进种子含真名、真校或学籍：{blob}")
        found = set(CODE.findall(blob))
        if not found:
            errors.append(f"跟进必须点名考勤里的合成代号：{blob}")
        extra = found - code_set
        if extra:
            errors.append(f"跟进出现了考勤里没有的代号：{'、'.join(sorted(extra))}")
        follow_codes |= found & code_set
    if codes and not follow_codes:
        errors.append("跟进和考勤没有共用任何一个合成代号")
    duty_codes: set[str] = set()
    for row in duties:
        blob = _seed_text(row)
        if FORBIDDEN.search(blob):
            errors.append(f"班务种子含真名、真校或学籍：{blob}")
        found = set(CODE.findall(blob))
        extra = found - code_set
        if extra:
            errors.append(f"班务出现了考勤里没有的代号：{'、'.join(sorted(extra))}")
        duty_codes |= found & code_set
    if codes and not duty_codes:
        errors.append("班务、考勤、跟进必须共用合成对象；至少一条班务要点名考勤代号")
    has_exception = False
    for row in attendance:
        status = str((row.get("values") or {}).get("status") or "")
        if status in EXCEPTION_STATUS:
            has_exception = True
    for row in follows:
        blob = _seed_text(row)
        if any(token in blob for token in EXCEPTION_HINT):
            has_exception = True
    if not has_exception:
        errors.append("开箱至少要有一条今晚例外：假、迟，或跟进里的未交/请假")
    return errors


def check_teacher_class_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "teacher-class-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "teacher-class-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    profiles = (SKILL / "references" / "scene-profiles.json").read_text(encoding="utf-8")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    errors: list[str] = []
    for marker, label in (
        ("data-teacher-class-board", "班主任专用今日板"),
        ("data-teacher-duty-form", "今日班务"),
        ("data-teacher-attendance-list", "今日考勤"),
        ("data-teacher-follow-list", "待跟进"),
        ("data-teacher-warmth", "每日一句"),
    ):
        if marker not in renderers and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderTeacherClass" not in helpers:
        errors.append("没有 renderTeacherClass")
    if "data-teacher-duty-toggle" not in listeners or "data-teacher-att-set" not in listeners:
        errors.append("没有勾班务或记考勤的监听")
    if "待人工发" not in listeners:
        errors.append("跟进必须能记下待人工发，且不能假装已发送")
    if "teacher-class-runtime-v1" not in packs:
        errors.append("pack 未绑定班主任 runtime")
    if "teacher_class_dashboard" not in packs:
        errors.append("pack 未使用班主任专用 dashboard")
    if "打开就处理班里这一件" in packs:
        errors.append("班主任务还在把今晚一件写成主规则")
    if "今晚处理这一件" in renderers[renderers.find("def _teacher_class") : renderers.find("def _teacher(")]:
        errors.append("班主任首页还在用今晚一件当主活动")
    if "页面不会发送" not in renderers and "页面没有发送" not in listeners:
        errors.append("首页必须写明家校消息不会发出去")
    if "teacher-class-warmth" not in library:
        errors.append("激励库缺少班主任暖话")
    if "勾第 1 组" in renderers[renderers.find("def _teacher_class") : renderers.find("def _teacher(")]:
        errors.append("班主任首页套了减脂或小学勾组")
    teacher_fn = renderers[renderers.find("def _teacher_class") : renderers.find("def _teacher(")]
    if "insert_today_workboard=False" not in teacher_fn:
        errors.append("班主任首页必须关掉通用今天待办板")
    builder = (SKILL / "scripts" / "double6_runtime" / "builder.py").read_text(encoding="utf-8")
    engine = (SKILL / "scripts" / "double6_runtime" / "atomic_engine.py").read_text(encoding="utf-8")
    if "data-ledger-csv-tool" not in builder or '"teaching-attendance"' not in engine:
        errors.append("考勤 CSV 预览必须在成人设置里，不得改成学校 OS")
    if "data-ledger-csv" in teacher_fn:
        errors.append("班主任首页不得放 CSV 导入")
    if "打开就能勾今晚组次" in profiles:
        errors.append("场景合同被健身旧目标污染")
    contract = SKILL / "references" / "teacher-tonight-content.md"
    if not contract.is_file():
        errors.append("缺少 references/teacher-tonight-content.md")
    else:
        text = contract.read_text(encoding="utf-8")
        if "跨班务、考勤、跟进共用" not in text or "禁止真名" not in text:
            errors.append("班主任开箱内容合同必须写明共用合成对象和禁真名")
    pack_rows = json.loads((SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")).get("packs") or []
    teacher_pack = next(
        (row for row in pack_rows if row.get("composition_id") == "composition.teaching.classroom-management-v1"),
        None,
    )
    if not teacher_pack:
        errors.append("找不到班主任 pack")
    else:
        errors.extend(check_teacher_tonight_cast(teacher_pack))
    return errors


def check_all() -> dict:
    errors = check_teacher_class_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查班主任今日板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"班主任今日板检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页是班务、考勤和待跟进，不是今晚一件。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
