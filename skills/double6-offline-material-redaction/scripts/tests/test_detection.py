"""自动检测、OCR 定位和勾选语义的合成回归，不读取真实材料。"""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.request

from PIL import Image

SCRIPTS = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPTS))
import detection
import engine
import formats
import local_ocr
import pdf_preserve
import server


def client_probe(expression):
    """运行真实客户端的纯计划计算，避免复制实现来证明实现。"""
    harness = r'''
const fs=require('fs'), vm=require('vm');
const elements=new Map();
const element=()=>({value:'',hidden:true,checked:false,disabled:false,classList:{toggle(){},add(){}},setAttribute(){},removeAttribute(){},hasAttribute(){return false},querySelectorAll(){return []},getContext(){return {}},addEventListener(){}});
const context={document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)}},window:{}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
console.log(vm.runInContext(process.argv[2],context));
'''
    output = subprocess.check_output([shutil.which('node'), '-e', harness, str(SCRIPTS/'web/app.js'), expression], text=True)
    return json.loads(output)


class EntityTests(unittest.TestCase):
    def test_types_values_and_business_numbers(self):
        text = '姓名：张伟明\n电话：13800000000\n邮箱：demo@example.invalid\n地址：上海市浦东新区示例路123号\n公司名称：星河测试有限公司\n身份证号：11010519491231002X\n银行卡号：4111111111111111\n护照号：E12345678\n学号：S20260123\n出生日期：1990-01-02\n订单号13800000001\n业务120条，完成率95%'
        items = detection.text_detection(text)['candidates']
        by_type = {item['type']:item['text'] for item in items}
        self.assertEqual(set(by_type),set(detection.TYPES))
        self.assertEqual(by_type['id'],'11010519491231002X')
        self.assertEqual(by_type['bank'],'4111111111111111')
        self.assertNotIn('13800000001',[item['text'] for item in items])
        self.assertNotIn('120',[item['text'] for item in items])

    def test_utf16_emoji_fullwidth_and_repeated_value(self):
        text = '😀姓名：张伟明\n张伟明来访\n手机：１３８００００００００'
        items = detection.text_detection(text)['candidates']
        name = next(item for item in items if item['type']=='name')
        self.assertEqual(len(name['spans']),2)
        encoded = text.encode('utf-16-le')
        for span in name['spans']:
            self.assertEqual(encoded[span['start']*2:span['end']*2].decode('utf-16-le'),'张伟明')
        self.assertEqual(next(item for item in items if item['type']=='phone')['text'],'１３８００００００００')

    def test_scan_labels_without_colon_and_address_structure(self):
        result=detection.text_detection('姓名 张伟明\n联系人李小明\n寄送至上海市浦东新区示例路123号')
        values={item['text'] for item in result['candidates']}
        self.assertIn('张伟明',values);self.assertIn('李小明',values)
        self.assertTrue(any(item['type']=='address' for item in result['candidates']))

    def test_plain_business_text_is_not_sensitive(self):
        self.assertEqual(detection.text_detection('整理120条反馈，完成率95%，订单号13800000001。')['candidates'],[])

    def test_limit_reported(self):
        result=detection.text_detection('\n'.join(f'u{i}@example.invalid' for i in range(230)))
        self.assertEqual(len(result['candidates']),200); self.assertTrue(result['truncated'])


class GeometryTests(unittest.TestCase):
    def png(self):
        b=io.BytesIO();Image.new('RGB',(500,300),'white').save(b,format='PNG');return b.getvalue()

    def recognized(self):
        text='demo@example.invalid'
        return {'engine':'synthetic OCR','languages':['zh-Hans','en-US'],'lines':[{'text':text,'boxes':[[50+i*8,80,58+i*8,100]for i in range(len(text))]}]}

    def test_image_boxes_mask_actual_pixels(self):
        raw=self.png()
        with patch.object(local_ocr,'recognize',return_value=self.recognized()): result=detection.page_detection(raw,'image')
        item=result['candidates'][0];self.assertEqual(item['type'],'email')
        output,_=engine.export_image(raw,item['rectangles'])
        image=Image.open(io.BytesIO(output));self.assertEqual(image.getpixel((70,90)),(0,0,0));self.assertEqual(image.getpixel((10,10)),(255,255,255))

    def test_ocr_failure_is_partial_and_does_not_leak_exception(self):
        with patch.object(local_ocr,'recognize',side_effect=local_ocr.OcrUnavailable('本地 OCR 不可用')):
            result=detection.page_detection(self.png(),'image')
        self.assertEqual(result['status'],'partial');self.assertTrue(result['warnings']);self.assertEqual(result['candidates'],[])

    def test_english_only_is_partial(self):
        value=self.recognized();value['languages']=['eng']
        with patch.object(local_ocr,'recognize',return_value=value):result=detection.page_detection(self.png(),'image')
        self.assertEqual(result['status'],'partial');self.assertIn('中文',result['warnings'][0])

    def make_pdf(self,rotation=0,unit=None):
        f=pdf_preserve.backend();d=f.open();p=d.new_page(width=350,height=230)
        p.insert_text((30,60),'demo@example.invalid',fontsize=14)
        p.insert_text((30,160),'KEEP BUSINESS 120',fontsize=14)
        if unit:d.xref_set_key(p.xref,'UserUnit',str(unit))
        p.set_rotation(rotation);raw=d.tobytes();d.close();return raw

    def test_pdf_coordinates_rotation_and_userunit_roundtrip(self):
        for rotation,unit in [(0,None),(90,None),(270,None)]:
            with self.subTest(rotation=rotation,unit=unit):
                raw=self.make_pdf(rotation,unit)
                with patch.object(local_ocr,'recognize',side_effect=local_ocr.OcrUnavailable('本例仅验证文字层')):
                    result=detection.page_detection(raw,'pdf')
                item=next(item for item in result['candidates'] if item['type']=='email')
                self.assertTrue(item.get('selectable',True))
                plan={'reviewed_pages':[1],'pages':[{'page':1,'rectangles':item['rectangles']}],'keep':['KEEP BUSINESS 120']}
                out=formats.export(raw,'pdf',plan)
                self.assertTrue(all(formats.verify(out,'pdf',plan,raw)['checks'].values()))
                with pdf_preserve.backend().open(stream=out,filetype='pdf') as d:
                    self.assertNotIn('demo@example.invalid',d[0].get_text());self.assertIn('KEEP BUSINESS 120',d[0].get_text())

    def test_nonstandard_user_unit_keeps_pixel_safety_gate(self):
        raw=self.make_pdf(270,2)
        with patch.object(local_ocr,'recognize',side_effect=local_ocr.OcrUnavailable('仅验证文字层')):
            result=detection.page_detection(raw,'pdf')
        item=result['candidates'][0]
        # 独立计算 PDFium 预览位置，不能仅拿检测器自己的坐标函数验证自己。
        with pdf_preserve.backend().open(stream=raw,filetype='pdf') as doc:
            p=doc[0];r=p.search_for('demo@example.invalid')[0]
            original=pdf_preserve.backend().Rect(r.x0/2,r.y0/2,r.x1/2,r.y1/2)*p.rotation_matrix
            box=item['rectangles'][0]
            self.assertLessEqual(box[0],original.x0*2);self.assertGreaterEqual(box[2],original.x1*2)
        with self.assertRaises(engine.Rejected):
            formats.export(raw,'pdf',{'reviewed_pages':[1],'pages':[{'page':1,'rectangles':item['rectangles']}]})

    def test_image_page_detected_when_pdf_has_no_text(self):
        f=pdf_preserve.backend();d=f.open();p=d.new_page(width=250,height=150);p.insert_image(p.rect,stream=self.png());raw=d.tobytes();d.close()
        with patch.object(local_ocr,'recognize',return_value=self.recognized()):result=detection.page_detection(raw,'pdf')
        self.assertTrue(result['candidates']);self.assertEqual(result['candidates'][0]['source'],'ocr')
        out=formats.export(raw,'pdf',{'reviewed_pages':[1],'pages':[{'page':1,'rectangles':result['candidates'][0]['rectangles']}]})
        self.assertTrue(out.startswith(b'%PDF'))

    def test_out_of_range_page_rejected(self):
        for page in [0,-1,2,True]:
            with self.assertRaises(engine.Rejected):detection.page_detection(self.make_pdf(),'pdf',page)


class TesseractAdapterTests(unittest.TestCase):
    def test_tsv_words_keep_full_bounds_and_scale_back(self):
        tsv='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t200\t30\t92\tdemo@example.invalid\n'
        fake=subprocess.CompletedProcess([],0,stdout=tsv.encode(),stderr=b'')
        with patch.object(local_ocr,'_tesseract',return_value='tesseract'),patch.object(subprocess,'run',return_value=fake) as run:
            lines,languages=local_ocr._tess(b'PNG',(1000,600),(500,300),{'languages':['chi_sim','eng']})
        self.assertEqual(lines[0]['text'],'demo@example.invalid')
        self.assertEqual(lines[0]['boxes'][0],[20,40,420,100])
        self.assertEqual(run.call_args.kwargs['input'],b'PNG')
        self.assertNotIn('shell',run.call_args.kwargs)

    def test_external_failure_returns_generic_error(self):
        with patch.object(local_ocr,'_tesseract',return_value='tesseract'),patch.object(subprocess,'run',side_effect=subprocess.CalledProcessError(1,[],stderr=b'PRIVATE_TEST')):
            with self.assertRaises(local_ocr.OcrUnavailable) as caught:
                local_ocr._tess(b'PNG',(100,100),(100,100),{'languages':['eng']})
        self.assertNotIn('PRIVATE_TEST',str(caught.exception))


@unittest.skipUnless(shutil.which('node'),'客户端行为回归需要 Node.js')
class ClientTests(unittest.TestCase):
    def test_only_selected_and_manual_terms_export(self):
        result=client_probe("candidates=[{id:'a',source:'text',text:'甲'},{id:'b',source:'text',text:'乙'}];selectedCandidates=new Set(['a']);$('terms').value=encodeTerm('跨行\\n原文');JSON.stringify(exportTerms())")
        self.assertEqual(result,['甲','跨行\n原文'])

    def test_page_toggle_preserves_manual_regions_and_other_pages(self):
        result=client_probe("job={kind:'pdf'};pdfBoxes={1:[[1,1,20,20]]};currentPage=2;boxes=[[5,5,30,30]];candidates=[{id:'a',page:1,rectangles:[[40,40,80,80]]},{id:'b',page:2,rectangles:[[50,50,90,90]]}];selectedCandidates=new Set(['b']);JSON.stringify(exportPages())")
        self.assertEqual(result,[{'page':1,'rectangles':[[1,1,20,20]]},{'page':2,'rectangles':[[5,5,30,30],[50,50,90,90]]}])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.server=server.LocalServer(0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=self.server.base+'/'+self.server.nonce+'/'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def post(self,path,data,headers=None):
        if isinstance(data,dict):data=json.dumps(data).encode()
        req=urllib.request.Request(self.url+path,data=data,headers={'Origin':self.server.base,**(headers or {})})
        with urllib.request.urlopen(req) as response:return json.loads(response.read())

    def test_import_text_detection_and_export_only_confirmed(self):
        raw='姓名：张伟明\n电话：13800000000\n保留120'.encode()
        job=self.post('api/import',raw,{'X-File-Kind':'text','X-File-Extension':'.txt'})
        self.assertEqual({x['type'] for x in job['detection']['candidates']},{'name','phone'})
        result=self.post('api/export',{'id':job['id'],'reviewed':True,'terms':['13800000000'],'keep':['张伟明','保留120']})
        with urllib.request.urlopen(self.url+result['download']) as response:out=response.read().decode()
        self.assertIn('张伟明',out);self.assertNotIn('13800000000',out)

    def test_detection_cached_and_cleared_with_session(self):
        b=io.BytesIO();Image.new('RGB',(50,50),'white').save(b,format='PNG')
        job=self.post('api/import',b.getvalue(),{'X-File-Kind':'image','X-File-Extension':'.png'})
        with patch.object(detection,'page_detection',return_value={'status':'complete','candidates':[],'warnings':[]}) as mocked:
            self.post('api/detect',{'id':job['id'],'page':1});self.post('api/detect',{'id':job['id'],'page':1})
            self.assertEqual(mocked.call_count,1)
        self.post('api/clear',{})
        self.assertEqual(self.server.jobs,{})


if __name__=='__main__': unittest.main()
