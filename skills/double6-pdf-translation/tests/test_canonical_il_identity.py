# SPDX-License-Identifier: AGPL-3.0-only
"""保存与运行态源IL必须保持同一科学对象身份，实际矩阵变更仍必须可见。"""
from pathlib import Path
import sys,copy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pdf_source_groups import _paragraph


def fixture():
    box={'x':0.0,'y':0.0,'x2':10.0,'y2':10.0}
    char={'box':box,'char_unicode':'x','pdf_character_id':120,
          'pdf_style':{'font_id':'R1','font_size':10.0}}
    formula={'box':box,'pdf_character':[char]}
    para={'unicode':'x','box':box,'pdf_style':char['pdf_style'],
          'pdf_paragraph_composition':[{'pdf_formula':formula}]}
    return para,{'R1':{'font_id':'R1','name':'original-font','xref_id':1}}


def test_saved_and_dataclass_optional_nulls_have_same_identity():
    saved,fonts=fixture();live=copy.deepcopy(saved)
    char=live['pdf_paragraph_composition'][0]['pdf_formula']['pdf_character'][0]
    char.update(source_text_matrix=None,source_local_bbox=None)
    assert _paragraph(1,saved,fonts,'actual-source-sha')['identity']==_paragraph(1,live,fonts,'actual-source-sha')['identity']


def test_actual_source_matrix_cannot_disappear_from_identity():
    saved,fonts=fixture();live=copy.deepcopy(saved)
    live['pdf_paragraph_composition'][0]['pdf_formula']['pdf_character'][0]['source_text_matrix']=[1,0,0,1,3,4]
    assert _paragraph(1,saved,fonts,'actual-source-sha')['sha256']!=_paragraph(1,live,fonts,'actual-source-sha')['sha256']


def test_unrelated_metadata_is_not_silently_ignored():
    saved,fonts=fixture();live=copy.deepcopy(saved)
    live['pdf_paragraph_composition'][0]['pdf_formula']['unknown_source_field']=None
    assert _paragraph(1,saved,fonts,'actual-source-sha')['sha256']!=_paragraph(1,live,fonts,'actual-source-sha')['sha256']
