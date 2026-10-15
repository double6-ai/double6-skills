"""autospec.py <template.pptx> <lang> <out_spec.json> [ratio]
Build a realistic fill spec from a template: every non-system text slot gets new text with the same
paragraph structure (levels kept), ~ratio x the sample length; mixed-run 'Label: value' keeps its label;
each slide gets new speaker notes; slide 2 (if any) gets a new transition; slide 1 is repeated at the end."""
import json, sys, re
sys.path.insert(0, "/workspace/wt-pm6-template/skills/double6-ppt-cli/scripts")
from double6_ppt_cli.pm6_template import analyze_pptx

ZH = "围绕年度目标推进重点项目落地并持续优化运营效率与客户体验同时加强风险管控和组织能力建设确保各项指标稳步提升"
EN = ("we continue to deliver the priority programs while improving operating efficiency and customer experience "
      "and we strengthen risk controls and team capabilities so that every key metric keeps improving steadily").split()

def gen(lang, n, seed):
    if lang == "zh":
        s = (ZH * 3)[seed % 17: seed % 17 + max(2, n)]
        return s
    words, out, i = [], 0, seed % 11
    while out < n:
        w = EN[i % len(EN)]; words.append(w); out += len(w) + 1; i += 1
    t = " ".join(words)
    return t[0].upper() + t[1:]

def main(tpl, lang, out, ratio=1.15):
    lib = analyze_pptx(tpl)
    spec = {"template": tpl.split("/")[-1], "title": "auto", "slides": []}
    k = 0
    for sl in lib["slides"]:
        names = [s.get("shape_name") for s in sl["slots"]]
        text = {}
        for s in sl["slots"]:
            if s.get("system_placeholder") or s.get("container") or not s.get("shape_name") or names.count(s["shape_name"]) != 1:
                continue
            if not s["text"].strip():
                continue
            paras = s["text"].split("\n")
            new = []
            for p in paras:
                k += 1
                m = re.match(r"^(.{1,12}?[:：]\s?)(.+)$", p)
                if m:
                    new.append(m.group(1) + ("14.1M USD" if lang == "en" else "14.1亿元"))
                elif p.strip():
                    new.append(gen(lang, int(len(p) * float(ratio)) + 1, k))
                else:
                    new.append("")
            lv = (s.get("fit_context") or {}).get("template_paragraph_levels")
            entry = "\n".join(new)
            text[s["shape_name"]] = {"text": entry, "levels": lv[: len(new)]} if lv and len(lv) >= len(new) and len(new) > 1 else entry
        slide = {"source": sl["slide_index"], "text": text,
                 "notes": ("新的讲者备注：第%d页" % sl["slide_index"]) if lang == "zh" else f"New speaker notes for page {sl['slide_index']}"}
        if sl["slide_index"] == 2:
            slide["transition"] = {"effect": "wipe", "duration": 0.6}
        spec["slides"].append(slide)
    if spec["slides"]:
        spec["slides"].append(dict(spec["slides"][0]))
    json.dump(spec, open(out, "w"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main(*sys.argv[1:])
