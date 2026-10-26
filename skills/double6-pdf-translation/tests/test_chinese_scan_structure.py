"""中文扫描：条款续行、编号身份和英文空格的真实 PDF 文字层。"""
from pathlib import Path
import json
import sys

import fitz
import pytest

S = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(S/'scripts'), str(S/'vendor/babeldoc'), str(S/'vendor/pdfmathtranslate_next')]
from babeldoc.format.pdf.document_il import Box, PdfCharacter, PdfLine, PdfParagraph, PdfParagraphComposition
from babeldoc.format.pdf.document_il.backend.pdf_creater import make_tounicode, parse_tounicode_cmap, reproduce_one_font
from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder
from babeldoc.format.pdf.document_il.utils.cjk_structure import cjk_numbering, normalize_cjk_numbering, cjk_identifiers, missing_cjk_identifiers
from reviewed_text_source import reference, rebuild


def test_blank_glyph_unicode_survives_real_font_reproduction(tmp_path):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    builder=FontBuilder(1000,isTTF=True)
    builder.setupGlyphOrder(['.notdef','A','unused','space'])
    builder.setupCharacterMap({32:'space',65:'A'})
    glyphs={}
    for name in ['.notdef','A','unused','space']:
        pen=TTGlyphPen(None)
        if name=='A':
            pen.moveTo((100,0));pen.lineTo((500,0));pen.lineTo((500,700));pen.lineTo((100,700));pen.closePath()
        glyphs[name]=pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({n:(600,0) for n in glyphs})
    builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupNameTable({'familyName':'Double6Test','styleName':'Regular','uniqueFontIdentifier':'Double6Test',
                           'fullName':'Double6Test','psName':'Double6Test'})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupPost();builder.setupMaxp()
    font_path=tmp_path/'test.ttf';builder.save(font_path);font=fitz.Font(fontfile=str(font_path))
    # 真正的嵌入 TTF：空格是无轮廓的 CID 3，复现被错误删映射的路径。
    doc = fitz.open(); page = doc.new_page()
    writer = fitz.TextWriter(page.rect)
    writer.append((60,80), 'A A A', font=font, fontsize=12)
    writer.write_text(page)
    before = page.get_text()
    for row in page.get_fonts():
        reproduce_one_font(doc,row[0])
    output = tmp_path/'copy.pdf';doc.save(output);doc.close()
    with fitz.open(output) as actual:
        assert actual[0].get_text() == before and 'A A A' in before
        assert '\x03' not in actual[0].get_text()


@pytest.mark.parametrize('source,expected', [('三、网络接入规范', '3.'), ('（十一）应审核资质', '(11)'),
    ('(十二)应记录信息', '(12)'), ('（1）许可证有效', '(1)'), ('（二十九）普通条款', '(29)')])
def test_cjk_number_identity(source, expected):
    assert cjk_numbering(source)['output_marker'] == expected


@pytest.mark.parametrize('text', ['前文提及（一）条规定', '(x=2)为数学表达式', '(1) Normal English item',
    '（一二）错误编号', '2026年完成', '（B25）信息服务业务'])
def test_non_clause_is_not_reinterpreted(text):
    assert cjk_numbering(text) is None


def test_number_normalization_changes_only_leading_marker():
    source = '（十二）记录第十一项中的许可证及B25编号'
    output = '<style id="1">(XII) Record item XI and B25.</style>'
    assert normalize_cjk_numbering(source, output, 'en') == '<style id="1">(12) Record item XI and B25.</style>'
    assert normalize_cjk_numbering(source, output, 'zh') == output
    assert normalize_cjk_numbering('English source', output, 'en') == output


def test_category_code_omission_and_substring_are_not_accepted():
    source='（1）持有许可证（B2第二类业务中的B25信息服务业务），B25代码不变。'
    assert cjk_identifiers(source)==['B2','B25','B25']
    assert missing_cjk_identifiers(source,'(1) B2 information services.', 'en')==['B25','B25']
    assert missing_cjk_identifiers(source,'(1) B2 and B25, code B25.', 'en')==[]
    assert missing_cjk_identifiers('B2类别','B25 category','en')==['B2']
    assert missing_cjk_identifiers(source,'中文不按英文代码守门', 'zh')==[]


def test_missing_category_code_cannot_reach_paragraph_writeback():
    from types import SimpleNamespace
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator
    translator=ILTranslator.__new__(ILTranslator)
    translator.translation_config=SimpleNamespace(lang_out='en')
    events=[]
    tracker=SimpleNamespace(set_output=lambda text:events.append(('output',text)),
                            set_writeback_status=lambda *args:events.append(args))
    source='（1）B2业务中的B25信息服务业务。'
    p=PdfParagraph(unicode=source,layout_label='plain text')
    assert translator.post_translate_paragraph(p,tracker,SimpleNamespace(unicode=source),'(1) B2 information services.') is False
    assert p.unicode==source and p.writeback_status=='rejected'
    assert p.writeback_reason=='missing_protected_cjk_identifier:B25'


@pytest.mark.parametrize('text,correct', [('Fil.','用。'),('(+=)应建立管理系统，','(十二)应建立管理系统，')])
def test_high_confidence_cjk_structural_anomaly_requires_two_fresh_reads(tmp_path,monkeypatch,text,correct):
    from PIL import Image
    import ocr_route as ocr
    png=tmp_path/'page.png';Image.new('RGB',(500,100),'white').save(png)
    line={'text':text,'bbox_px':[20,20,460,60],'min_readable_word_conf':90,'mean_conf':92}
    calls=[]
    def read(*args,**kwargs):
        calls.append(kwargs['purpose'] if 'purpose' in kwargs else args[4])
        return {'text':correct,'words':[{'text':correct,'conf':95,'left':20,'top':20,'width':400,'height':40}],
                'mean':95,'weakest':95}
    monkeypatch.setattr(ocr,'_line_pass',read)
    ocr.verify_weak_lines([line],png,binary='unit',lang='chi_sim+eng',lang_key='chi_sim',workdir=tmp_path,page_no=1,log=[])
    assert len(calls)==2 and line['text']==correct and line['weak_word_verification']=='consensus'
    assert line['structural_reverification']


def test_structural_ocr_disagreement_keeps_original_and_math_gate(tmp_path,monkeypatch):
    from PIL import Image
    import ocr_route as ocr
    png=tmp_path/'page.png';Image.new('RGB',(500,100),'white').save(png)
    line={'text':'(+=)应记录内容','bbox_px':[20,20,460,60],'min_readable_word_conf':90,'mean_conf':92}
    results=iter([{'text':'(十二)应记录内容','mean':95,'weakest':95},{'text':'(十三)应记录内容','mean':95,'weakest':95}])
    monkeypatch.setattr(ocr,'_line_pass',lambda *args,**kwargs:next(results))
    ocr.verify_weak_lines([line],png,binary='unit',lang='chi_sim+eng',lang_key='chi_sim',workdir=tmp_path,page_no=1,log=[])
    assert line['text']=='(+=)应记录内容' and line['weak_word_verification']=='unverified'
    assert ocr.is_math_line(line['text']) and ocr.is_math_line('x = y + 2')
    assert ocr._cjk_structural_suspicion('(1)代码B25','chi_sim') is None
    assert ocr._cjk_structural_suspicion('Fil.','eng') is None


@pytest.mark.parametrize('angle',[0,90,180,270])
@pytest.mark.parametrize('mode',['vector','pypdf-vector'])
def test_rotated_source_bilingual_panel_matches_reader_orientation(tmp_path,angle,mode):
    import numpy as np
    from build_bilingual_pdf import build_en_left_zh_right_pdf
    a=tmp_path/'original.pdf';b=tmp_path/'target.pdf';out=tmp_path/'dual.pdf'
    d=fitz.open();p=d.new_page(width=300,height=400)
    p.draw_rect(fitz.Rect(25,40,95,110),fill=(.8,.1,.1));p.insert_text((30,160),'Original text',fontsize=16)
    p.set_rotation(angle);d.save(a);d.close();raw=a.read_bytes()
    with fitz.open(a) as original:
        w,h=original[0].rect.width,original[0].rect.height
        expected=original[0].get_pixmap(alpha=False)
    d=fitz.open();p=d.new_page(width=w,height=h);p.insert_text((30,80),'Translated text');d.save(b);d.close()
    build_en_left_zh_right_pdf(a,b,out,mode=mode)
    with fitz.open(out) as actual:
        assert tuple(actual[0].rect)==(0,0,w*2,h)
        # 避开中间分隔线的半像素，不以页数或文字数量代替旋转方向核验。
        got=actual[0].get_pixmap(clip=fitz.Rect(0,0,w-1,h),alpha=False)
        expected_array=np.frombuffer(expected.samples,np.uint8).reshape(expected.height,expected.width,3)[:,:got.width,:]
        got_array=np.frombuffer(got.samples,np.uint8).reshape(got.height,got.width,3)
        assert np.abs(expected_array.astype(float)-got_array.astype(float)).mean()<.1
    assert a.read_bytes()==raw


def paragraph(lines):
    parts=[]
    for n,text in enumerate(lines):
        chars=[]
        for x,c in enumerate(text):
            box=Box(60+x*8,700-n*20,68+x*8,714-n*20)
            chars.append(PdfCharacter(box=box,visual_bbox=__import__('types').SimpleNamespace(box=box),
                                      char_unicode=c,vertical=False,xobj_id=None))
        parts.append(PdfParagraphComposition(pdf_line=PdfLine(box=Box(60,700-n*20,60+len(text)*8,714-n*20),pdf_character=chars)))
    return PdfParagraph(box=Box(60,640,300,714),pdf_paragraph_composition=parts,layout_label='plain text',unicode=''.join(lines))


def test_cjk_list_splits_at_markers_and_keeps_wrapped_continuation():
    finder=ParagraphFinder.__new__(ParagraphFinder)
    p=paragraph(['（十一）审核以下资质：','（1）持有许可证，','且在有效期内；','（2）持有使用证书。'])
    before=[c for part in p.pdf_paragraph_composition for c in part.pdf_line.pdf_character]
    parts=finder._split_cjk_clause_paragraph(p)
    assert len(parts)==3
    assert [len(x.pdf_paragraph_composition) for x in parts]==[1,2,1]
    assert '且在有效期内' in parts[1].unicode and cjk_numbering(parts[2].unicode)['number']==2
    assert [c for x in parts for part in x.pdf_paragraph_composition for c in part.pdf_line.pdf_character]==before
    assert finder._split_cjk_clause_paragraph(paragraph(['普通正文，含（1）这样的行内引用','下一行是续文。']))[0].unicode.startswith('普通正文')


def review_fixture(tmp_path):
    src=tmp_path/'scan.pdf';d=fitz.open();d.new_page(width=300,height=400);d.save(src);d.close()
    font=tmp_path/'font.bin';font.write_bytes(fitz.Font('helv').buffer)
    review={'status':'executor_reviewed_source','reviewer':'unit test executor','original_scan':reference(src),
            'fonts':{'regular':reference(font)},'pages':[{'page':1,'complete_visible_text':True,'blocks':[
                {'id':'p1b1','role':'body','text':'A complete reviewed paragraph.', 'bbox':[30,40,270,120],
                 'font_size':14,'font':'regular','leading':20}]}]}
    p=tmp_path/'review.json';p.write_text(json.dumps(review));return p,review


def test_reviewed_source_preserves_geometry_and_visible_text(tmp_path):
    path,_=review_fixture(tmp_path);output=tmp_path/'new.pdf';m=rebuild(path,output)
    with fitz.open(output) as doc:
        assert tuple(doc[0].rect)==(0,0,300,400)
        assert doc[0].get_text().strip()=='A complete reviewed paragraph.'
        assert doc[0].get_text('dict')['blocks'][0]['lines'][0]['spans'][0]['size']==14
    assert m['automatic_ocr_acceptance'] is False and m['human_acceptance'] is False


@pytest.mark.parametrize('change,error', [('sha','reference_changed'),('scope','scope_incomplete'),
    ('blank','complete_page_review_required'),('overlap','blocks_overlap'),('overflow','block_overflow')])
def test_reviewed_source_rejects_changed_or_incomplete_inputs(tmp_path,change,error):
    path,r=review_fixture(tmp_path)
    if change=='sha':r['original_scan']['sha256']='0'*64
    if change=='scope':r['pages'][0]['page']=2
    if change=='blank':r['pages'][0]['blocks']=[]
    if change=='overlap':r['pages'][0]['blocks'].append({**r['pages'][0]['blocks'][0],'id':'second'})
    if change=='overflow':r['pages'][0]['blocks'][0]['bbox']=[30,40,270,41]
    path.write_text(json.dumps(r));output=tmp_path/'bad.pdf'
    with pytest.raises(ValueError,match=error):rebuild(path,output)
    assert not output.exists()
