"""PR #25 review 3（P2）：主版式已失去数学特征时，可读版仍须按原文/主版式结构报告判定。

前三个用例为用户独立复现 test_readable_source_math.py 原样搬入（仅导入路径改为本仓库 scripts/）：
主版式把 V^2 压成同基线 V2 时，旧实现只看主版式页的数学证据（为空），跳过原文结构核对并以 status=ok
重排写出损坏的 final_readable.pdf。其后为相邻边界：原文数学页在主版式里整页失去数学特征（无上下标关系，
仅数学字体）、多页中只有一页丢失、原文无数学的普通正文、页映射未知（重新分页）两向、结构核对无法完成。
"""
from pathlib import Path
import sys,json,hashlib
import fitz
import pytest
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'scripts'))
import render_readable_pdf as rr
import formula_structure_check as fc

def make(path, damaged):
 d=fitz.open();p=d.new_page(width=400,height=200)
 p.insert_text((40,80),'The response follows',fontname='tiro',fontsize=12)
 p.insert_text((155,80),'V',fontname='tiro'if damaged else'tiit',fontsize=12)
 p.insert_text((164,80 if damaged else 74),'2',fontname='tiro',fontsize=12 if damaged else 7)
 p.insert_text((175,80),'for every sample.',fontname='tiro',fontsize=12)
 d.save(path)

def test_readable_rejects_math_lost_in_target_even_without_target_math_evidence(tmp_path):
 source=tmp_path/'source.pdf';target=tmp_path/'flattened-target.pdf';make(source,False);make(target,True)
 md=tmp_path/'translation.md';md.write_text(fitz.open(target)[0].get_text())
 out=tmp_path/'final_readable.pdf'
 check=fc.check_formula_structure(source,target)
 se=rr.page_math_evidence(fitz.open(source)[0]);te=rr.page_math_evidence(fitz.open(target)[0])
 result=rr.render_pdf(md,out,title='Independent test',math_source_pdf=target,source_pdf=source,original_markdown_path=md)
 audit={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'target_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'source_evidence':se,'target_evidence':te,'structure_check':check,'readable':result,'output_exists':out.exists(),'scope':'实际PDF+真实公式结构检查及可读版函数；未声称完整后端最终quality pass'}
 (tmp_path/'READABLE_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
 assert se['has_math'] and check['quality_fail'] and check['lost']>0
 assert result['status']=='refused' and result['reason_code']=='readable_math_source_structure_lost',audit
 assert not out.exists()

def test_unchanged_supported_formula_remains_vector_preserved(tmp_path):
 source=tmp_path/'source.pdf';make(source,False)
 md=tmp_path/'translation.md';md.write_text(fitz.open(source)[0].get_text())
 out=tmp_path/'final_readable.pdf'
 result=rr.render_pdf(md,out,title='Independent test',math_source_pdf=source,source_pdf=source,original_markdown_path=md)
 assert result['status']=='ok' and out.is_file()
 assert result['math_fidelity']['vector_pages']==[1]
 a=fitz.open(source)[0].get_pixmap(alpha=False);b=fitz.open(out)[0].get_pixmap(alpha=False)
 assert (a.width,a.height,a.samples)==(b.width,b.height,b.samples)

def test_normal_baseline_text_remains_reflowable(tmp_path):
 source=tmp_path/'source.pdf';make(source,True)
 md=tmp_path/'translation.md';md.write_text(fitz.open(source)[0].get_text())
 out=tmp_path/'final_readable.pdf'
 result=rr.render_pdf(md,out,title='Independent test',math_source_pdf=source,source_pdf=source,original_markdown_path=md)
 assert result['status']=='ok' and out.is_file()
 assert result['math_fidelity']['vector_pages']==[]
 assert 'V2' in ''.join(fitz.open(out)[0].get_text().split())


# ----------------------------------------------------------------------------- 相邻边界
def _pages(path, specs):
    """specs: 每页 'prose' | 'symbol'（Symbol 字体 Σ≤，无上下标关系）| 'plain_symbol'（同文改为 Times）|
    'script'（V^2）| 'flat'（V2 同基线）。"""
    d = fitz.open()
    for kind in specs:
        p = d.new_page(width=400, height=200)
        p.insert_text((40, 60), 'Plain prose on this page stays reflowable.', fontname='tiro', fontsize=12)
        if kind == 'symbol':
            p.insert_text((40, 90), 'The bound', fontname='tiro', fontsize=12)
            p.insert_text((100, 90), '\u03a3 \u2264', fontname='symb', fontsize=12)
        elif kind == 'plain_symbol':
            p.insert_text((40, 90), 'The bound', fontname='tiro', fontsize=12)
            p.insert_text((100, 90), 'S at most', fontname='tiro', fontsize=12)
        elif kind in ('script', 'flat'):
            p.insert_text((40, 90), 'The response', fontname='tiro', fontsize=12)
            p.insert_text((120, 90), 'V', fontname='tiit' if kind == 'script' else 'tiro', fontsize=12)
            p.insert_text((129, 84 if kind == 'script' else 90), '2', fontname='tiro', fontsize=7 if kind == 'script' else 12)
    d.save(path)
    return path


def _markdown(tmp_path, target):
    doc = fitz.open(target)
    md = tmp_path / 'translation.md'
    md.write_text('\f'.join(page.get_text() for page in doc), encoding='utf-8')
    return md


def _render(tmp_path, source_specs, target_specs):
    source = _pages(tmp_path / 'source.pdf', source_specs)
    target = _pages(tmp_path / 'target.pdf', target_specs)
    md = _markdown(tmp_path, target)
    out = tmp_path / 'final_readable.pdf'
    result = rr.render_pdf(md, out, title='Boundary', math_source_pdf=target, source_pdf=source, original_markdown_path=md)
    return result, out


def test_source_math_page_whose_main_layout_lost_all_math_evidence_is_refused(tmp_path):
    # 无上下标关系可比（结构核对本身通过），但原文该页的数学字体字形在主版式整页消失：不能按无数学页重排。
    result, out = _render(tmp_path, ['symbol'], ['plain_symbol'])
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_source_structure_lost', result
    assert result['refusal']['pages'] == [1]
    assert result['refusal']['evidence'] == 'main_layout_math_evidence_missing'
    assert not out.exists()


def test_only_the_page_that_lost_math_is_named_in_a_multipage_refusal(tmp_path):
    result, out = _render(tmp_path, ['prose', 'symbol', 'symbol'], ['prose', 'symbol', 'plain_symbol'])
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_source_structure_lost'
    assert result['refusal']['pages'] == [3] and not out.exists()


def test_multipage_script_flattening_is_refused_by_the_source_structure_report(tmp_path):
    result, out = _render(tmp_path, ['prose', 'script'], ['prose', 'flat'])
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_source_structure_lost'
    assert result['refusal']['evidence'] == 'script_relations_lost' and result['refusal']['pages'] == [2]
    assert not out.exists()


def test_source_math_kept_in_main_layout_still_vector_copies(tmp_path):
    result, out = _render(tmp_path, ['prose', 'symbol', 'script'], ['prose', 'symbol', 'script'])
    assert result['status'] == 'ok' and out.is_file()
    assert result['math_fidelity']['vector_pages'] == [2, 3]
    assert result['math_fidelity']['source_page_mapping'] == 'same_page_count'


def test_source_without_math_keeps_normal_prose_reflow(tmp_path):
    result, out = _render(tmp_path, ['prose', 'prose'], ['prose', 'prose'])
    assert result['status'] == 'ok' and out.is_file()
    assert result['math_fidelity']['vector_pages'] == []
    assert 'source_structure_check' not in result['math_fidelity']


def test_unknown_page_mapping_with_all_math_gone_is_refused_not_reflowed(tmp_path):
    # 重新分页（原文 2 页、主版式 1 页）：逐页对应未知，主版式整份不剩数学特征 → 拒绝，不按普通无数学重排。
    result, out = _render(tmp_path, ['prose', 'symbol'], ['plain_symbol'])
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_source_structure_lost'
    assert result['refusal']['evidence'] == 'main_layout_math_evidence_missing'
    assert result['math_fidelity']['source_page_mapping'] == 'document_level'
    assert not out.exists()


def test_unknown_page_mapping_with_math_retained_vector_copies(tmp_path):
    result, out = _render(tmp_path, ['prose', 'symbol'], ['symbol'])
    assert result['status'] == 'ok' and out.is_file()
    assert result['math_fidelity']['source_page_mapping'] == 'document_level'
    assert result['math_fidelity']['vector_pages'] == [1]


def test_structure_check_that_raises_is_refused_as_unverifiable(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError('synthetic structure-check failure')
    monkeypatch.setattr(fc, 'check_formula_structure', boom)
    result, out = _render(tmp_path, ['script'], ['script'])
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_structure_unverifiable'
    assert result['refusal']['stage'] == 'structure_check' and not out.exists()


def test_structure_check_not_evaluated_is_refused_as_unverifiable(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, 'check_formula_structure', lambda *_a, **_k: {'status': 'not_evaluated', 'reason': 'synthetic'})
    result, out = _render(tmp_path, ['symbol'], ['symbol'])
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_structure_unverifiable'
    assert not out.exists()


def test_source_evidence_failure_is_refused_as_unverifiable(tmp_path, monkeypatch):
    real = rr.page_math_evidence
    source = _pages(tmp_path / 'source.pdf', ['script'])
    target = _pages(tmp_path / 'target.pdf', ['script'])

    def flaky(page):
        if page.parent.name == str(source):
            raise MemoryError('synthetic glyph cap')
        return real(page)
    monkeypatch.setattr(rr, 'page_math_evidence', flaky)
    md = _markdown(tmp_path, target)
    out = tmp_path / 'final_readable.pdf'
    result = rr.render_pdf(md, out, title='Boundary', math_source_pdf=target, source_pdf=source, original_markdown_path=md)
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_structure_unverifiable'
    assert result['refusal']['stage'] == 'source_page_evidence' and not out.exists()


def test_main_layout_evidence_failure_with_source_math_is_refused(tmp_path, monkeypatch):
    real = rr.page_math_evidence
    source = _pages(tmp_path / 'source.pdf', ['script'])
    target = _pages(tmp_path / 'target.pdf', ['script'])

    def flaky(page):
        if page.parent.name == str(target):
            raise MemoryError('synthetic glyph cap')
        return real(page)
    monkeypatch.setattr(rr, 'page_math_evidence', flaky)
    md = _markdown(tmp_path, target)
    out = tmp_path / 'final_readable.pdf'
    result = rr.render_pdf(md, out, title='Boundary', math_source_pdf=target, source_pdf=source, original_markdown_path=md)
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_structure_unverifiable'
    assert result['refusal']['stage'] == 'main_layout_page_evidence' and not out.exists()
