"""扫描写回冷进程。只读取冻结区域和源PDF，返回实际写回后的区域证据。"""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qa_source_contract import file_ref
from scanned_raster.pipeline import _render_translated_pdf
from scanned_raster.schema import validate_scan_region
from scanned_raster.mineru4_adapter import write_jsonl
import fitz

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--source-sha',required=True);p.add_argument('--target',required=True);p.add_argument('--regions',required=True);p.add_argument('--result',required=True);p.add_argument('--dpi',type=int,default=144);a=p.parse_args()
 source=Path(a.source);target=Path(a.target);path=Path(a.regions);result=Path(a.result)
 before=file_ref(source);region_ref=file_ref(path)
 if before['sha256']!=a.source_sha or path.stat().st_size>64*1024**2 or not 72<=a.dpi<=200:raise ValueError('isolated_writeback_input_bounds')
 if target.exists()or result.exists():raise ValueError('isolated_writeback_new_target_required')
 rows=[json.loads(l)for l in path.read_text().splitlines()]
 if not rows or len(rows)>20000 or len({r['page']for r in rows})>20 or sum(len(r.get('ocr_text',''))for r in rows)>1000000:raise ValueError('isolated_writeback_region_bounds')
 with fitz.open(source)as doc:
  if len(doc)>2000 or any(not 1<=r['page']<=len(doc)for r in rows):raise ValueError('isolated_writeback_page_bounds')
 for row in rows:
  if validate_scan_region(row)or row['source_pdf_sha256']!=before['sha256']:raise ValueError('isolated_writeback_region_identity')
 font=_render_translated_pdf(source,target,rows,dpi=a.dpi)
 if file_ref(source)!=before or file_ref(path)!=region_ref:raise ValueError('isolated_writeback_input_changed')
 updated=result.with_name('rendered_regions.jsonl');write_jsonl(updated,rows)
 record={'source':before,'target':file_ref(target),'input_regions':region_ref,'rendered_regions':file_ref(updated),'font_embedding':font,'status':'rendered_candidate_only','quality_pass':False}
 with result.open('x')as f:json.dump(record,f,ensure_ascii=False,indent=2)
 print(json.dumps({'status':record['status'],'quality_pass':False}))
if __name__=='__main__':main()

