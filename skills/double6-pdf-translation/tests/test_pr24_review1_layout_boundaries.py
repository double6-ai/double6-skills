# PR #24 review-1 评审独立用例（sha256 e5793f6138cbd5b0a6c6732be142f16d1041891634f7c5fe8d876f81cc0ecfdc）。
# 只改了路径：S 指向本仓库 Skill 根目录、辅助函数取自同目录 test_layout_line_fragments.py；输入与断言未改。
"""独立实际PDF字符几何→真实ParagraphFinder；不运行模型或完整翻译后端。"""
from pathlib import Path
import os,sys,json,hashlib
import fitz
R=Path(__file__).resolve().parent;TREE=os.environ.get('REVIEW_TREE','source');S=R.parent
helpers=(R/'test_layout_line_fragments.py').read_text().replace('ROOT = Path(__file__).resolve().parents[1]','ROOT = Path('+repr(str(S))+')')
ns={'__file__':str(R/'geometry_support.py'),'__name__':'geometry_support'};exec(compile(helpers,str(R/'geometry_support.py'),'exec'),ns)
il=ns['il']
def from_pdf(path,layouts):
 d=fitz.open(path);page=d[0];chars=[]
 for b in page.get_text('rawdict')['blocks']:
  for line in b.get('lines',[]):
   for span in line['spans']:
    for c in span['chars']:
     x,y,x2,y2=c['bbox'];box=il.Box(x=x,y=page.rect.height-y2,x2=x2,y2=page.rect.height-y)
     chars.append(il.PdfCharacter(pdf_style=il.PdfStyle(font_id='F1',font_size=span['size'],graphic_state=il.GraphicState()),box=box,visual_bbox=il.VisualBbox(box=il.Box(box.x,box.y,box.x2,box.y2)),vertical=False,scale=1.,pdf_character_id=ord(c['c'][0]),char_unicode=c['c'],xobj_id=0,render_order=0))
 return ns['_page'](chars,layouts)
def record(tmp_path,pdf,page):
 result=[{'text':ns['text'](p),'layout_id':p.layout_id,'label':p.layout_label,'box':[p.box.x,p.box.y,p.box.x2,p.box.y2]}for p in page.pdf_paragraph]
 (tmp_path/'LAYOUT_AUDIT.json').write_text(json.dumps({'tree':TREE,'pdf':str(pdf),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'paragraphs':result},indent=2));return result
def test_nested_body_container_keeps_two_columns_separate(tmp_path):
 pdf=tmp_path/'two-columns.pdf';d=fitz.open();p=d.new_page(width=612,height=792)
 for x,y,s in [(60,100,'The treatment reduces mortality.'),(60,118,'This applies to children.'),(330,100,'The control increases mortality.'),(330,118,'This applies to adults.')]:p.insert_text((x,y),s,fontsize=9,fontname='helv')
 d.save(pdf)
 layouts=[('plain text',(55,660,250,710)),('plain text',(325,660,550,710)),('plain text',(50,650,560,720))]
 out=ns['_process'](from_pdf(pdf,layouts));rows=record(tmp_path,pdf,out)
 assert len(rows)==2,rows
 assert 'reduces mortality' in rows[0]['text']and'increases mortality'not in rows[0]['text'],rows
 assert 'increases mortality'in rows[1]['text'],rows
def test_known_single_column_cells_keep_multiword_values(tmp_path):
 pdf=tmp_path/'single-column-table.pdf';d=fitz.open();p=d.new_page(width=612,height=792)
 p.draw_rect(fitz.Rect(90,150,280,220));p.draw_line(fitz.Point(90,185),fitz.Point(280,185))
 for words,y in [(('New','York','USA'),170),(('San','Jose','USA'),205)]:
  for x,word in zip((100,155,210),words):p.insert_text((x,y),word,fontsize=9,fontname='helv')
 d.save(pdf)
 layouts=[('table_cell',(90,607,280,642)),('table_cell',(90,572,280,607)),('table',(90,572,280,642))]
 out=ns['_process'](from_pdf(pdf,layouts));rows=record(tmp_path,pdf,out)
 assert len(rows)==2,rows
 assert rows[0]['text']=='New York USA'and rows[1]['text']=='San Jose USA',rows
