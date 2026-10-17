"""真实小字体/PDF：修复新字体复制映射，保护原字体与画面。"""
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import fitz,pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from owned_font_unicode import bind_owned_font_unicode,bind_typeset_owned_font_unicode

def fixture(tmp_path):
    fb=FontBuilder(1000,isTTF=True);order=['.notdef','space','A'];fb.setupGlyphOrder(order)
    glyphs={}
    for name in order:
        pen=TTGlyphPen(None)
        if name=='A':pen.moveTo((0,0));pen.lineTo((250,700));pen.lineTo((500,0));pen.closePath()
        glyphs[name]=pen.glyph()
    fb.setupGlyf(glyphs);fb.setupHorizontalMetrics({n:(600,0)for n in order});fb.setupHorizontalHeader(ascent=800,descent=-200);fb.setupCharacterMap({32:'space',65:'A'});fb.setupNameTable({'familyName':'OwnedFixture','styleName':'Regular','uniqueFontIdentifier':'OwnedFixture','fullName':'OwnedFixture','psName':'OwnedFixture'});fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200);fb.setupPost();fb.setupMaxp();p=tmp_path/'font.ttf';fb.save(p)
    doc=fitz.open();page=doc.new_page();xref=page.insert_font(fontname='Owned',fontfile=str(p));page.insert_text((30,40),'A A',fontname='Owned',fontsize=12)
    chars=[NS(pdf_style=NS(font_id='Owned'),pdf_character_id=i,char_unicode=c)for i,c in [(2,'A'),(1,' '),(2,'A')]]
    il=NS(page=[NS(page_number=0,pdf_character=[],pdf_paragraph=[NS(chars=chars)])])
    return doc,xref,il

def test_actual_copy_space_is_repaired_without_paint_or_stream_changes(tmp_path):
    doc,xref,il=fixture(tmp_path);bind_owned_font_unicode(doc,xref,{1:'\x01',2:'A'},owned_font_xrefs={xref});page=doc[0]
    assert '\x01'in page.get_text();pixels=page.get_pixmap().samples;streams=[doc.xref_stream(x)for x in page.get_contents()];program=doc.extract_font(xref)[3]
    result=bind_typeset_owned_font_unicode(doc,il,owned_font_ids={'Owned'},source_font_xrefs=set(),paragraph_characters=lambda p:p.chars)
    assert result[0]['actual_space_cids']==[1]
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor/babeldoc'))
    from babeldoc.format.pdf.document_il.backend.pdf_creater import reproduce_one_font
    # 模拟后续高层兼容性清理：以前此处过滤无墨迹空格，导致CID被读成控制符。
    reproduce_one_font(doc,xref)
    # 重新打开以清除MuPDF字体缓存，模拟普通阅读器保存重开。
    saved=fitz.open(stream=doc.tobytes(),filetype='pdf')
    assert saved[0].get_text().strip()=='A A'
    assert saved[0].get_pixmap().samples==pixels
    assert [saved.xref_stream(x)for x in saved[0].get_contents()]==streams
    assert saved.extract_font(xref)[3]==program

def test_original_font_mapping_cannot_be_changed(tmp_path):
    doc,xref,il=fixture(tmp_path)
    with pytest.raises(ValueError,match='source_font'):
        bind_typeset_owned_font_unicode(doc,il,owned_font_ids={'Owned'},source_font_xrefs={xref},paragraph_characters=lambda p:p.chars)

def test_ambiguous_same_CID_different_text_is_rejected(tmp_path):
    doc,xref,il=fixture(tmp_path);il.page[0].pdf_paragraph[0].chars[0].pdf_character_id=1
    with pytest.raises(ValueError,match='ambiguous_unicode'):
        bind_typeset_owned_font_unicode(doc,il,owned_font_ids={'Owned'},source_font_xrefs=set(),paragraph_characters=lambda p:p.chars)
