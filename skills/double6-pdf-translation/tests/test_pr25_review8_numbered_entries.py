"""PR #25 第八轮：编号、年份、DOI 都不是作者或文献条目角色的证据（两个翻译方向）。

成对正负：
- 参考文献区内的编号普通叙述（含年份 + DOI）照常计数；真实编号条目（中文 GB/T 7714 / 英文）允许保留。
- 编号连续（[1][2][3]）不能替代作者证据；作者形似段之后若年份/DOI 写在叙述里，同样不算条目。
- 中文叙述按结构否决（逗号连接的多个分句、句中句号），不是禁词：换掉用词结论不变。
- 悬挂缩进条目、机构作者、全角标点条目仍是 strong；附录之后的编号叙述照常计数。
- 豁免只收窄：新过滤保留的行是修复前（bc9a1ec / 1a88972）保留行的超集。
使用真实 collect_issues / 过滤函数；不依赖模型、网络或字体下载。
"""
import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

from check_translation_gates import collect_issues  # noqa: E402
from check_translation_residue import (  # noqa: E402
    en_author_evidence,
    reference_entry_lines,
    strip_role_passthrough_lines,
    strip_zh_reference_lines,
    zh_narrative_veto,
    zh_reference_entry_class,
)
import render_residue_check as rrc  # noqa: E402

EN_LEAD = 'The experiment evaluates multilingual models.'
ZH_LEAD = '实验在多个数据集上评估了多语模型并报告了观察到的性能。'
# 用户冻结句（第八轮复核原文）
ZH_NUMBERED_BODY = ('[4] 实验在 2024 年完成，神经网络经过统一训练后，评估了多个基准数据集的模型性能、误差来源和研究局限性，'
                    '数据地址为 doi.org/10.1234/data。')
ZH_REF = '[1] 张三, 李四. 深度学习在医学图像中的应用[J]. 计算机学报, 2020, 43(2): 1-10.'
ZH_NUMBERED_REFS = [
    ZH_REF,
    '[2] 王五. 机器翻译评测方法研究[D]. 北京: 北京大学, 2019.',
    '[3] 赵六, 钱七, 等. 多语言预训练模型综述[J]. 软件学报, 2021. DOI: 10.13328/j.cnki.jos.006123.',
    '[4] 国家统计局. 中国统计年鉴2020[M]. 北京: 中国统计出版社, 2020.',
    '[5] 中华人民共和国教育部. 普通高等学校本科专业目录[EB/OL]. (2020-02-21)[2024-01-01]. http://www.moe.gov.cn/.',
    '[6] 张三，李四．深度学习在医学图像中的应用[J]．计算机学报，2020，43(2)：1-10．',
    '[7] 刘洋. 神经机器翻译前沿进展[C]//中国计算语言学大会论文集. 北京: 清华大学出版社, 2018: 1-12.',
    '8. 周明. 自然语言处理. 北京: 电子工业出版社, 2017.',
    '[9] Smith J, Lee K. 深度学习方法[J]. 计算机学报, 2020, 43(2): 1-10.',
    '[10] 陈静, 等. 跨语言信息检索研究[J]. 情报学报, 2015, 34(5): 456-465.',
    '[11] 李华. 大语言模型评测. 计算机研究与发展, 2023, 60(1): 1-20.',
    '[12] 王强. 坚持守正创新，推动高质量发展[J]. 求是, 2023(5): 1-3.',
]
ZH_NUMBERED_NARRATIVES = [
    ZH_NUMBERED_BODY,
    # 同一结构换用词（不是禁词）：仍是逗号连接的叙述分句
    '[4] 测试于 2023 年结束，模型参数经过统一调整以后，比较了若干公开语料库的翻译质量、错误类型和适用范围，代码位于 doi.org/10.5555/code。',
    '[2] 实验结果在 2024 年发布于 doi.org/10.1234/data 并公开代码',             # 编号 + 年份 + DOI，无作者段
    '[6] 2024 年的实验完成后数据公开于 doi.org/10.1234/data',                   # 编号 + 年份开头
    '[8] 实验在 2024 年完成后在 http://example.org/data 公开数据',              # URL 不是出处
    '[5] 结果表明. 模型在 2024 年的 ImageNet 测试中表现良好，数据见 doi.org/10.1/x。',  # 作者形似段，年份/DOI 在叙述里
    '[7] 实验数据. 训练于 2023 年完成并在多个基准上评估[J]，误差来源与局限性见附录。',     # 方括号后不是著录分隔符
]
EN_NUMBERED_BODY = ('[4] Experiments completed in 2024 after unified training, covering multiple benchmark datasets '
                    'for model performance and error sources, data at doi.org/10.1234/data.')
EN_NUMBERED_REFS = [
    '[1] Ashish Vaswani, Noam Shazeer, Niki Parmar, et al. Attention is all you need. Advances in neural '
    'information processing systems, 30, 2017.',
    '[2] Smith, J. and Lee, K. (2020). Deep learning for medical imaging. Journal of Computing, 43(2): 1-10. '
    'doi:10.1000/jc.2020.43',
    '[3] OpenAI. GPT-4 technical report. arXiv preprint arXiv:2303.08774, 2023. doi:10.48550/arXiv.2303.08774',
]


def zh_long(issues):
    return [i for i in issues if i.title == '疑似大段中文未翻译' and i.severity == 'medium']


def en_long(issues):
    return [i for i in issues if i.title == '疑似大段英文未翻译']


def qa(text, target):
    return collect_issues(text, text, [], manifest={'target_language': target, 'pages': []})  # 源目标相同


# ---------- 中译英（目标 en）：编号叙述 vs 真实编号条目 ----------

def test_numbered_zh_narrative_after_real_reference_is_counted():
    text = EN_LEAD + '\nReferences\n' + ZH_REF + '\n' + ZH_NUMBERED_BODY
    assert zh_reference_entry_class(ZH_NUMBERED_BODY) == 'break'
    assert ZH_NUMBERED_BODY in strip_zh_reference_lines(text)
    assert zh_long(qa(text, 'en'))


def test_real_numbered_zh_reference_list_remains_permitted():
    text = EN_LEAD + '\nReferences\n' + '\n'.join(ZH_NUMBERED_REFS)
    assert strip_zh_reference_lines(text).splitlines() == [EN_LEAD, 'References']
    assert not zh_long(qa(text, 'en'))


@pytest.mark.parametrize('line', ZH_NUMBERED_NARRATIVES)
def test_number_year_doi_are_not_author_or_entry_evidence(line):
    assert zh_reference_entry_class(line) == 'break'
    text = EN_LEAD + '\n参考文献\n' + ZH_REF + '\n' + line
    assert line in strip_zh_reference_lines(text)


@pytest.mark.parametrize('line', ZH_NUMBERED_REFS)
def test_real_numbered_zh_entries_with_author_title_source_are_strong(line):
    assert zh_reference_entry_class(line) == 'strong'


def test_consecutive_numbering_does_not_replace_author_evidence():
    narrative = ZH_NUMBERED_BODY.replace('[4]', '[2]', 1)
    text = EN_LEAD + '\nReferences\n' + ZH_NUMBERED_REFS[0] + '\n' + narrative + '\n' + ZH_NUMBERED_REFS[2]
    filtered = strip_zh_reference_lines(text)
    assert narrative in filtered
    assert ZH_NUMBERED_REFS[0] not in filtered and ZH_NUMBERED_REFS[2] not in filtered
    assert zh_long(qa(text, 'en'))


def test_chinese_narrative_veto_is_structural_not_a_word_list():
    assert zh_narrative_veto(ZH_NUMBERED_BODY) == ['clause_chain']
    assert zh_narrative_veto(ZH_NUMBERED_NARRATIVES[1]) == ['clause_chain']  # 无“实验”一词
    assert zh_narrative_veto('前一句已经结束。后面仍有正文。') == ['inner_full_stop']
    for ref in ZH_NUMBERED_REFS:
        assert zh_narrative_veto(ref) == [], ref


def test_hanging_indent_numbered_entry_still_one_strong_entry():
    first = '[1] 张三, 李四, 王五, 赵六. 深度学习在医学图像分割与配准中的'
    text = EN_LEAD + '\n参考文献\n' + first + '\n    应用研究[J]. 计算机学报, 2020, 43(2): 1-10.\n' + ZH_NUMBERED_BODY
    assert {2, 3} <= reference_entry_lines(text)
    assert 4 not in reference_entry_lines(text)
    assert strip_zh_reference_lines(text).splitlines() == [EN_LEAD, '参考文献', first, ZH_NUMBERED_BODY]


@pytest.mark.parametrize('boundary', ['附录 A', 'Appendix A', '# 5 Discussion'])
def test_numbered_narrative_after_appendix_is_counted_and_entries_before_it_allowed(boundary):
    text = EN_LEAD + '\nReferences\n' + ZH_REF + '\n' + boundary + '\n' + ZH_NUMBERED_REFS[1] + '\n' + ZH_NUMBERED_BODY
    filtered = strip_zh_reference_lines(text)
    assert ZH_REF not in filtered
    assert ZH_NUMBERED_REFS[1] in filtered and ZH_NUMBERED_BODY in filtered
    assert zh_long(qa(text, 'en'))


# ---------- 英译中（目标 zh）：同一合同 ----------

def _en_class(text):
    return rrc.headingless_entry_class({'text': text, 'rows': [{'text': text, 'col': 'text'}], 'x0': 0.0, 'page': 0},
                                       region=True)


def test_numbered_en_narrative_without_author_is_counted_for_zh_target():
    # 渲染检查的通用分类会因“编号 + 年份 + DOI”判 strong；文字 QA 另要求作者角色证据
    assert _en_class(EN_NUMBERED_BODY) == 'strong' and not en_author_evidence(EN_NUMBERED_BODY)
    text = ZH_LEAD + '\n参考文献\n' + EN_NUMBERED_REFS[0] + '\n' + EN_NUMBERED_BODY
    assert EN_NUMBERED_BODY in strip_role_passthrough_lines(text)
    assert en_long(qa(text, 'zh'))


def test_real_numbered_en_entries_remain_permitted_for_zh_target():
    assert all(en_author_evidence(ref) for ref in EN_NUMBERED_REFS)
    text = ZH_LEAD + '\n参考文献\n' + '\n'.join(EN_NUMBERED_REFS)
    assert strip_role_passthrough_lines(text).splitlines() == [ZH_LEAD, '参考文献']
    assert not en_long(qa(text, 'zh'))


def test_en_consecutive_numbering_does_not_replace_author_evidence():
    narrative = EN_NUMBERED_BODY.replace('[4]', '[2]', 1)
    text = ZH_LEAD + '\nReferences\n' + EN_NUMBERED_REFS[0] + '\n' + narrative + '\n' + EN_NUMBERED_REFS[2]
    filtered = strip_role_passthrough_lines(text)
    assert narrative in filtered and EN_NUMBERED_REFS[0] not in filtered and EN_NUMBERED_REFS[2] not in filtered


# ---------- 豁免只收窄 ----------

def _review7_module():
    spec = importlib.util.spec_from_file_location('_review7', Path(__file__).with_name('test_pr25_review7_reference_entries.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SAMPLES = [
    EN_LEAD + '\nReferences\n' + ZH_REF + '\n' + ZH_NUMBERED_BODY,
    EN_LEAD + '\n参考文献\n' + '\n'.join(ZH_NUMBERED_REFS + ZH_NUMBERED_NARRATIVES),
    ZH_LEAD + '\nReferences\n' + '\n'.join(EN_NUMBERED_REFS) + '\n' + EN_NUMBERED_BODY,
]


@pytest.mark.parametrize('sample', SAMPLES)
def test_filters_keep_a_superset_of_bc9a1ec_kept_lines(sample):
    old = _review7_module()  # 第七轮测试中 bc9a1ec 两个过滤函数的逐字副本
    for new, previous in ((strip_zh_reference_lines, old._old_strip_zh), (strip_role_passthrough_lines, old._old_strip_en)):
        kept_new, kept_old = Counter(new(sample).splitlines()), Counter(previous(sample).splitlines())
        assert not (kept_old - kept_new), kept_old - kept_new
