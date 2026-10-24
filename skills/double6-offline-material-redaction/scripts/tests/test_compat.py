import sys,io,zipfile,unittest,tempfile,subprocess,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
import compat,engine,formats


def odf(ext,body,styles='',extra=None):
    buf=io.BytesIO()
    ns=' '.join('xmlns:'+p+'="'+v[1:-1]+'"'for p,v in compat.NS.items())
    with zipfile.ZipFile(buf,'w')as z:
        z.writestr('mimetype',compat.ODF[ext]);z.writestr('content.xml','<office:document-content '+ns+'><office:automatic-styles>'+styles+'</office:automatic-styles><office:body>'+body+'</office:body></office:document-content>')
        for n,b in (extra or {}).items():z.writestr(n,b)
    return buf.getvalue()


class CompatTests(unittest.TestCase):
    def test_hidden_text_annotation_and_link_target_not_resurrected(self):
        data=odf('.odt','<office:text><text:p>业务120 <text:span text:style-name="Hidden">PRIVATE</text:span><text:a xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://PRIVATE">可见链接</text:a><office:annotation><text:p>PRIVATE</text:p></office:annotation></text:p></office:text>','<style:style style:name="Hidden" style:family="text"><style:text-properties text:display="none"/></style:style>')
        out,info=compat.normalize(data,'.odt');text=engine.inspect_docx(out)['preview'];self.assertIn('业务120',text);self.assertIn('可见链接',text);self.assertNotIn('PRIVATE',text);self.assertGreaterEqual(info['hidden_nodes_removed'],2)
        self.assertNotIn(b'PRIVATE',b''.join(engine.read_package(out).values()))
    def test_hidden_sheet_row_column_and_cached_formula(self):
        body='<office:spreadsheet><table:table><table:table-column/><table:table-column table:visibility="collapse"/><table:table-row><table:table-cell office:value-type="float" office:value="120" table:formula="of:=60+60"/><table:table-cell office:value-type="string"><text:p>PRIVATE</text:p></table:table-cell></table:table-row><table:table-row table:visibility="collapse"><table:table-cell><text:p>PRIVATE</text:p></table:table-cell></table:table-row><table:table-row table:number-rows-repeated="1048575"><table:table-cell table:number-columns-repeated="16384"/></table:table-row></table:table><table:table table:display="false"><table:table-row><table:table-cell><text:p>PRIVATE</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet>'
        out,_=compat.normalize(odf('.ods',body),'.ods');model,_,text=formats.excel_model(out);self.assertEqual(len(model),1);self.assertEqual(model[0],[(1,1,120)]);self.assertNotIn('PRIVATE',text)
    def test_hidden_slides_notes_and_editable_table(self):
        body='<office:presentation><draw:page><draw:frame><draw:text-box><text:p>业务120</text:p></draw:text-box></draw:frame><draw:frame><table:table><table:table-row><table:table-cell><text:p>项目甲</text:p></table:table-cell></table:table-row></table:table></draw:frame><presentation:notes><text:p>PRIVATE</text:p></presentation:notes></draw:page><draw:page draw:style-name="H"><text:p>PRIVATE</text:p></draw:page></office:presentation>'
        styles='<style:style style:name="H" style:family="drawing-page"><style:drawing-page-properties presentation:visibility="hidden"/></style:style>'
        out,_=compat.normalize(odf('.odp',body,styles),'.odp');model,_,text=formats.slides_model(out);self.assertEqual(len(model),1);self.assertNotIn('PRIVATE',text);self.assertTrue(any(t=='table'for t,v in model[0]));self.assertIn('项目甲',text)
    def test_conditional_hidden_ambiguous_master_and_encryption_stop(self):
        for data in [odf('.odt','<office:text><text:hidden-text>private</text:hidden-text></office:text>'),odf('.odt','<office:text><text:p>visible</text:p></office:text>',extra={'META-INF/manifest.xml':'<manifest><encryption-data xmlns="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/></manifest>'})]:
            with self.assertRaises(engine.Rejected):compat.normalize(data,'.odt')
    def test_macro_container_and_wrong_format_rejected(self):
        data=odf('.odt','<office:text><text:p>visible</text:p></office:text>',extra={'Basic/Module.xml':'private'})
        with self.assertRaises(engine.Rejected):compat.normalize(data,'.odt')
        with self.assertRaises(engine.Rejected):compat.normalize(data,'.ods')
        with self.assertRaises(engine.Rejected):compat.normalize(b'not binary','.doc')
    def test_hidden_outline_groups_are_not_promoted_to_visible(self):
        body='<office:spreadsheet><table:table><table:table-column/><table:table-column-group table:display="false"><table:table-column/></table:table-column-group><table:table-row><table:table-cell><text:p>业务120</text:p></table:table-cell><table:table-cell><text:p>PRIVATE_COLUMN</text:p></table:table-cell></table:table-row><table:table-row-group table:display="false"><table:table-row><table:table-cell><text:p>PRIVATE_ROW</text:p></table:table-cell></table:table-row></table:table-row-group></table:table></office:spreadsheet>'
        out,_=compat.normalize(odf('.ods',body),'.ods');text=formats.excel_model(out)[2];self.assertIn('业务120',text);self.assertNotIn('PRIVATE',text)
    def test_missing_cache_and_unsupported_slide_stop(self):
        cases=[('.ods','<office:spreadsheet><table:table><table:table-row><table:table-cell table:formula="of:=60+60"/></table:table-row></table:table></office:spreadsheet>'),('.odp','<office:presentation><draw:page><draw:image/></draw:page></office:presentation>')]
        for ext,body in cases:
            with self.assertRaises(engine.Rejected):compat.normalize(odf(ext,body),ext)
    def test_hidden_string_attribute_never_restores_empty_visible_cell(self):
        body='<office:spreadsheet><table:table><table:table-row><table:table-cell office:value-type="string" office:string-value="PRIVATE"><text:p><text:span text:style-name="H">PRIVATE</text:span></text:p></table:table-cell><table:table-cell><text:p>业务120</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet>'
        style='<style:style style:name="H" style:family="text"><style:text-properties text:display="none"/></style:style>'
        out,_=compat.normalize(odf('.ods',body,style),'.ods');self.assertNotIn('PRIVATE',formats.excel_model(out)[2])

class VerifyBoundaryTests(unittest.TestCase):
    def test_verify_never_normalizes_a_legacy_original(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);source=root/'original.doc';source.write_bytes(b'original bytes, deliberately not convertible');plan=root/'plan.json';plan.write_text(json.dumps({'version':1,'kind':'word','reviewed':True,'terms':[],'clean_only':True,'acknowledge_loss':True}))
            p=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'cli.py'),'verify','--input',str(source),'--plan',str(plan)],capture_output=True)
            self.assertEqual(p.returncode,2);self.assertIn('verify',json.loads(p.stdout.decode('utf8'))['error']);self.assertEqual(source.read_bytes(),b'original bytes, deliberately not convertible');self.assertEqual(p.stderr,b'')
