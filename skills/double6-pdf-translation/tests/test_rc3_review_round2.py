"""2.0.0-rc.3 评审修复第二轮：参考文献剔除改为按几何位置与逐条目校验（PR #16 复审）。

所有用例都调用真实的 render_residue_check，PDF 由 PyMuPDF 按显式坐标生成；
插入顺序即内容流顺序，可构造“像素相同、内容流顺序不同”的文件。
"""
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

from render_residue_check import check_render_residue  # noqa: E402

EN_PARA = ('Test-time training adapts the weights of the model during inference so that the network can store '
           'long context in fast weights. We evaluate the approach on language modeling and on novel view synthesis, '
           'and we find that larger chunks make the hardware much more efficient than the small online updates.')
ZH_PARA = '测试时训练在推理过程中更新模型权重，使网络能够把长上下文存入快速权重。我们在语言建模和新视角合成上评估该方法，发现更大的块能显著提高硬件效率。' * 2
CITED_EN = ('Prior work (Vaswani et al., 2017; Brown et al., 2020) has shown that the attention mechanism is the '
            'main cost when the context grows, and [12] argued in 2021 that this is why we need a different design '
            'for the long sequences that we study in this paper and in the experiments that follow.')
REFS = [
    '[1] Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, '
    'and Illia Polosukhin. Attention is all you need. In Advances in Neural Information Processing Systems, '
    'volume 30, pages 5998-6008, 2017.',
    '[2] Yu Sun, Xinhao Li, Karan Dalal, Jiarui Xu, Arjun Vikram, Genghan Zhang, et al. Learning to (learn at test '
    'time): RNNs with expressive hidden states. arXiv preprint arXiv:2407.04620, 2024.',
    '[3] Imanol Schlag, Kazuki Irie, and Jurgen Schmidhuber. Linear transformers are secretly fast weight '
    'programmers. In International Conference on Machine Learning, pages 9355-9366. PMLR, 2021.',
    '[4] Tri Dao. FlashAttention-2: Faster attention with better parallelism and work partitioning. '
    'arXiv preprint arXiv:2307.08691, 2023.',
    '[5] Albert Gu and Tri Dao. Mamba: Linear-time sequence modeling with selective state spaces. '
    'arXiv preprint arXiv:2312.00752, 2023.',
    '[6] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual learning for image recognition. '
    'In Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition, pages 770-778, 2016.',
]
AUTHOR_YEAR_REFS = [  # 无编号、悬挂缩进风格（ACL/natbib）
    'Jacob Devlin, Ming-Wei Chang, Kenton Lee, and Kristina Toutanova. 2019. BERT: Pre-training of deep '
    'bidirectional transformers for language understanding. In Proceedings of NAACL-HLT, pages 4171-4186.',
    'Kazuki Irie, Robert Csordas, and Jurgen Schmidhuber. 2022. The dual form of neural networks revisited. '
    'In Proceedings of the International Conference on Machine Learning, pages 9639-9659.',
    'Ofir Press, Noah A. Smith, and Mike Lewis. 2022. Train short, test long: Attention with linear biases '
    'enables input length extrapolation. In International Conference on Learning Representations.',
    'Peter J. Liu, Mohammad Saleh, Etienne Pot, Ben Goodrich, Ryan Sepassi, Lukasz Kaiser, and Noam Shazeer. '
    '2018. Generating Wikipedia by summarizing long sequences. In ICLR.',
]


class Page:
    """按坐标写入文本块；记录写入的块以便以不同顺序重放（内容流顺序）。"""

    def __init__(self, width=595, height=842):
        self.blocks, self.width, self.height = [], width, height

    def add(self, rect, text, font='helv', size=9):
        self.blocks.append((fitz.Rect(*rect), text, font, size))
        return self


def flow(page, x0, x1, y, items, size=9, gap=7):
    """自上而下排版 [(text, font)]，返回下一个 y。"""
    for text, font in items:
        probe = fitz.open().new_page(width=page.width, height=page.height)
        rest = probe.insert_textbox(fitz.Rect(x0, y, x1, page.height - 20), text, fontname=font, fontsize=size)
        used = page.height - 20 - y - rest
        page.add((x0, y, x1, y + used + 2), text, font, size)
        y += used + gap
    return y


def save(path, pages, order=None):
    doc = fitz.open()
    for index, spec in enumerate(pages):
        page = doc.new_page(width=spec.width, height=spec.height)
        blocks = spec.blocks if order is None or index not in order else [spec.blocks[i] for i in order[index]]
        for rect, text, font, size in blocks:
            assert page.insert_textbox(rect, text, fontname=font, fontsize=size) >= 0, text[:40]
    doc.save(path)
    doc.close()
    return path


def body_then_refs(body, refs, heading='References', body_font='helv', heading_font='hebo'):
    page = Page()
    y = flow(page, 50, 545, 50, [(text, body_font) for text in body])
    if heading:
        y = flow(page, 50, 545, y + 6, [(heading, heading_font)])
    flow(page, 50, 545, y, [(r, 'helv') for r in refs])
    return page


def pixels(path):
    with fitz.open(path) as doc:
        return [p.get_pixmap(dpi=40).samples for p in doc]


# ---------- 1 [P1]: exclusion must follow geometry, not content-stream order ----------

def test_round2_stream_order_swapped_pixel_identical_untranslated_body_fails(tmp_path):
    spec = body_then_refs([EN_PARA, EN_PARA, EN_PARA], REFS[:4])
    source = save(tmp_path / 'source.pdf', [spec])
    # 目标文件：参考文献块（位于页面下方）先写入内容流，正文后写；渲染像素完全相同。
    n = len(spec.blocks)
    target = save(tmp_path / 'target.pdf', [spec], order={0: list(range(3, n)) + [0, 1, 2]})
    assert pixels(source) == pixels(target)
    result = check_render_residue(source, target)
    assert result['severity'] == 'high' and result['quality_fail'], result['pages']
    assert result['pages'][0]['residue_ratio'] >= 0.9


def test_round2_two_column_stream_order_swapped_fails(tmp_path):
    page = Page()
    flow(page, 50, 290, 50, [(EN_PARA, 'helv')] * 4)
    y = flow(page, 305, 545, 50, [(EN_PARA, 'helv')])
    y = flow(page, 305, 545, y + 6, [('References', 'hebo')])
    flow(page, 305, 545, y, [(r, 'helv') for r in REFS[:3]])
    source = save(tmp_path / 'source.pdf', [page])
    n = len(page.blocks)
    target = save(tmp_path / 'target.pdf', [page], order={0: list(range(5, n)) + [4] + [0, 1, 2, 3]})
    assert pixels(source) == pixels(target)
    result = check_render_residue(source, target)
    assert result['severity'] == 'high', result['pages']


def test_round2_prose_after_heading_is_not_excluded(tmp_path):
    # 标题之后若是普通正文（不像参考文献条目），不得整段剔除。
    spec = body_then_refs([EN_PARA], [EN_PARA, EN_PARA, EN_PARA])
    source = save(tmp_path / 's.pdf', [spec])
    result = check_render_residue(source, save(tmp_path / 't.pdf', [spec]))
    assert result['severity'] == 'high' and result['pages'][0]['excluded_source_words'] <= 2


def test_round2_target_exclusion_capped_by_source(tmp_path):
    # 源文是正文；译文把同页内容换成英文“伪参考文献”。译文侧剔除不得超过源文同页剔除量。
    source_page = Page(); flow(source_page, 50, 545, 50, [(EN_PARA, 'helv')] * 4)
    target_page = Page(); flow(target_page, 50, 545, 50, [(r, 'helv') for r in REFS])
    result = check_render_residue(save(tmp_path / 's.pdf', [source_page]), save(tmp_path / 't.pdf', [target_page]))
    row = result['pages'][0]
    assert row['target_exclusion_capped_words'] > 100 and row['severity'] != 'ok', row


# ---------- 2 [P2]: lettered / named appendix after references ends the region ----------

@pytest.mark.parametrize('heading,target_heading', [
    ('A Proof of the Main Theorem', 'A Proof of the Main Theorem'),
    ('Appendix A', 'Appendix A'),
    ('A.1 Additional Proofs', 'A.1 Additional Proofs'),
    ('B Additional Results', 'B Additional Results'),
    ('Appendix', '附录'),
])
def test_round2_appendix_after_references_is_counted(tmp_path, heading, target_heading):
    def doc(body, appendix_heading, heading_font):
        first = Page(); flow(first, 50, 545, 50, [(body, 'china-s' if body is ZH_PARA else 'helv')] * 2)
        second = Page()
        y = flow(second, 50, 545, 50, [('References', 'hebo')])
        y = flow(second, 50, 545, y, [(r, 'helv') for r in REFS[:3]])
        y = flow(second, 50, 545, y + 8, [(appendix_heading, heading_font)])
        flow(second, 50, 545, y, [(EN_PARA, 'helv')] * 3)  # 附录正文未翻译
        return [first, second]
    source = save(tmp_path / 's.pdf', doc(EN_PARA, heading, 'hebo'))
    target = save(tmp_path / 't.pdf', doc(ZH_PARA, target_heading, 'china-s' if target_heading == '附录' else 'hebo'))
    result = check_render_residue(source, target)
    page2 = result['pages'][1]
    assert page2['evaluated'] and page2['severity'] == 'high', page2
    assert result['severity'] == 'high'


# ---------- 3: references without a heading ----------

@pytest.mark.parametrize('refs', [REFS, AUTHOR_YEAR_REFS], ids=['numbered', 'author_year'])
def test_round2_headingless_references_with_translated_body_pass(tmp_path, refs):
    def doc(body, font):  # 第三轮起无标题剔除不得超过文档英文词一半，正文取 5 段
        first = Page(); flow(first, 50, 545, 50, [(body, font)] * 5)
        second = Page(); flow(second, 50, 545, 50, [(r, 'helv') for r in refs])
        return [first, second]
    result = check_render_residue(save(tmp_path / 's.pdf', doc(EN_PARA, 'helv')),
                                  save(tmp_path / 't.pdf', doc(ZH_PARA, 'china-s')))
    assert result['severity'] == 'ok' and not result['quality_fail'], result['pages']
    assert result['pages'][1]['excluded_source_breakdown'].get('reference_entries_headingless', 0) > 80


def test_round2_headingless_refs_same_page_as_translated_body_pass(tmp_path):
    def doc(body, font):
        page = Page(); y = flow(page, 50, 545, 50, [(body, font)] * 4)  # 第三轮：正文须多于无标题条目
        flow(page, 50, 545, y + 10, [(r, 'helv') for r in REFS])
        return [page]
    result = check_render_residue(save(tmp_path / 's.pdf', doc(EN_PARA, 'helv')),
                                  save(tmp_path / 't.pdf', doc(ZH_PARA, 'china-s')))
    assert result['severity'] == 'ok', result['pages']


def test_round2_headingless_refs_page_with_carried_over_fragments_pass(tmp_path):
    # 真实论文的续页：页首是上一页条目的残段（无编号、无年份之外的特征），中间条目被拆成两段。
    carry = ('Xu, Zheng Yan, Iliyan Zarov, Yuchen Zhang, Angela Fan, Melanie Kambadur, Sharan Narang, '
             'Aurelien Rodriguez, Robert Stojnic, and Thomas Scialom. Llama 2: Open foundation models, 2023.')
    split_head = ('[35] Andrew Jaegle, Felix Gimeno, Andy Brock, Oriol Vinyals, Andrew Zisserman, and Joao Carreira. '
                  'Perceiver: General perception with iterative attention. In ICML, pages 4651-')
    entries = [(carry, 'helv')] + [(r, 'helv') for r in REFS[:4]] + [(split_head, 'helv'), ('4664. PMLR, 2021.', 'helv')] \
        + [(r, 'helv') for r in REFS[4:]]
    def doc(body, font):
        first = Page(); flow(first, 50, 545, 50, [(body, font)] * 5)
        second = Page(); flow(second, 50, 545, 50, entries, gap=9)
        return [first, second]
    result = check_render_residue(save(tmp_path / 's.pdf', doc(EN_PARA, 'helv')),
                                  save(tmp_path / 't.pdf', doc(ZH_PARA, 'china-s')))
    assert result['severity'] == 'ok', result['pages']
    # 第三轮起：页首无编号的续接残段与缺年份的半条目照常计数（宁可误报），其余条目剔除，该页不足评估词数。
    row = result['pages'][1]
    assert row['excluded_source_breakdown'].get('reference_entries_headingless', 0) >= 120, row
    assert not row['evaluated'], row


def test_round2_headingless_english_prose_at_page_bottom_still_counts(tmp_path):
    def doc(body, font):
        page = Page(); flow(page, 50, 545, 50, [(body, font)])
        flow(page, 50, 545, 600, [(EN_PARA, 'helv'), (CITED_EN, 'helv')])  # 页脚附近的英文正文（未翻译）
        return [page]
    result = check_render_residue(save(tmp_path / 's.pdf', doc(EN_PARA, 'helv')),
                                  save(tmp_path / 't.pdf', doc(ZH_PARA, 'china-s')))
    row = result['pages'][0]
    assert row['excluded_source_breakdown'].get('reference_entries_headingless', 0) == 0, row
    assert row['excluded_source_breakdown'].get('reference_section', 0) == 0
    assert row['target_latin_words'] >= 60 and row['severity'] in ('medium', 'high')


def test_round2_adversarial_untranslated_body_with_inline_citations_fails(tmp_path):
    # 未翻译正文夹带年份、作者-年份引用和以 [n] 开头的段落，仍须判失败。
    paragraphs = [CITED_EN, '[3] ' + EN_PARA + ' (Gu and Dao, 2023)', CITED_EN, '[7] ' + CITED_EN, EN_PARA + ' In 2024, et al.']
    def doc():
        page = Page(); flow(page, 50, 545, 50, [(p, 'helv') for p in paragraphs])
        return [page]
    result = check_render_residue(save(tmp_path / 's.pdf', doc()), save(tmp_path / 't.pdf', doc()))
    assert result['severity'] == 'high' and result['pages'][0]['residue_ratio'] >= 0.8, result['pages']


def test_round2_adversarial_references_heading_then_untranslated_body_fails(tmp_path):
    def doc():
        page = Page(); y = flow(page, 50, 545, 50, [('References', 'hebo')])
        flow(page, 50, 545, y, [(CITED_EN, 'helv'), (EN_PARA, 'helv'), (CITED_EN, 'helv'), (EN_PARA, 'helv')])
        return [page]
    result = check_render_residue(save(tmp_path / 's.pdf', doc()), save(tmp_path / 't.pdf', doc()))
    assert result['severity'] == 'high', result['pages']
