"""PR #25 公式结构 / 可读版保真回归测试。

(A) BabelDOC 合成空格让上/下标退化为基线样式片段（doc 13 V_n^max）：真实段落夹具 + 相邻边界；
    普通中英文正文不因新规则被归为公式。
(B) formula_structure_check：上/下标层级压平、方向翻转、偏移不足必须失败关闭（两个方向通用）；
    整体平移/缩放、重新分页、偏移在容差内必须通过；正文脚注角标不在范围内；闭括号与矩阵相邻行边界。
(C) 可读版（final_readable.pdf）：数学页整页矢量复制主版式页（逐字形保留），纯文字页重排；
    不能保真时写出前拒绝并给出稳定 reason_code，不留下损坏文件；标题取原文件名。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'vendor/babeldoc')]
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend import styles_and_formulas as saf  # noqa: E402

import formula_structure_check as fsc  # noqa: E402
import pdf_translation_artifacts as artifacts  # noqa: E402
import qa_pipeline as qa  # noqa: E402
import render_readable_pdf as rr  # noqa: E402

FIXTURE = ROOT / 'tests/fixtures/formula_scripts/arxiv2610.21653-p8-vnmax.json'


# ----------------------------------------------------------------------------- (A) IL 分类
class _FontMapper:
    def __init__(self, table=None):
        self.table = table or {}

    def has_char(self, char):
        return self.table.get(char, True)


def _stage(table=None):
    stage = saf.StylesAndFormulas.__new__(saf.StylesAndFormulas)
    stage.translation_config = NS(formular_font_pattern=None, formular_char_pattern=None,
                                  skip_formula_offset_calculation=False, ocr_workaround=False,
                                  remove_non_formula_lines=False)
    stage.font_mapper = _FontMapper(table)
    return stage


def _box(v):
    return il.Box(x=v[0], y=v[1], x2=v[2], y2=v[3])


def _fixture_page():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    compositions = []
    for row_line in data['lines']:
        chars = [il.PdfCharacter(pdf_style=il.PdfStyle(font_id=r[9], font_size=r[10], graphic_state=il.GraphicState()),
                                 box=_box(r[1:5]), visual_bbox=il.VisualBbox(box=_box(r[5:9])), vertical=r[11], scale=1.0,
                                 pdf_character_id=r[13], char_unicode=r[0], formula_layout_id=r[12]) for r in row_line]
        compositions.append(_line(chars))
    paragraph = il.PdfParagraph(box=_box(data['box']), pdf_paragraph_composition=compositions, xobj_id=data['xobj_id'],
                                debug_id=data['debug_id'], layout_label=data['layout_label'], layout_id=data['layout_id'])
    page = il.Page(page_number=0, pdf_font=[il.PdfFont(font_id=f['font_id'], name=f['name']) for f in data['fonts']],
                   pdf_paragraph=[paragraph])
    return data, page


def _line(chars):
    return il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=chars, box=il.Box(
        x=min(c.box.x for c in chars), y=min(c.box.y for c in chars),
        x2=max(c.box.x2 for c in chars), y2=max(c.box.y2 for c in chars))))


def _parts(page):
    rows = []
    for comp in page.pdf_paragraph[0].pdf_paragraph_composition:
        if comp.pdf_formula is not None:
            rows.append(('formula', ''.join(c.char_unicode or '' for c in comp.pdf_formula.pdf_character),
                         bool(comp.pdf_formula.is_corner_mark)))
        elif comp.pdf_same_style_characters is not None:
            rows.append(('style', ''.join(c.char_unicode or '' for c in comp.pdf_same_style_characters.pdf_character), False))
        elif comp.pdf_line is not None:
            rows.append(('line', ''.join(c.char_unicode or '' for c in comp.pdf_line.pdf_character), False))
    return rows


def test_fixture_has_synthetic_space_between_base_and_script():
    data, _ = _fixture_page()
    line = next(l for l in data['lines'] if 'namely' in ''.join(r[0] or '' for r in l))
    k = next(i for i, r in enumerate(line) if r[0] == 'V' and line[i + 2][0] == 'm')
    assert line[k + 1][0] == ' ' and line[k + 1][13] is None      # 合成空格：无源字形编号
    assert line[k][13] is not None and line[k + 2][13] is not None
    assert line[k + 2][10] < 0.79 * line[k][10]


def test_vnmax_scripts_stay_inside_the_formula():
    data, page = _fixture_page()
    _stage(data['has_char']).process_page(page)
    parts = _parts(page)
    assert not [p for p in parts if p[0] != 'formula' and 'max' in p[1]], parts
    holder = next(p for p in parts if p[0] == 'formula' and p[1].replace(' ', '').endswith('Vmaxn'))
    assert holder[2] is True
    # 段内普通英文正文仍是可翻译文字，不被并入公式
    text = ' '.join(p[1] for p in parts if p[0] != 'formula')
    for word in ('threshold', 'pruned', 'branches'):
        assert word in text


def test_without_the_fix_max_becomes_a_baseline_style_run(monkeypatch):
    """根因复现：去掉合成空格规则（即 e3ab2be 行为）时 max 成为独立样式片段。"""
    monkeypatch.setattr(saf, '_is_script_after_synthetic_space', lambda *a, **k: False)
    data, page = _fixture_page()
    _stage(data['has_char']).process_page(page)
    assert ('style', 'max', False) in _parts(page)


FONTS = [('F0', 'NimbusRomNo9L-Regu'), ('F1', 'CMMI10'), ('F2', 'CMR7'), ('F3', 'SourceHanSerifCN-Regular')]


def _c(u, x, y, size, font, cid):
    box = il.Box(x=x, y=y, x2=x + 0.55 * size, y2=y + size)
    return il.PdfCharacter(pdf_style=il.PdfStyle(font_id=font, font_size=size, graphic_state=il.GraphicState()), box=box,
                           visual_bbox=il.VisualBbox(box=il.Box(x=box.x, y=box.y, x2=box.x2, y2=box.y2)), vertical=False,
                           scale=1.0, pdf_character_id=cid, char_unicode=u)


def _page_of(chars):
    para = il.PdfParagraph(box=il.Box(0, 0, 400, 200), pdf_paragraph_composition=[_line(chars)], debug_id='t',
                           layout_label='plain text')
    return il.Page(page_number=0, pdf_font=[il.PdfFont(font_id=i, name=n) for i, n in FONTS], pdf_paragraph=[para])


def _word(text, x, y, size, font, start=100):
    out = []
    for i, u in enumerate(text):
        out.append(_c(u, x, y, size, font, None if u == ' ' else start + i))
        x += 0.55 * size
    return out, x


def _script_case(shift, *, base_font='F1', script_font='F2', script_size=7.0, gap_id=None, script='ab'):
    """shift：脚本基线相对基字基线的抬高量（pt）；字形框底 = 基线 − 0.22×字号（下伸），与 IL 一致。"""
    head, x = _word('see ', 10, 97.8, 10, 'F0')
    base = _c('x', x, 97.8, 10, base_font, 50)
    gap = _c(' ', x + 5.5, 97.8, 10, base_font, gap_id)
    tail, x2 = _word(script, x + 7, 100 + shift - 0.22 * script_size, script_size, script_font, start=60)
    rest, _ = _word(' then more words', x2 + 1, 97.8, 10, 'F0', start=200)
    page = _page_of(head + [base, gap] + tail + rest)
    _stage().process_page(page)
    return _parts(page)


@pytest.mark.parametrize('shift', [3.72, -2.4])   # doc 13 原文的 max 抬高量 / n 降低量
def test_raised_or_lowered_script_after_synthetic_space_is_a_corner_mark(shift):
    parts = _script_case(shift)
    holder = next(p for p in parts if 'ab' in p[1])
    assert holder[0] == 'formula' and holder[2] is True and 'x' in holder[1]


def test_same_baseline_smaller_text_after_synthetic_space_is_not_a_script():
    parts = _script_case(0.0)          # 同基线的小字号文字（如小型大写）：框中心只差下伸量
    holder = next(p for p in parts if 'ab' in p[1])
    assert not (holder[0] == 'formula' and holder[2])


def test_source_space_glyph_keeps_original_rule():
    """源文本身的空格字形（有 pdf_character_id）不属于合成空格，沿用原规则（不判角标）。"""
    parts = _script_case(3.7, gap_id=77)
    holder = next(p for p in parts if 'ab' in p[1])
    assert not holder[2]


def test_prose_base_with_raised_small_text_is_not_pulled_into_a_formula():
    """基字是正文字体（非公式）时，新规则不触发：脚注号/上标序数等不并入公式。"""
    parts = _script_case(3.7, base_font='F0', script_font='F0')
    holder = next(p for p in parts if 'ab' in p[1])
    assert not holder[2]


@pytest.mark.parametrize('text,font', [('The ordinary body text is still translated normally', 'F0'),
                                       ('这是普通中文正文，仍然按原样整段翻译。', 'F3')])
def test_ordinary_body_text_is_not_formula(text, font):
    chars, _ = _word(text, 10, 100, 10, font)
    page = _page_of(chars)
    _stage().process_page(page)
    parts = _parts(page)
    assert not [p for p in parts if p[0] == 'formula']
    assert ''.join(p[1] for p in parts).replace(' ', '') == text.replace(' ', '')


# ----------------------------------------------------------------------------- (B) 成品层级门
def _pdf(path, pages):
    doc = fitz.open()
    for items in pages:
        page = doc.new_page(width=300, height=300)
        for text, x, y, size, font in items:
            page.insert_text((x, y), text, fontsize=size, fontname=font)
    doc.save(str(path))
    doc.close()
    return path


def _vnmax(dx=0.0, dy=0.0, scale=1.0, max_raise=3.7, n_lower=2.4, prose=True):
    s = scale
    items = [('namely', 20 + dx, 100 + dy, 10 * s, 'tiro')] if prose else []
    items += [('V', 60 + dx, 100 + dy, 10 * s, 'tiit'),
              ('max', 60 + dx + 7.6 * s, 100 + dy - max_raise * s, 7 * s, 'tiro'),
              ('n', 60 + dx + 6.4 * s, 100 + dy + n_lower * s, 7 * s, 'tiit'),
              ('(U)', 60 + dx + 19 * s, 100 + dy, 10 * s, 'tiro')]
    return items


def _check(tmp_path, source_pages, target_pages):
    return fsc.check_formula_structure(_pdf(tmp_path / 's.pdf', source_pages), _pdf(tmp_path / 't.pdf', target_pages))


def test_source_relations_include_every_script_glyph(tmp_path):
    rel = fsc.script_relations(fitz.open(_pdf(tmp_path / 's.pdf', [_vnmax()]))[0])
    got = sorted((r['base'], r['script'], r['kind']) for r in rel)
    assert got == [('V', 'a', 'superscript'), ('V', 'm', 'superscript'), ('V', 'n', 'subscript'),
                   ('V', 'x', 'superscript')]


@pytest.mark.parametrize('target', [
    pytest.param([_vnmax(dx=35, dy=60, scale=0.95)], id='moved-and-scaled'),
    pytest.param([_vnmax(max_raise=3.3)], id='offset-within-tolerance'),
    pytest.param([[('other text', 20, 50, 10, 'tiro')], _vnmax(dy=20)], id='moved-to-next-page'),
])
def test_preserved_scripts_pass(tmp_path, target):
    result = _check(tmp_path, [_vnmax()], target)
    assert result['status'] == 'evaluated' and result['severity'] == 'ok' and result['lost'] == 0
    assert result['source_relations'] == 4


@pytest.mark.parametrize('target,lost', [
    pytest.param(_vnmax(max_raise=0.0), {'m', 'a', 'x'}, id='superscript-flattened'),
    pytest.param(_vnmax(n_lower=0.0), {'n'}, id='subscript-flattened'),
    pytest.param(_vnmax(n_lower=-2.4), {'n'}, id='subscript-flipped-to-superscript'),
    pytest.param(_vnmax(max_raise=2.0), {'m', 'a', 'x'}, id='superscript-offset-insufficient'),
    pytest.param([('namely', 20, 100, 10, 'tiro')], {'m', 'a', 'x', 'n'}, id='formula-dropped'),
])
def test_damaged_scripts_fail_closed(tmp_path, target, lost):
    result = _check(tmp_path, [_vnmax()], [target])
    assert result['severity'] == 'high' and result['quality_fail'] is True and result['flagged_pages'] == [1]
    assert {s['script'] for p in result['pages'] for s in p['samples']} == lost
    assert result['rule'] == 'formula_script_structure_lost'


def test_prose_footnote_mark_is_out_of_scope(tmp_path):
    source = [('word', 20, 100, 10, 'tiro'), ('1', 40.5, 96, 7, 'tiro')]
    flattened = [('word', 20, 100, 10, 'tiro'), ('1', 40.5, 100, 7, 'tiro')]
    result = _check(tmp_path, [source], [flattened])
    assert result['source_relations'] == 0 and result['severity'] == 'ok'


def test_closing_bracket_with_math_font_script(tmp_path):
    source = [('(', 20, 100, 10, 'tiro'), ('A', 24, 100, 10, 'tiit'), (')', 31, 100, 10, 'tiro'), ('a', 35, 96, 7, 'symb')]
    flat = [('(', 20, 100, 10, 'tiro'), ('A', 24, 100, 10, 'tiit'), (')', 31, 100, 10, 'tiro'), ('a', 35, 100, 7, 'symb')]
    assert _check(tmp_path, [source], [source])['severity'] == 'ok'
    result = _check(tmp_path, [source], [flat])
    assert result['severity'] == 'high' and result['pages'][0]['samples'][0]['base'] == ')'


def test_matrix_rows_are_not_scripts_but_matrix_subscript_is(tmp_path):
    """矩阵相邻两行（同字号上下排列）不是上/下标；矩阵右括号后的降低小字号尺寸标注是下标。"""
    rows = [('x', 60, 90, 10, 'tiit'), ('y', 80, 90, 10, 'tiit'), ('z', 60, 104, 10, 'tiit'), ('w', 80, 104, 10, 'tiit')]
    assert fsc.script_relations(fitz.open(_pdf(tmp_path / 'm.pdf', [rows]))[0]) == []
    source = rows + [(')', 92, 100, 14, 'symb'), ('2', 98, 104, 7, 'tiro')]
    flat = rows + [(')', 92, 100, 14, 'symb'), ('2', 98, 100, 7, 'tiro')]
    assert _check(tmp_path, [source], [source])['severity'] == 'ok'
    assert _check(tmp_path, [source], [flat])['severity'] == 'high'


def _stub_attach(monkeypatch, tmp_path, target):
    monkeypatch.setattr(qa, 'evaluate_quality_packet', lambda *a, **k: {'status': 'pass', 'quality_pass': True, 'issues': []})
    monkeypatch.setattr(qa, 'final_pdf_from_manifest', lambda *a, **k: target)
    monkeypatch.setattr(qa, 'audit_technical_receipt', lambda *a, **k: {'issues': [], 'pending': []})
    monkeypatch.setattr(qa, 'render_residue_gate', lambda *a, **k: {'severity': 'none'})


@pytest.mark.parametrize('damaged', [True, False])
def test_comprehensive_quality_uses_stable_rule_code(tmp_path, monkeypatch, damaged):
    source = _pdf(tmp_path / 's.pdf', [_vnmax()])
    target = _pdf(tmp_path / 't.pdf', [_vnmax(max_raise=0.0) if damaged else _vnmax(dx=20)])
    _stub_attach(monkeypatch, tmp_path, target)
    qa.attach_pipeline_quality({}, source=source, output_dir=tmp_path)
    result = json.loads((tmp_path / 'comprehensive_quality.json').read_text())
    issues = [i for i in result.get('issues', []) if i['id'] == 'formula_script_structure_lost']
    assert (tmp_path / 'formula_structure_check.json').is_file()
    if damaged:
        assert result['status'] == 'fail' and result['quality_pass'] is False and issues[0]['pages'] == [1]
        assert issues[0]['severity'] == 'high' and issues[0]['lost'] == 3
    else:
        assert not issues and result['status'] == 'pass'
        assert result['formula_structure_check']['status'] == 'evaluated'


def test_unreadable_target_is_not_evaluated_not_passed(tmp_path, monkeypatch):
    source = _pdf(tmp_path / 's.pdf', [_vnmax()])
    bad = tmp_path / 'x.pdf'
    bad.write_bytes(b'%PDF-1.4 stub')
    _stub_attach(monkeypatch, tmp_path, bad)
    qa.attach_pipeline_quality({}, source=source, output_dir=tmp_path)
    result = json.loads((tmp_path / 'comprehensive_quality.json').read_text())
    assert result['formula_structure_check']['status'] == 'not_evaluated'
    assert result['formula_structure_check']['reason']


# ----------------------------------------------------------------------------- (C) 可读版
MATH_TEXT = 'commutation [a_j, a†_k] = δ_jk and ∆ = ∆† hold.'


def _math_mono(path, damaged=False):
    return _pdf(path, [_vnmax(max_raise=0.0 if damaged else 3.7) + [('∆ = ∆', 20, 140, 10, 'symb')]])


def _render(tmp_path, markdown, *, mono=None, source=None, original=None, title='doc-title'):
    md = tmp_path / 'translation.qa_repaired.md'
    md.write_text(markdown, encoding='utf-8')
    orig = None
    if original is not None:
        orig = tmp_path / 'translation.md'
        orig.write_text(original, encoding='utf-8')
    out = tmp_path / 'final_readable.pdf'
    manifest = rr.render_pdf(md, out, title=title, math_source_pdf=mono, source_pdf=source, original_markdown_path=orig)
    return manifest, out


def test_math_page_is_vector_copied_and_lossless(tmp_path):
    mono = _math_mono(tmp_path / 'mono.pdf')
    source = _pdf(tmp_path / 'src.pdf', [_vnmax()])
    text = 'namely V maxn (U)\n' + MATH_TEXT
    manifest, out = _render(tmp_path, text, mono=mono, source=source, original=text)
    assert manifest['status'] == 'ok' and out.is_file()
    assert manifest['math_fidelity']['page_modes'] == {'1': 'vector_page_copy'}
    with fitz.open(out) as readable, fitz.open(mono) as main:
        assert readable.metadata['title'] == 'doc-title'
        assert readable[0].get_text() == main[0].get_text()
        a, b = readable[0].get_pixmap(dpi=72), main[0].get_pixmap(dpi=72)
        assert a.samples == b.samples
    # 矢量页上的上/下标几何与主版式页逐字形一致
    assert fsc.check_formula_structure(source, out)['severity'] == 'ok'


def test_prose_source_without_mono_still_reflows(tmp_path):
    source = _pdf(tmp_path / 'src.pdf', [[('Plain prose only', 20, 100, 10, 'helv')]])
    manifest, out = _render(tmp_path, '普通正文段落。', source=source)
    assert manifest['status'] == 'ok' and out.is_file()


def test_prose_page_still_reflows(tmp_path):
    mono = _pdf(tmp_path / 'mono.pdf', [[('Plain prose only', 20, 100, 10, 'helv')]])
    manifest, out = _render(tmp_path, '普通正文段落，没有公式。\n\nPlain prose only.', mono=mono)
    assert manifest['status'] == 'ok' and manifest['math_fidelity']['page_modes'] == {'1': 'reflow'}
    assert '普通正文段落' in fitz.open(out)[0].get_text()


def test_form_feed_pages_mix_reflow_and_vector(tmp_path):
    mono = _pdf(tmp_path / 'mono.pdf', [[('Plain prose only', 20, 100, 10, 'helv')], _vnmax()])
    manifest, out = _render(tmp_path, 'Plain prose only.\fnamely V maxn (U)', mono=mono)
    assert manifest['status'] == 'ok'
    assert manifest['math_fidelity']['page_modes'] == {'1': 'reflow', '2': 'vector_page_copy'}
    assert len(fitz.open(out)) == 2


@pytest.mark.parametrize('case,code', [
    ('no_mono_math_glyphs', 'readable_codepoint_loss'),
    ('damaged_mono', 'readable_math_source_structure_lost'),
    ('repair_conflict', 'readable_math_page_repair_conflict'),
    ('unmapped_pages', 'readable_page_mapping_unknown'),
    ('backend_failed_no_mono', 'readable_math_source_missing'),
])
def test_unsupported_readable_is_refused_before_delivery(tmp_path, case, code):
    out = tmp_path / 'final_readable.pdf'
    out.write_bytes(b'stale')   # 上一次的旧成品不得冒充本次结果
    source = _pdf(tmp_path / 'src.pdf', [_vnmax()])
    if case == 'no_mono_math_glyphs':
        manifest, out = _render(tmp_path, MATH_TEXT)
    elif case == 'damaged_mono':
        manifest, out = _render(tmp_path, MATH_TEXT, mono=_math_mono(tmp_path / 'mono.pdf', damaged=True), source=source,
                                original=MATH_TEXT)
    elif case == 'repair_conflict':
        manifest, out = _render(tmp_path, MATH_TEXT.replace('δ_jk', 'δ_kj'), mono=_math_mono(tmp_path / 'mono.pdf'), source=source,
                                original=MATH_TEXT)
    elif case == 'unmapped_pages':
        mono = _pdf(tmp_path / 'mono.pdf', [_vnmax(), _vnmax()])
        manifest, out = _render(tmp_path, MATH_TEXT, mono=mono)
    else:   # 主版式后端失败、没有可复制的成品页：即便文字码位都能重排，原文的上下标也会被压平
        manifest, out = _render(tmp_path, 'namely V maxn (U)', source=source)
    assert manifest['status'] == 'refused' and manifest['reason_code'] == code and code in rr.REFUSAL_CODES
    assert manifest['output_pdf'] is None and not out.exists()
    assert not list(tmp_path.glob('*.tmp-parts'))


def test_appended_recovery_section_is_reflowed_after_vector_page(tmp_path):
    """QA 修复只在末页之后追加的内容（受保护内容恢复等）作为附录重排，矢量页本身不变。"""
    mono = _math_mono(tmp_path / 'mono.pdf')
    original = 'namely V maxn (U)'
    manifest, out = _render(tmp_path, original + '\n\n## 受保护内容恢复\n\n- [12]', mono=mono, original=original)
    assert manifest['status'] == 'ok'
    assert [c['mode'] for c in manifest['math_fidelity']['checks']] == ['vector_page_copy', 'appendix']
    assert len(fitz.open(out)) == 2


def test_render_qa_repaired_pdf_title_is_source_stem_and_refusal_is_recorded(tmp_path):
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    (out_dir / 'translation.md').write_text('namely V maxn (U)', encoding='utf-8')
    (out_dir / 'translation.qa_repaired.md').write_text('namely V maxn (U)', encoding='utf-8')
    src = _pdf(tmp_path / '18-zh-formulas.pdf', [_vnmax()])
    ok_mono = _pdf(out_dir / 'ok.mono.pdf', [_vnmax(dx=10)])
    manifest = artifacts.render_qa_repaired_pdf(out_dir, NS(post_qa_repair='auto', input_pdf=str(src)), translated_pdf=ok_mono)
    assert manifest['status'] == 'ok' and manifest['title'] == '18-zh-formulas'
    assert fitz.open(out_dir / 'final_readable.pdf').metadata['title'] == '18-zh-formulas'
    bad_mono = _pdf(out_dir / 'bad.mono.pdf', [_vnmax(max_raise=0.0)])
    manifest = artifacts.render_qa_repaired_pdf(out_dir, NS(post_qa_repair='auto', input_pdf=str(src)), translated_pdf=bad_mono)
    assert manifest['status'] == 'refused' and manifest['reason_code'] == 'readable_math_source_structure_lost'
    assert manifest['output'] is None and not (out_dir / 'final_readable.pdf').exists()
    saved = json.loads((out_dir / 'final_pdf_manifest.json').read_text())
    assert saved['reason_code'] == 'readable_math_source_structure_lost'
    receipt = qa.readable_fidelity_receipt(out_dir)
    assert receipt['status'] == 'refused' and receipt['reason_code'] == 'readable_math_source_structure_lost'
