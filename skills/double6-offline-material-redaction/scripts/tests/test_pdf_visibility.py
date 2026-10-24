"""正常办公排版裁剪、嵌套与真实隐藏载体分别检查。"""
import io,sys,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]))
import acceptance as a,engine,output_policy as policy,pdf_preserve as pdf,pdf_visibility

class VisibilityTests(unittest.TestCase):
    def rect_clip(self,data,commands):
        f=pdf.backend();d=f.open(stream=data,filetype='pdf')
        for xref in d[0].get_contents():d.update_stream(xref,b'q '+commands+b' '+d.xref_stream(xref)+b' Q')
        raw=d.tobytes();d.close();return raw
    def wrap(self,data):
        f=pdf.backend();s=f.open(stream=data,filetype='pdf');d=f.open();page=d.new_page(width=300,height=200);page.show_pdf_page(page.rect,s,0);raw=d.tobytes();d.close();s.close();return raw
    def image(self,clipped=False):
        f=pdf.backend();im=Image.new('RGB',(160,100),'white');im.paste((255,0,255),(80,0,160,100));b=io.BytesIO();im.save(b,format='PNG');d=f.open();page=d.new_page(width=300,height=200);page.insert_image(f.Rect(20,20,180,120),stream=b.getvalue());page.insert_text((20,180),a.KEEP);raw=d.tobytes();d.close()
        return self.rect_clip(raw,b'20 20 40 40 re W n')if clipped else raw
    def test_harmless_rectangular_office_clip_keeps_searchable_text(self):
        raw=self.rect_clip(a.pdf(),b'0 0 300 200 re W* n');out,r,_=policy.export(raw,'.pdf',a.pdf_plan())
        with pdf.backend().open(stream=out,filetype='pdf')as d:self.assertIn(a.KEEP,d[0].get_text());self.assertNotIn(a.SECRET,d[0].get_text())
        self.assertTrue(r['checks']['pdf_not_rasterized'])
    def test_clip_restore_does_not_apply_header_clip_to_body(self):
        f=pdf.backend();d=f.open();page=d.new_page(width=300,height=200);page.insert_text((20,35),a.SECRET);first=page.get_contents()[0];d.update_stream(first,b'q 10 150 220 45 re W n '+d.xref_stream(first)+b' Q');page.insert_text((20,120),a.KEEP);raw=d.tobytes();d.close();out,_,_=policy.export(raw,'.pdf',a.pdf_plan())
        with f.open(stream=out,filetype='pdf')as d:self.assertIn(a.KEEP,d[0].get_text())
    def test_nested_forms_preserve_business_and_remove_selected_text(self):
        raw=self.wrap(self.wrap(a.pdf()));out,_,_=policy.export(raw,'.pdf',a.pdf_plan());pdf_visibility.check_used_xobjects(out)
        with pdf.backend().open(stream=out,filetype='pdf')as d:self.assertNotIn(a.SECRET,d[0].get_text());self.assertIn(a.KEEP,d[0].get_text())
    def test_nested_image_redaction_cleans_every_image_object(self):
        raw=self.wrap(self.image());plan={'reviewed_pages':[1],'pages':[{'page':1,'rectangles':[[195,35,370,250]]}],'keep':[a.KEEP]};out,_,_=policy.export(raw,'.pdf',plan)
        with pdf.backend().open(stream=out,filetype='pdf')as d:
            count=0
            for xref in range(1,d.xref_length()):
                if d.xref_get_key(xref,'Subtype')[1]!='/Image':continue
                im=Image.open(io.BytesIO(d.extract_image(xref)['image'])).convert('RGB');count+=sum(pixel==(255,0,255)for pixel in im.getdata())
            self.assertEqual(count,0)
    def test_direct_and_nested_clipped_original_image_are_rejected(self):
        raw=self.image(True)
        for source in [raw,self.wrap(raw)]:
            with self.assertRaises(engine.Rejected):policy.export(source,'.pdf',a.pdf_plan())
    def test_even_odd_hole_and_non_rectangular_clip_rejected(self):
        for path in [b'0 0 300 200 re 10 100 150 80 re W* n',b'0 0 m 300 0 l 100 200 l h W n']:
            with self.assertRaises(engine.Rejected):policy.export(self.rect_clip(a.pdf(),path),'.pdf',a.pdf_plan())
    def test_transparent_vector_objects_are_not_silently_accepted(self):
        f=pdf.backend();d=f.open(stream=a.pdf(),filetype='pdf');d[0].draw_rect(f.Rect(200,160,250,180),color=None,fill=(0,0,0),fill_opacity=.1);raw=d.tobytes();d.close()
        with self.assertRaises(engine.Rejected):policy.export(raw,'.pdf',a.pdf_plan())

    def test_white_header_on_opaque_dark_rectangle_is_visible(self):
        f=pdf.backend();d=f.open(stream=a.pdf(),filetype='pdf');page=d[0];page.draw_rect(f.Rect(10,130,285,170),color=None,fill=(.05,.1,.3));page.insert_text((20,155),'VISIBLE WHITE HEADER',color=(1,1,1));raw=d.tobytes();d.close()
        out,_,_=policy.export(raw,'.pdf',a.pdf_plan())
        with f.open(stream=out,filetype='pdf')as d:self.assertIn('VISIBLE WHITE HEADER',d[0].get_text())
    def test_white_on_white_hidden_text_still_rejected(self):
        f=pdf.backend();d=f.open(stream=a.pdf(),filetype='pdf');d[0].insert_text((20,150),'HIDDEN',color=(1,1,1));raw=d.tobytes();d.close()
        with self.assertRaises(engine.Rejected):policy.export(raw,'.pdf',a.pdf_plan())
    def test_partial_complex_vector_cannot_be_kept_under_black_box(self):
        f=pdf.backend();d=f.open(stream=a.pdf(),filetype='pdf');page=d[0];shape=page.new_shape();shape.draw_polyline([f.Point(240,140),f.Point(275,170),f.Point(240,180)]);shape.finish(fill=(1,0,0));shape.commit();raw=d.tobytes();d.close()
        plan=a.pdf_plan();plan['pages'][0]['rectangles'].append([470,275,515,335])
        with self.assertRaises(engine.Rejected):policy.export(raw,'.pdf',plan)
    def test_whole_character_alignment_is_explicit_and_reported(self):
        f=pdf.backend();d=f.open();p=d.new_page(width=300,height=200);p.insert_text((20,45),'NAME:PRIVATE:END');p.insert_text((20,120),a.KEEP);raw=d.tobytes();char=[c for span in p.get_texttrace()for c in span['chars']if chr(c[0])=='P'][0];r=f.Rect(char[3]);d.close()
        initial=[int(r.x0*2+2),int(r.y0*2+2),int(r.x1*2-1),int(r.y1*2-1)];snapped=pdf.snap_region(raw,1,initial)
        self.assertLessEqual(snapped[0],initial[0]);self.assertGreaterEqual(snapped[2],initial[2])
        plan={'reviewed_pages':[1],'pages':[{'page':1,'rectangles':[initial]}],'keep':[a.KEEP],'snap_to_text':True}
        out,report,_=policy.export(raw,'.pdf',plan);self.assertEqual(report['effective_pages'][0]['rectangles'],[snapped]);self.assertTrue(report['checks']['outside_page_pixels_preserved'])
    def test_table_background_is_preserved_outside_selection(self):
        f=pdf.backend();d=f.open();p=d.new_page(width=300,height=200);p.draw_rect(f.Rect(10,10,290,85),color=None,fill=(.8,.9,1));p.insert_text((20,35),a.SECRET);p.insert_text((20,120),a.KEEP);raw=d.tobytes();d.close()
        out,report,_=policy.export(raw,'.pdf',a.pdf_plan());self.assertTrue(report['checks']['outside_page_pixels_preserved'])

    def test_nested_object_metadata_and_pieceinfo_are_removed(self):
        f=pdf.backend();raw=self.wrap(a.pdf());d=f.open(stream=raw,filetype='pdf');form=next(n for n in range(1,d.xref_length())if d.xref_get_key(n,'Subtype')[1]=='/Form');meta=d.get_new_xref();d.update_object(meta,'<</Type /Metadata /Subtype /XML>>');d.update_stream(meta,b'<xmp>PRIVATE_OBJECT_XML_782</xmp>');d.xref_set_key(form,'Metadata',str(meta)+' 0 R');d.xref_set_key(form,'PieceInfo','<</Private (PRIVATE_OBJECT_HISTORY_782)>>');raw=d.tobytes();d.close()
        out,r,_=policy.export(raw,'.pdf',a.pdf_plan())
        with f.open(stream=out,filetype='pdf')as d:
            all_objects=b' '.join(d.xref_object(n).encode()+(d.xref_stream(n)or b'')for n in range(1,d.xref_length()))
            self.assertNotIn(b'PRIVATE_OBJECT_XML_782',all_objects);self.assertNotIn(b'PRIVATE_OBJECT_HISTORY_782',all_objects);pdf_visibility.check_object_carriers(d)
    def test_unknown_private_form_field_and_image_alternate_rejected(self):
        f=pdf.backend()
        for source,kind,key,value in [(self.wrap(a.pdf()),'/Form','PrivateData','(PRIVATE782)'),(self.image(),'/Image','Alternates','[<</Image 1 0 R>>]')]:
            d=f.open(stream=source,filetype='pdf');xref=next(n for n in range(1,d.xref_length())if d.xref_get_key(n,'Subtype')[1]==kind);d.xref_set_key(xref,key,value);raw=d.tobytes();d.close()
            with self.assertRaises(engine.Rejected):policy.export(raw,'.pdf',a.pdf_plan())

    def test_nested_transparency_group_private_and_metadata_fields_rejected(self):
        f=pdf.backend()
        for key in ['Private','Metadata']:
            raw=self.wrap(a.pdf());d=f.open(stream=raw,filetype='pdf');xref=next(n for n in range(1,d.xref_length())if d.xref_get_key(n,'Subtype')[1]=='/Form');d.xref_set_key(xref,'Group','<</S /Transparency /CS /DeviceRGB /'+key+' (HIDDEN_GROUP_782)>>');raw=d.tobytes();d.close()
            with self.assertRaises(engine.Rejected):policy.export(raw,'.pdf',a.pdf_plan())

if __name__=='__main__':unittest.main()
