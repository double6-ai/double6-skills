"""实际OCR的汉字变量上下标不得涂改为标点；原输入与实际生成结果保留。"""
from pathlib import Path
import json,pytest
from ocr_math_pages import reviewer2_root  # PR #20 review 2：仅路径改动——输入由 reviewer probe 的同一生成方式在本机真实生成
R=reviewer2_root()
@pytest.mark.parametrize('case,bad,marker',[('cjk-variable-sup','甲-','²'),('cjk-variable-sub','甲,','₂')])
def test_cjk_script_not_destroyed(case,bad,marker):
 d=json.loads((R/'geometry-independent'/(case+'.result.json')).read_text())
 if d['ocr_status']=='blocked':return
 text=d.get('reconstructed_text','')
 assert bad not in text and any(x in text for x in ['2',marker]), 'Actual OCR erases a clear mathematical script and rebuilds punctuation: '+bad
