"""PR #25 第七轮：参考文献区只豁免有条目结构证据的文献条目（两个翻译方向）。

年份/DOI/出处标记本身不足以证明一行是文献条目。成对正负：
- 参考文献标题之后的普通正文（含年份/DOI）照常计数；真实文献条目（中文 GB/T 7714 / 英文）允许保留。
- 区域在附录类标题或 Markdown 标题处结束：之后的正文/附录照常计数（即使形似条目）。
- 未知块（只有编号、无年份与出处）不按文献豁免。
- 豁免只会比修复前更窄：剔除的行同时满足历史逐行标记与条目结构证据。
使用真实 collect_issues / 过滤函数；不依赖模型、网络或字体下载。
"""
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

from check_translation_gates import collect_issues  # noqa: E402
from check_translation_residue import (  # noqa: E402
    reference_entry_lines,
    strip_role_passthrough_lines,
    strip_zh_reference_lines,
    zh_reference_entry_class,
)

EN_LEAD = 'The experiment evaluates multilingual models across multiple datasets and reports observed performance.'
ZH_LEAD = '实验在多个数据集上评估了多语模型并报告了观察到的性能。'
# 用户冻结句（第七轮复核原文）
ZH_BODY = '我们在 2024 年训练了神经网络，评估了多语结果，并报告多个基准数据集的模型性能、误差来源和研究局限性。'
ZH_BODY_DOI = '该方法随后在多个基准数据集上复现了上述结论，相关数据见 doi.org/10.1234/abcd.2024 并讨论了研究局限性。'
EN_BODY = ('We trained the neural networks in (2024) and evaluated multilingual results, reporting model performance '
           'across several benchmark datasets and their error sources.')
ZH_REFS = [
    '[1] 张三, 李四. 深度学习在医学图像中的应用[J]. 计算机学报, 2020, 43(2): 1-10.',
    '[2] 王五. 机器翻译评测方法研究[D]. 北京: 北京大学, 2019.',
    '[3] 赵六, 钱七, 等. 多语言预训练模型综述[J]. 软件学报, 2021. DOI: 10.13328/j.cnki.jos.006123.',
]
EN_REFS = [
    '[1] Ashish Vaswani, Noam Shazeer, Niki Parmar, et al. Attention is all you need. Advances in neural '
    'information processing systems, 30, 2017.',
    '[2] Smith, J. and Lee, K. (2020). Deep learning for medical imaging. Journal of Computing, 43(2): 1-10. '
    'doi:10.1000/jc.2020.43',
]


def titles(issues):
    return [i.title for i in issues]


def zh_long(issues):
    return [i for i in issues if i.title == '疑似大段中文未翻译' and i.severity == 'medium']


def en_long(issues):
    return [i for i in issues if i.title == '疑似大段英文未翻译']


def qa(text, target, source=None):
    return collect_issues(text if source is None else source, text, [], manifest={'target_language': target, 'pages': []})


# ---------- 中译英（目标 en）：正文 vs 真实条目 ----------

def test_zh_narrative_with_year_inside_reference_region_is_counted():
    text = EN_LEAD + '\nReferences\n' + ZH_REFS[0] + '\n' + '\n'.join([ZH_BODY] * 3)
    issues = qa(text, 'en', source=text)  # 源目标完全相同：隔离数字/事实类发现
    assert zh_long(issues), titles(issues)
    assert strip_zh_reference_lines(text).count('训练了神经网络') == 3
    assert ZH_REFS[0] not in strip_zh_reference_lines(text)


def test_zh_narrative_with_doi_inside_reference_region_is_counted():
    text = EN_LEAD + '\n参考文献\n' + ZH_REFS[0] + '\n' + ZH_BODY_DOI
    assert zh_long(qa(text, 'en', source=text))
    assert ZH_BODY_DOI in strip_zh_reference_lines(text)


def test_genuine_chinese_reference_entries_remain_permitted():
    text = EN_LEAD + '\n参考文献\n' + '\n'.join(ZH_REFS)
    issues = qa(text, 'en', source=text)
    assert not zh_long(issues), titles(issues)
    assert strip_zh_reference_lines(text).splitlines() == [EN_LEAD, '参考文献']


def test_wrapped_chinese_reference_entry_with_hanging_indent_is_one_entry():
    first = '[1] 张三, 李四, 王五, 赵六. 深度学习在医学图像分割与配准中的'
    text = EN_LEAD + '\n参考文献\n' + first + '\n    应用研究[J]. 计算机学报, 2020, 43(2): 1-10.\n'
    # 首行与悬挂缩进续行是同一条目块（strong）
    assert {2, 3} <= reference_entry_lines(text)
    # 续行带文献标记 → 剔除；首行没有任何文献标记 → 与修复前相同照常计数（豁免只收窄）
    assert strip_zh_reference_lines(text).splitlines() == [EN_LEAD, '参考文献', first]


@pytest.mark.parametrize('line', [
    ZH_BODY,
    ZH_BODY_DOI,
    '在 2024 年，该方法被广泛用于医学图像 doi.org/10.1/x，并取得了较好的效果。',
    '[4] 我们在 2023 年重新标注了数据集[J]，并报告了误差来源与局限性。',  # 编号 + 类型标识，但第一人称叙述
])
def test_year_doi_or_type_marker_alone_is_not_entry_evidence(line):
    assert zh_reference_entry_class(line) == 'break'


@pytest.mark.parametrize('line', ZH_REFS)
def test_gbt_entry_structure_is_strong(line):
    assert zh_reference_entry_class(line) == 'strong'


def test_unknown_numbered_block_without_year_or_source_is_not_exempted():
    unknown = '[5] 以上各项实验结果均在统一的硬件环境下重复测量得到并取平均值作为最终的报告结果'
    text = EN_LEAD + '\n参考文献\n' + ZH_REFS[0] + '\n' + unknown
    assert unknown in strip_zh_reference_lines(text)
    assert zh_long(qa(text, 'en', source=text))


def test_weak_entry_needs_numbered_sequence_evidence():
    weak = '[2] 王五. 机器翻译评测方法研究. 北京大学, 2019.'  # 有编号作者开头与年份，无出处标识 → weak
    assert zh_reference_entry_class(weak) == 'weak'
    seq = EN_LEAD + '\n参考文献\n' + ZH_REFS[0] + '\n' + weak + '\n' + ZH_REFS[2]
    assert weak not in strip_zh_reference_lines(seq)  # 与 [1]/[3] 编号连续 → 剔除
    alone = EN_LEAD + '\n参考文献\n' + weak
    assert weak in strip_zh_reference_lines(alone)  # 无正面证据 → 计数


# ---------- 章节恢复：参考文献之后的附录/正文 ----------

@pytest.mark.parametrize('boundary', ['附录 A', '## 附录 A 实验细节', 'Appendix A', '# 5 Discussion', 'Supplementary Materials'])
def test_appendix_after_reference_list_is_counted_even_if_entry_like(boundary):
    entry_like = '[9] 孙八. 附录中引用的未译正文[J]. 学报, 2022.'
    before = EN_LEAD + '\nReferences\n' + ZH_REFS[0] + '\n' + entry_like
    after = EN_LEAD + '\nReferences\n' + ZH_REFS[0] + '\n' + boundary + '\n' + entry_like + '\n' + ZH_BODY
    assert entry_like not in strip_zh_reference_lines(before)  # 区内真实条目：允许
    filtered = strip_zh_reference_lines(after)
    assert ZH_REFS[0] not in filtered  # 边界之前的条目仍豁免
    assert entry_like in filtered and ZH_BODY in filtered  # 边界之后：照常计数
    assert zh_long(qa(after, 'en', source=after))


def test_second_reference_heading_reopens_region():
    text = (EN_LEAD + '\nReferences\n' + ZH_REFS[0] + '\nAppendix A\n' + ZH_BODY + '\n参考文献\n' + ZH_REFS[1])
    filtered = strip_zh_reference_lines(text)
    assert ZH_BODY in filtered and ZH_REFS[0] not in filtered and ZH_REFS[1] not in filtered


# ---------- 英译中（目标 zh）：同一合同 ----------

def test_en_narrative_with_year_inside_reference_region_is_counted():
    text = ZH_LEAD + '\n参考文献\n' + EN_REFS[1] + '\n' + EN_BODY + '\n' + EN_BODY
    assert EN_BODY in strip_role_passthrough_lines(text)
    issues = qa(text, 'zh', source=text)
    assert en_long(issues), titles(issues)


def test_genuine_english_reference_entries_remain_permitted_for_zh_target():
    text = ZH_LEAD + '\n参考文献\n' + '\n'.join(EN_REFS)
    assert strip_role_passthrough_lines(text).splitlines() == [ZH_LEAD, '参考文献']
    assert not en_long(qa(text, 'zh', source=text))


def test_en_appendix_after_reference_list_is_counted():
    text = ZH_LEAD + '\nReferences\n' + EN_REFS[1] + '\nAppendix A\n' + EN_REFS[1]
    filtered = strip_role_passthrough_lines(text).splitlines()
    assert filtered == [ZH_LEAD, 'References', 'Appendix A', EN_REFS[1]]


# ---------- 豁免只收窄 ----------

@pytest.mark.parametrize('strip, lead, refs, body', [
    (strip_zh_reference_lines, EN_LEAD, ZH_REFS, ZH_BODY),
    (strip_role_passthrough_lines, ZH_LEAD, EN_REFS, EN_BODY),
])
def test_exemption_never_wider_than_line_markers(strip, lead, refs, body):
    # 条目块里不带任何文献标记的行（例如续行只有题名）不剔除
    text = lead + '\nReferences\n' + refs[0] + '\n' + body
    kept = strip(text).splitlines()
    assert body in kept
    assert all(line in text.splitlines() for line in kept)


# 修复前（bc9a1ec）两个过滤函数的逐字副本：新实现保留的行必须是旧实现保留行的超集（豁免只收窄）。
def _old_strip_zh(text):
    import re
    marker = re.compile(r"\[(?:[JMCDRSNPZA]|EB|OL|J/OL|EB/OL|DB)\]|\(\d{4}\)|\b(?:19|20)\d{2}\b|doi\.org/|\b10\.\d{4,9}/|et al\.|等\.", re.I)
    kept, in_references = [], False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line.lower().strip("#:： ") in {"references", "参考文献", "bibliography"}:
            in_references = True
            kept.append(raw_line)
            continue
        if in_references and marker.search(line):
            continue
        kept.append(raw_line)
    return "\n".join(kept)


def _old_strip_en(text):
    import re
    kept, in_references = [], False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line.lower().strip(":：") in {"references", "参考文献"}:
            in_references = True
            kept.append(raw_line)
            continue
        if in_references and re.search(r"\(\d{4}\)|\bdoi\.org/|\b10\.\d{4,9}/|et al\.", line, re.I):
            continue
        if re.match(r"^(?:Example\s+\d+|ST|TT|HT|NMT-GT|LLM-[A-Za-z0-9-]+)\s*[:：]", line, re.I):
            continue
        kept.append(raw_line)
    return "\n".join(kept)


SUPERSET_SAMPLES = [
    EN_LEAD + '\nReferences\n' + ZH_REFS[0] + '\n' + '\n'.join([ZH_BODY] * 3),
    EN_LEAD + '\n参考文献\n' + '\n'.join(ZH_REFS) + '\n附录 A\n' + ZH_BODY,
    ZH_LEAD + '\n参考文献\n' + '\n'.join(EN_REFS) + '\n' + EN_BODY,
    ZH_LEAD + '\nBibliography\n' + EN_REFS[1] + '\n# References\n' + EN_REFS[1] + '\n7 References\n' + EN_BODY,
    ('参考文献\n[1] Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N Gomez, Łukasz\n'
     '    Kaiser, and Illia Polosukhin. Attention is all you need. Advances in neural information processing systems,\n'
     '    30, 2017.\n\n 13\n [2] Yu Sun, Xinhao Li, Karan Dalal, et al. Learning to (learn at test time): Rnns with expressive\n'
     '     hidden states. arXiv preprint arXiv:2407.04620, 2024.\n'),
]


@pytest.mark.parametrize('sample', SUPERSET_SAMPLES)
@pytest.mark.parametrize('new, old', [(strip_zh_reference_lines, _old_strip_zh), (strip_role_passthrough_lines, _old_strip_en)])
def test_new_filters_keep_a_superset_of_previously_kept_lines(sample, new, old):
    from collections import Counter
    kept_new, kept_old = Counter(new(sample).splitlines()), Counter(old(sample).splitlines())
    assert not (kept_old - kept_new), kept_old - kept_new
