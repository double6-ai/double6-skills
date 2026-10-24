"""对实际容器、可搜索文字、原格式和不可覆盖行为做独立断言。"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image, ImageChops
sys.path.insert(0,str(Path(__file__).parents[1]))
import acceptance as examples
import engine
import output_policy as policy
import pdf_preserve


class NativeOutputTests(unittest.TestCase):
    def test_pdf_text_removed_business_searchable_and_old_attachment_absent(self):
        original=examples.pdf();out,r,ext=policy.export(original,'.pdf',examples.pdf_plan())
        with pdf_preserve.backend().open(stream=out,filetype='pdf')as d:
            self.assertIn(examples.KEEP,d[0].get_text());self.assertNotIn(examples.SECRET,d[0].get_text());self.assertEqual(d.embfile_count(),0)
            streams=b'\n'.join(d.xref_stream(i)or b''for i in range(1,d.xref_length()))
            self.assertNotIn(examples.SECRET.encode(),streams);self.assertFalse(d.metadata['author'])
        self.assertTrue(r['checks']['pdf_not_rasterized']);self.assertEqual(ext,'.pdf')

    def test_pdf_cover_rectangle_is_not_accepted_as_redaction(self):
        f=pdf_preserve.backend();d=f.open();p=d.new_page(width=300,height=200);p.insert_text((20,35),examples.SECRET);p.insert_text((20,120),examples.KEEP)
        raw=d.tobytes();p.draw_rect(f.Rect(10,15,145,47.5),color=None,fill=(0,0,0));fake=d.tobytes();d.close()
        with f.open(stream=fake,filetype='pdf')as check:self.assertIn(examples.SECRET,check[0].get_text())
        with self.assertRaises(engine.Rejected):policy.verify(fake,'.pdf',examples.pdf_plan(),raw)

    def test_pdf_white_text_and_occluded_text_are_rejected(self):
        f=pdf_preserve.backend()
        for mode in ['white','occluded']:
            d=f.open();p=d.new_page(width=300,height=200);p.insert_text((20,35),examples.SECRET);p.insert_text((20,120),examples.KEEP)
            if mode=='white':p.insert_text((20,180),'HIDDEN PRIVATE',color=(1,1,1))
            else:
                p.insert_text((20,180),'HIDDEN PRIVATE');p.draw_rect(f.Rect(10,160,200,190),color=None,fill=(1,1,1))
            raw=d.tobytes();d.close()
            with self.assertRaises(engine.Rejected):policy.export(raw,'.pdf',examples.pdf_plan())

    def test_pdf_rasterization_requires_explicit_mode(self):
        p=examples.pdf_plan();p.update(pdf_mode='rasterize',acknowledge_loss=True,keep=[])
        out,r,_=policy.export(examples.pdf(),'.pdf',p)
        with pdf_preserve.backend().open(stream=out,filetype='pdf')as d:self.assertEqual(d[0].get_text(),'')
        self.assertTrue(r['checks']['image_only_pdf'])

    def test_image_original_formats_metadata_and_real_encoding(self):
        for ext,fmt in [('.png','PNG'),('.jpg','JPEG'),('.jpeg','JPEG'),('.webp','WEBP')]:
            raw=examples.picture(fmt);out,r,actual=policy.export(raw,ext,{'rectangles':[[5,5,70,45]]})
            self.assertEqual(actual,ext)
            with Image.open(io.BytesIO(out))as d:
                self.assertEqual(d.format,fmt);self.assertFalse(d.getexif())
                self.assertLessEqual(max(v[1]for v in d.convert('RGB').crop((8,8,67,42)).getextrema()),8 if fmt=='JPEG'else 0)
            if fmt!='JPEG':
                delta=ImageChops.difference(engine.image_source(raw),engine.image_source(out));delta.paste((0,0,0),(5,5,70,45));self.assertIsNone(delta.getbbox())

    def test_image_trailing_payload_is_rejected(self):
        for ext,fmt in [('.png','PNG'),('.jpg','JPEG'),('.webp','WEBP')]:
            raw=examples.picture(fmt);out,_,_=policy.export(raw,ext,{'rectangles':[[5,5,70,45]]})
            with self.assertRaises(engine.Rejected):policy.verify(out+b'PRIVATE TRAILING',ext,{'rectangles':[[5,5,70,45]]},raw)

    def test_odf_default_containers_are_real_odf_and_reopen(self):
        for ext,kind,raw in [('.odt','word',examples.word()),('.ods','excel',examples.excel()),('.odp','slides',examples.slides())]:
            original=policy.native_odf(raw,ext);out,r,actual=policy.export(original,ext,examples.plan(kind));self.assertEqual(actual,ext)
            with ZipFile(io.BytesIO(out))as z:
                self.assertEqual(z.read('mimetype').decode(),policy.compat.ODF[ext]);self.assertNotIn(examples.SECRET,z.read('content.xml').decode())
                self.assertEqual(set(z.namelist()),{'mimetype','content.xml','styles.xml','META-INF/manifest.xml'})
            self.assertTrue(r['checks']['odf_reopened'])

    def test_xlsm_is_macro_container_without_vba(self):
        raw=policy.xlsm_container(examples.excel());out,_,ext=policy.export(raw,'.xlsm',examples.plan('excel'))
        self.assertEqual(ext,'.xlsm')
        with ZipFile(io.BytesIO(out))as z:
            self.assertIn(b'application/vnd.ms-excel.sheet.macroEnabled.main+xml',z.read('[Content_Types].xml'))
            self.assertFalse(any('vba'in n.lower()for n in z.namelist()))
        workbook=examples.load_workbook(io.BytesIO(out));self.assertEqual(workbook.active['C1'].value,.15);self.assertEqual(workbook.active['C1'].number_format,'0%');workbook.close()

    def test_excel_renaming_is_not_format_preservation(self):
        with self.assertRaises(engine.Rejected):policy.verify(examples.excel(),'.xlsm',examples.plan('excel'))

    def test_legacy_default_stops_before_converter_runs(self):
        with patch.object(policy.compat,'normalize',side_effect=AssertionError('must not run')):
            for ext in policy.LEGACY:
                with self.assertRaises(engine.Rejected):policy.export(b'original',ext,examples.plan(policy.category(ext)))

    def test_cli_filename_does_not_silently_authorize_conversion(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);original=root/'source.jpg';original.write_bytes(examples.picture('JPEG'));before=original.read_bytes();p=root/'plan.json';p.write_text(json.dumps({'version':1,'kind':'image','reviewed':True,'rectangles':[[5,5,70,45]]}),encoding='utf-8');out=root/'converted.png'
            command=[sys.executable,str(Path(__file__).parents[1]/'cli.py'),'redact','--input',str(original),'--plan',str(p),'--output',str(out)]
            bad=subprocess.run(command,capture_output=True);self.assertEqual(bad.returncode,2);self.assertFalse(out.exists());self.assertEqual(original.read_bytes(),before)
            good=subprocess.run([*command,'--output-format','.png'],capture_output=True);self.assertEqual(good.returncode,0,good.stdout);self.assertEqual(Image.open(out).format,'PNG')
            snapshot=out.read_bytes();again=subprocess.run([*command,'--output-format','.png'],capture_output=True);self.assertEqual(again.returncode,2);self.assertEqual(out.read_bytes(),snapshot);self.assertEqual(original.read_bytes(),before)


if __name__=='__main__':unittest.main()
