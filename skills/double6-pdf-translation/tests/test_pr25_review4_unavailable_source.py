"""PR #25 review 4（P2）：显式提供但不可用的原件不得按“无数学”处理。

前两个用例为用户独立复现 test_unavailable_math_source.py 原样搬入（仅导入路径改为本仓库）：传入不存在的原件路径时，
旧实现 `if source_pdf and Path(source_pdf).is_file()` 直接跳过原文核对，压平的 V2 以 ok 重排写出 final_readable.pdf。
其后为同范围边界：目录、无读权限、stat 抛 PermissionError/OSError、无效字节（仍拒绝）；主版式成品显式提供但不可用；
修复前译文显式提供但不可用；source_pdf=None 的独立普通 Markdown 入口照旧重排；流水线调用方原样传入原件路径。
"""
from pathlib import Path
import sys,json,hashlib,os
import pytest,fitz
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'scripts'))
import render_readable_pdf as rr
from test_pr25_review3_readable_source_math import make

@pytest.mark.parametrize('mode',['missing','invalid'])
def test_unavailable_source_is_not_treated_as_no_math(tmp_path,mode):
 original=tmp_path/'frozen-source.pdf';make(original,False)
 target=tmp_path/'flattened-target.pdf';make(target,True)
 md=tmp_path/'translation.md';md.write_text(fitz.open(target)[0].get_text())
 unavailable=tmp_path/'unavailable-source.pdf'
 if mode=='invalid':unavailable.write_bytes(b'not a pdf')
 out=tmp_path/'final_readable.pdf'
 result=rr.render_pdf(md,out,math_source_pdf=target,source_pdf=unavailable,original_markdown_path=md)
 audit={'mode':mode,'actual_original':str(original),'original_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'supplied_source':str(unavailable),'supplied_source_exists':unavailable.exists(),'target_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'readable':result,'output_exists':out.exists(),'scope':'实际PDF和真实render_pdf；原件参数显式提供但路径不可用。未声称完整后端最终质量通过。'}
 (tmp_path/'UNAVAILABLE_AUDIT.json').write_text(json.dumps(audit,indent=2))
 assert result['status']=='refused' and result['reason_code']=='readable_math_structure_unverifiable',audit
 assert not out.exists()


# ----------------------------------------------------------------------------- 相邻边界
def _case(tmp_path):
    target = tmp_path / 'flattened-target.pdf'
    make(target, True)
    md = tmp_path / 'translation.md'
    md.write_text(fitz.open(target)[0].get_text())
    out = tmp_path / 'final_readable.pdf'
    out.write_bytes(b'stale')   # 上一次的旧成品不得留下冒充本次结果
    return target, md, out


def _assert_refused(result, out, tmp_path, stage):
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_structure_unverifiable', result
    assert result['refusal']['stage'] == stage
    assert result['output_pdf'] is None and not out.exists()
    assert not list(tmp_path.glob('*.tmp-parts'))


def test_missing_source_path_is_refused_with_a_stable_stage(tmp_path):
    target, md, out = _case(tmp_path)
    result = rr.render_pdf(md, out, math_source_pdf=target, source_pdf=tmp_path / 'nope.pdf', original_markdown_path=md)
    _assert_refused(result, out, tmp_path, 'source_pdf_unavailable')
    assert result['refusal']['error'] == 'missing'


def test_directory_source_path_is_refused(tmp_path):
    target, md, out = _case(tmp_path)
    folder = tmp_path / 'source.pdf'
    folder.mkdir()
    result = rr.render_pdf(md, out, math_source_pdf=target, source_pdf=folder, original_markdown_path=md)
    _assert_refused(result, out, tmp_path, 'source_pdf_unavailable')
    assert result['refusal']['error'] == 'not_a_regular_file'


@pytest.mark.skipif(hasattr(os, 'geteuid') and os.geteuid() == 0, reason='root 可读取 chmod 000 文件，无法构造不可读原件')
def test_unreadable_source_file_is_refused(tmp_path):
    target, md, out = _case(tmp_path)
    source = tmp_path / 'source.pdf'
    make(source, False)
    source.chmod(0)
    try:
        result = rr.render_pdf(md, out, math_source_pdf=target, source_pdf=source, original_markdown_path=md)
    finally:
        source.chmod(0o644)
    _assert_refused(result, out, tmp_path, 'source_pdf_unavailable')
    assert result['refusal']['error'].startswith('permission_denied')


@pytest.mark.parametrize('error', [PermissionError(13, 'Permission denied'), OSError(5, 'Input/output error')])
def test_source_stat_raising_is_refused_not_raised(tmp_path, monkeypatch, error):
    target, md, out = _case(tmp_path)
    source = tmp_path / 'source.pdf'
    make(source, False)
    real_stat = os.stat

    def flaky_stat(path, *args, **kwargs):
        if str(path) == str(source):
            raise error
        return real_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, 'stat', flaky_stat)
    result = rr.render_pdf(md, out, math_source_pdf=target, source_pdf=source, original_markdown_path=md)
    monkeypatch.undo()
    _assert_refused(result, out, tmp_path, 'source_pdf_unavailable')


def test_invalid_source_bytes_are_still_refused(tmp_path):
    target, md, out = _case(tmp_path)
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'not a pdf')
    result = rr.render_pdf(md, out, math_source_pdf=target, source_pdf=source, original_markdown_path=md)
    _assert_refused(result, out, tmp_path, 'source_page_evidence')


def test_standalone_markdown_without_source_still_reflows(tmp_path):
    md = tmp_path / 'translation.md'
    md.write_text('Plain standalone prose, V2 on the baseline.\n', encoding='utf-8')
    out = tmp_path / 'final_readable.pdf'
    result = rr.render_pdf(md, out, title='Standalone')
    assert result['status'] == 'ok' and out.is_file()
    assert result['math_fidelity']['vector_pages'] == []
    assert 'V2' in ''.join(fitz.open(out)[0].get_text().split())


def test_standalone_with_main_layout_and_no_source_keeps_previous_behaviour(tmp_path):
    target, md, out = _case(tmp_path)
    result = rr.render_pdf(md, out, math_source_pdf=target, original_markdown_path=md)
    assert result['status'] == 'ok' and out.is_file()


def test_unavailable_main_layout_without_source_is_refused(tmp_path):
    _, md, out = _case(tmp_path)
    result = rr.render_pdf(md, out, math_source_pdf=tmp_path / 'missing-mono.pdf', original_markdown_path=md)
    _assert_refused(result, out, tmp_path, 'math_source_pdf_unavailable')


def test_invalid_main_layout_bytes_without_source_are_refused(tmp_path):
    _, md, out = _case(tmp_path)
    mono = tmp_path / 'mono.pdf'
    mono.write_bytes(b'not a pdf')
    result = rr.render_pdf(md, out, math_source_pdf=mono, original_markdown_path=md)
    _assert_refused(result, out, tmp_path, 'math_source_pdf_unavailable')


def test_unavailable_main_layout_with_source_math_is_source_missing(tmp_path):
    _, md, out = _case(tmp_path)
    source = tmp_path / 'source.pdf'
    make(source, False)
    result = rr.render_pdf(md, out, math_source_pdf=tmp_path / 'missing-mono.pdf', source_pdf=source, original_markdown_path=md)
    assert result['status'] == 'refused' and result['reason_code'] == 'readable_math_source_missing'
    assert result['math_fidelity']['math_source_unavailable'] == 'missing' and not out.exists()


def test_unavailable_main_layout_with_prose_source_still_reflows(tmp_path):
    _, md, out = _case(tmp_path)
    source = tmp_path / 'source.pdf'
    make(source, True)   # 原文本身没有数学
    result = rr.render_pdf(md, out, math_source_pdf=tmp_path / 'missing-mono.pdf', source_pdf=source, original_markdown_path=md)
    assert result['status'] == 'ok' and out.is_file()
    assert result['math_fidelity']['math_source_unavailable'] == 'missing'


def test_unavailable_original_markdown_with_math_pages_is_refused(tmp_path):
    source = tmp_path / 'source.pdf'
    make(source, False)
    md = tmp_path / 'translation.qa_repaired.md'
    md.write_text(fitz.open(source)[0].get_text())
    out = tmp_path / 'final_readable.pdf'
    result = rr.render_pdf(md, out, math_source_pdf=source, source_pdf=source, original_markdown_path=tmp_path / 'translation.md')
    _assert_refused(result, out, tmp_path, 'original_markdown_unavailable')


def test_lossless_formula_and_prose_positives_are_unchanged(tmp_path):
    source = tmp_path / 'source.pdf'
    make(source, False)
    md = tmp_path / 'translation.md'
    md.write_text(fitz.open(source)[0].get_text())
    result = rr.render_pdf(md, tmp_path / 'a.pdf', math_source_pdf=source, source_pdf=source, original_markdown_path=md)
    assert result['status'] == 'ok' and result['math_fidelity']['vector_pages'] == [1]
    prose = tmp_path / 'prose.pdf'
    make(prose, True)
    md.write_text(fitz.open(prose)[0].get_text())
    result = rr.render_pdf(md, tmp_path / 'b.pdf', math_source_pdf=prose, source_pdf=prose, original_markdown_path=md)
    assert result['status'] == 'ok' and result['math_fidelity']['vector_pages'] == []


# ----------------------------------------------------------------------------- 流水线调用方
def _pipeline_dir(tmp_path):
    import argparse
    out = tmp_path / 'out'
    out.mkdir()
    target = out / 'paper.no_watermark.zh.mono.pdf'
    make(target, True)
    text = fitz.open(target)[0].get_text()
    (out / 'translation.qa_repaired.md').write_text(text)
    (out / 'translation.md').write_text(text)
    return out, target, argparse.Namespace(post_qa_repair='auto')


def test_pipeline_passes_the_input_pdf_path_even_when_it_is_missing(tmp_path):
    import pdf_translation_artifacts as artifacts
    out, target, args = _pipeline_dir(tmp_path)
    args.input_pdf = str(tmp_path / 'gone' / 'paper.pdf')
    manifest = artifacts.render_qa_repaired_pdf(out, args, translated_pdf=target)
    assert manifest['status'] == 'refused' and manifest['reason_code'] == 'readable_math_structure_unverifiable'
    assert manifest['refusal']['stage'] == 'source_pdf_unavailable'
    assert manifest['output'] is None and not (out / 'final_readable.pdf').exists()
    saved = json.loads((out / 'final_pdf_manifest.json').read_text())
    assert saved['reason_code'] == 'readable_math_structure_unverifiable'


def test_pipeline_forwards_explicit_paths_unfiltered(tmp_path, monkeypatch):
    import pdf_translation_artifacts as artifacts
    out, target, args = _pipeline_dir(tmp_path)
    source = tmp_path / 'paper.pdf'
    make(source, False)
    args.input_pdf = str(source)
    seen = {}
    real = artifacts.render_readable_pdf.render_pdf

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(artifacts.render_readable_pdf, 'render_pdf', spy)
    manifest = artifacts.render_qa_repaired_pdf(out, args, translated_pdf=tmp_path / 'missing-mono.pdf')
    assert seen['source_pdf'] == source and seen['math_source_pdf'] == tmp_path / 'missing-mono.pdf'
    assert manifest['status'] == 'refused' and manifest['reason_code'] == 'readable_math_source_missing'
