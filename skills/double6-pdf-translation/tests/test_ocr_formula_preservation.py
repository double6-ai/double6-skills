"""复用原样独立真实OCR输入，必须拒绝不支持数学或无损保留公式。"""
from pathlib import Path
import json
from ocr_math_pages import reviewer_root  # PR #20 review 1：仅路径改动——输入由 reviewer probe 的同一生成方式在本机真实生成
R=reviewer_root()
def test_superscript_is_not_silently_destroyed():
 result=json.loads((R/'ocr-independent/superscript.result.json').read_text())
 assert result['ocr_status']=='blocked' or 'x²' in result.get('reconstructed_text',''), 'Actual OCR accepts x² source but rebuilds x? and paints over the original mathematical exponent'
