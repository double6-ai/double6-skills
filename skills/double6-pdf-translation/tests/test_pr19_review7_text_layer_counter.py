"""新成品门负例：正文单词中的 x 不能充当丢失的行内变量。无模型调用。"""
from pathlib import Path
import sys,json
import fitz,pytest
R=Path(__file__).resolve().parent
S=R.parent
sys.path[:0]=[str(S/'scripts'),str(S/'tests'),str(S/'vendor/babeldoc')]
import test_pr19_review_boundaries as b
from pdf_input_preflight import inspect_pdf
from render_residue_check import check_render_residue

def write_source(path,wrapped):
    d=fitz.open();p=b._inline_page(d)
    x=72+10.5*len(b.ZH_LINE_A)+4
    p.insert_text((x+2,120),'x',fontname='tiit',fontsize=11)
    if wrapped:
        w=fitz.open();q=w.new_page();q.show_pdf_page(q.rect,d,0);w.save(path);w.close()
    else:d.save(path)
    d.close()

@pytest.mark.parametrize('wrapped',[False,True])
@pytest.mark.parametrize('keep_variable',[False,True])
def test_words_do_not_replace_math_variable(tmp_path,wrapped,keep_variable):
    src=tmp_path/'source.pdf';tgt=tmp_path/'target.pdf';write_source(src,wrapped)
    # 表达式一词本来就包含 x；坏成品不含独立变量，正例包含变量并允许重排。
    head='Consider an array of '+('x 'if keep_variable else '')+'single-polarized omnidirectional antennas.'
    text=head+' This paper presents a mathematical framework for the far-field directivity of arrays and derives analytical expressions.'*3
    d=fitz.open();p=d.new_page();p.insert_textbox(fitz.Rect(72,72,520,400),text,fontname='helv',fontsize=10);d.save(tgt);d.close()
    pre=inspect_pdf(src,target_language='en',require_digital=True)
    qa=check_render_residue(src,tgt,target_language='en')
    (tmp_path/'TEXT_COUNTER.json').write_text(json.dumps({'keep_variable':keep_variable,'wrapped':wrapped,'preflight':pre,'quality':qa},ensure_ascii=False,indent=2))
    if keep_variable:assert not qa['quality_fail'],qa
    else:assert pre['status']=='blocked' or qa['quality_fail'],'Missing inline x is incorrectly matched to x inside expressions'
