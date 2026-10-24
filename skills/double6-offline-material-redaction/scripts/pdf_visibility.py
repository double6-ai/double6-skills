"""按MuPDF实际解释顺序核对矩形裁剪和嵌套Form；不能确认可见性时停止。"""
import io
import math
import pymupdf as fitz
from pymupdf import mupdf as m
from engine import Rejected


class RectangleWalker(m.FzPathWalker2):
    def __init__(self, matrix):
        super().__init__();self.points=[];self.moves=0;self.curved=False;self.closed=False;self.matrix=matrix
        for name in ('moveto','lineto','curveto','closepath'):getattr(self,'use_virtual_'+name)()
    def point(self,x,y):
        a=self.matrix
        self.points.append((x*a.a+y*a.c+a.e,x*a.b+y*a.d+a.f))
    def moveto(self,ctx,x,y):self.moves+=1;self.point(x,y)
    def lineto(self,ctx,x,y):self.point(x,y)
    def curveto(self,ctx,*args):self.curved=True
    def closepath(self,ctx):self.closed=True
    def rectangle(self):
        points=list(self.points)
        if points and points[-1]==points[0]:points.pop()
        if self.moves!=1 or self.curved or not self.closed:return None
        # Office矩形也可能以边中点起笔；只去掉共线点，不接受回折或多轮廓。
        if len(points)>1000:return None
        for _ in range(len(points)):
            old=points[:];points=[p for i,p in enumerate(old)if p!=old[i-1]]
            if len(points)<4:return None
            filtered=[]
            for i,p in enumerate(points):
                a=points[i-1];b=points[(i+1)%len(points)]
                collinear=(a[0]==p[0]==b[0]and min(a[1],b[1])<=p[1]<=max(a[1],b[1]))or(a[1]==p[1]==b[1]and min(a[0],b[0])<=p[0]<=max(a[0],b[0]))
                if not collinear:filtered.append(p)
            points=filtered
            if points==old:break
        if len(points)!=4:return None
        if any(not math.isfinite(v)for p in points for v in p):return None
        xs=sorted(set(p[0]for p in points));ys=sorted(set(p[1]for p in points))
        if len(xs)!=2 or len(ys)!=2 or len(set(points))!=4:return None
        if any(a[0]!=b[0]and a[1]!=b[1]for a,b in zip(points,points[1:]+points[:1])):return None
        return fitz.Rect(xs[0],ys[0],xs[1],ys[1])


def rectangle(path,ctm):
    walker=RectangleWalker(ctm)
    m.fz_walk_path(m.FzPath(m.ll_fz_keep_path(path)),walker,walker.m_internal)
    return walker.rectangle()


def box(rect):return fitz.Rect(rect.x0,rect.y0,rect.x1,rect.y1)


class VisibilityDevice(m.FzDevice2):
    def __init__(self,bounds):
        super().__init__();self.clips=[fitz.Rect(bounds)];self.groups=[fitz.Rect(bounds)];self.group_alpha=[1.0];self.errors=[];self.events=0;self.clip_count=0;self.cookie=m.FzCookie()
        for name in ('clip_path','pop_clip','fill_path','stroke_path','fill_text','stroke_text','ignore_text','fill_image','fill_image_mask','clip_image_mask','clip_stroke_path','clip_text','clip_stroke_text','fill_shade','begin_mask','end_mask','begin_group','end_group','begin_tile','end_tile','begin_metatext','end_metatext'):
            getattr(self,'use_virtual_'+name)()
    def reject(self,message):
        if not self.errors:self.errors.append(message)
    def tick(self):
        self.events+=1
        if self.events>200000:
            self.reject('PDF绘制操作超出安全检查范围。');self.cookie.m_internal.abort=1
    def contains(self,bounds):
        return not bounds.is_empty and not bounds.is_infinite and (self.clips[-1]&self.groups[-1]).contains(bounds)
    def clip_path(self,ctx,path,even,ctm,scissor):
        self.tick();rect=rectangle(path,ctm);self.clip_count+=1
        if rect is None:self.reject('PDF含非矩形/旋转裁剪路径，当前不能证明全部内容可见，原生路线停止。');rect=fitz.Rect()
        self.clips.append(self.clips[-1]&self.groups[-1]&rect)
        if len(self.clips)>128:self.reject('PDF裁剪嵌套超出安全范围。');self.cookie.m_internal.abort=1
    def pop_clip(self,ctx):
        if len(self.clips)<2:self.reject('PDF裁剪栈不一致，原生路线停止。')
        else:self.clips.pop()
    def fill_text(self,ctx,text,ctm,cs,color,alpha,params):
        self.tick()
        if alpha*self.group_alpha[-1]<.999 or not self.contains(box(m.ll_fz_bound_text(text,None,ctm))):self.reject('PDF文字被裁剪或透明隐藏，原生路线停止。')
    def stroke_text(self,ctx,text,stroke,ctm,cs,color,alpha,params):
        self.tick()
        if alpha*self.group_alpha[-1]<.999 or not self.contains(box(m.ll_fz_bound_text(text,stroke,ctm))):self.reject('PDF文字被裁剪或透明隐藏，原生路线停止。')
    def ignore_text(self,ctx,text,ctm):self.reject('PDF含不可见文字，原生路线停止。')
    def fill_image(self,ctx,image,ctm,alpha,params):
        self.tick();bounds=box(m.ll_fz_transform_rect(m.fz_unit_rect,ctm))
        if alpha*self.group_alpha[-1]<.999 or not self.contains(bounds):self.reject('PDF图片被裁剪或透明隐藏，可能保留原像素，原生路线停止。')
    def fill_path(self,ctx,path,even,ctm,cs,color,alpha,params):
        self.tick();bounds=box(m.ll_fz_bound_path(path,None,ctm))
        if bounds.is_empty:return
        if alpha<.999:self.reject('PDF含透明矢量绘制，原生路线停止。')
        if not self.contains(bounds):
            # 只允许矩形背景覆盖整个裁剪区，或最多0.05pt的Office边缘舍入；文字/图片无此容差。
            rect=rectangle(path,ctm)
            effective=self.clips[-1]&self.groups[-1]
            if rect is None or not (rect.contains(effective)or(effective+(-.05,-.05,.05,.05)).contains(rect)):self.reject('PDF矢量内容被裁剪，原生路线停止。')
    def stroke_path(self,ctx,path,stroke,ctm,cs,color,alpha,params):
        self.tick();bounds=box(m.ll_fz_bound_path(path,stroke,ctm))
        if not bounds.is_empty and(alpha*self.group_alpha[-1]<.999 or not self.contains(bounds)):self.reject('PDF描边内容被裁剪或透明隐藏，原生路线停止。')
    def begin_group(self,ctx,area,cs,isolated,knockout,blendmode,alpha):
        self.groups.append(self.groups[-1]&box(area));self.group_alpha.append(self.group_alpha[-1]*alpha)
        if blendmode!=0 or alpha<.999:self.reject('PDF透明/混合组尚不能安全处理，原生路线停止。')
    def end_group(self,ctx):
        if len(self.groups)<2:self.reject('PDF混合组栈不一致，原生路线停止。')
        else:self.groups.pop();self.group_alpha.pop()
    def begin_metatext(self,ctx,kind,text):self.reject('PDF含替代文字载体，原生路线停止。')
    def end_metatext(self,ctx):pass
    def begin_tile(self,ctx,*args):self.reject('PDF图案载体尚不能安全处理，原生路线停止。');return 0
    def end_tile(self,ctx):pass
    def fill_shade(self,ctx,*args):self.reject('PDF渐变载体尚不能安全处理，原生路线停止。')
    def fill_image_mask(self,ctx,*args):self.reject('PDF含图片遮罩，原生路线停止。')
    def clip_image_mask(self,ctx,*args):self.reject('PDF含图片遮罩，原生路线停止。');self.clips.append(fitz.Rect())
    def clip_stroke_path(self,ctx,*args):self.reject('PDF描边裁剪尚不能安全处理，原生路线停止。');self.clips.append(fitz.Rect())
    def clip_text(self,ctx,*args):self.reject('PDF文字裁剪尚不能安全处理，原生路线停止。');self.clips.append(fitz.Rect())
    def clip_stroke_text(self,ctx,*args):self.reject('PDF文字裁剪尚不能安全处理，原生路线停止。');self.clips.append(fitz.Rect())
    def begin_mask(self,ctx,*args):self.reject('PDF含软遮罩，原生路线停止。')
    def end_mask(self,ctx,*args):self.clips.append(fitz.Rect())


def validate(page):
    rotation=page.rotation
    try:
        if rotation:page.set_rotation(0)
        device=VisibilityDevice(page.rect)
        m.fz_run_page_contents(m.FzPage(page.this),device,m.FzMatrix(),device.cookie)
        m.fz_close_device(device)
        if len(device.groups)!=1:device.reject('PDF混合组未完整结束，原生路线停止。')
        if len(device.clips)!=1:device.reject('PDF裁剪栈未完整结束，原生路线停止。')
        if device.errors:raise Rejected(device.errors[0])
        return {'paint_events':device.events,'verified_rectangle_clips':device.clip_count}
    except Rejected:raise
    except Exception as exc:raise Rejected('PDF实际裁剪/绘制可见性检查未完成，原生路线停止。')from exc
    finally:
        if rotation:page.set_rotation(rotation)


def check_used_xobjects(data):
    """新副本不保留未实际调用的Form/图片资源；递归和循环均有界。"""
    from pypdf import PdfReader
    from pypdf.generic import ContentStream
    reader=PdfReader(io.BytesIO(data));seen=set()
    def walk(stream,resources,chain,depth):
        if depth>32:raise Rejected('PDF资源嵌套超出复检范围。')
        content=ContentStream(stream,reader)if stream is not None else None
        used={str(args[0])for args,op in content.operations if op==b'Do'}if content is not None else set()
        if hasattr(resources,'get_object'):resources=resources.get_object()
        if set(resources)-{'/ExtGState','/ColorSpace','/Pattern','/Shading','/XObject','/Font','/ProcSet','/Properties'}:raise Rejected('PDF资源字典含未知私有载体。')
        objects=resources.get('/XObject',{})
        if hasattr(objects,'get_object'):objects=objects.get_object()
        if set(objects)!=used:raise Rejected('PDF副本含未使用或缺失的Form/图片资源。')
        for name in used:
            ref=objects[name];obj=ref.get_object();identity=(getattr(ref,'idnum',id(obj)),getattr(ref,'generation',0))
            if identity in chain:raise Rejected('PDF资源出现循环。')
            if obj.get('/Subtype')=='/Form':
                group=obj.get('/Group')
                if hasattr(group,'get_object'):group=group.get_object()
                if group is not None and set(group)-{'/Type','/S','/CS','/I','/K'}:raise Rejected('PDF混合组含未知私有或元数据字段，原生路线停止。')
                walk(obj,obj.get('/Resources',resources),chain|{identity},depth+1)
            elif obj.get('/Subtype')!='/Image':raise Rejected('PDF副本含未支持的资源类型。')
    for page in reader.pages:
        group=page.get('/Group')
        if hasattr(group,'get_object'):group=group.get_object()
        if group is not None and set(group)-{'/Type','/S','/CS','/I','/K'}:raise Rejected('PDF页面混合组含未知私有或元数据字段，原生路线停止。')
        walk(page.get_contents(),page.get('/Resources',{}),set(),0)


def drawing_rectangle(drawing):
    items=drawing.get('items',[])
    if len(items)==1 and items[0][0]=='re':return items[0][1]
    if not items or any(item[0]!='l'for item in items):return None
    points=[items[0][1]]
    for item in items:
        if points[-1]!=item[1]:return None
        points.append(item[2])
    if points[-1]!=points[0]:return None
    walker=RectangleWalker(m.FzMatrix());walker.points=[(p.x,p.y)for p in points];walker.moves=1;walker.closed=True
    return walker.rectangle()


def redaction_graphics(page,boxes):
    """背景矩形可保留；复杂矢量若只选中一部分则停止，防止盖住后仍可恢复。"""
    for drawing in page.get_drawings():
        rect=fitz.Rect(drawing['rect']);width=(drawing.get('width')or 0)/2
        bounds=rect+(-width,-width,width,width)
        touched=[box for box in boxes if box.intersects(bounds)]
        if not touched or any(box.contains(bounds)for box in touched):continue
        items=drawing['items']
        if drawing.get('fill')is not None:
            if drawing_rectangle(drawing)is not None and drawing.get('color')is None:continue
            raise Rejected('框选只覆盖部分复杂矢量内容，请调整范围；未保留被盖住的原路径。')
        segments=[]
        for item in items:
            if item[0]=='l':segments.append((item[1],item[2]))
            elif item[0]=='re':
                r=item[1];segments.extend([(r.tl,r.tr),(r.tr,r.br),(r.br,r.bl),(r.bl,r.tl)])
            else:raise Rejected('框选与复杂描边交叠，当前不能安全分割，原生路线停止。')
        for a,b in segments:
            edge=fitz.Rect(min(a.x,b.x),min(a.y,b.y),max(a.x,b.x),max(a.y,b.y))+(-width-.01,-width-.01,width+.01,width+.01)
            if any(edge.intersects(box)for box in touched):raise Rejected('框选切到部分描边，请在预览调整；未保留遮盖下的原路径。')


def white_text_visible(page,span):
    """白字仅在最近的实色深色矩形背景上允许；复杂背景不作猜测。"""
    drawings={d['seqno']:d for d in page.get_drawings()};log=page.get_bboxlog();seq=span.get('seqno',-1)
    for char in span['chars']:
        if not chr(char[0]).strip():continue
        rect=fitz.Rect(char[3]);last=None
        for n,(kind,bounds)in enumerate(log[:seq]):
            if fitz.Rect(bounds).intersects(rect):last=(n,kind)
        if last is None:return False
        drawing=drawings.get(last[0]);items=drawing.get('items',[])if drawing else []
        background=drawing_rectangle(drawing)if drawing else None
        if last[1]!='fill-path'or background is None or not background.contains(rect):return False
        color=drawing.get('fill');opacity=drawing.get('fill_opacity',1)
        if not color or opacity<.999:return False
        channels=[c/12.92 if c<=.04045 else((c+.055)/1.055)**2.4 for c in color];luminance=sum(x*y for x,y in zip(channels,(.2126,.7152,.0722)))
        if 1.05/(luminance+.05)<4.5:return False
    return True


# 非绘制载体不随页面复制；未知的XObject私有字段按不支持处理。
OBJECT_METADATA={'Metadata','PieceInfo','LastModified'}
FORM_KEYS={'Type','Subtype','FormType','BBox','Matrix','Resources','Group','Name','Length','Filter','DecodeParms','StructParent','StructParents'}
IMAGE_KEYS={'Type','Subtype','Width','Height','ColorSpace','BitsPerComponent','Intent','ImageMask','Mask','Decode','Interpolate','Alternates','SMask','SMaskInData','Name','StructParent','ID','OPI','Length','Filter','DecodeParms'}


def check_object_carriers(doc,clean=False):
    for xref in range(1,doc.xref_length()):
        keys=set(doc.xref_get_keys(xref))
        if not keys:continue
        subtype=doc.xref_get_key(xref,'Subtype')[1]
        if subtype in {'/Form','/Image'}:
            allowed=FORM_KEYS if subtype=='/Form'else IMAGE_KEYS
            unknown=keys-allowed-OBJECT_METADATA
            if unknown:raise Rejected('PDF绘制对象含未支持的私有字段，原生路线停止。')
            if subtype=='/Image'and keys&{'Alternates','OPI'}:raise Rejected('PDF图片含替代/印前隐藏载体，原生路线停止。')
        for key in keys&OBJECT_METADATA:
            if doc.xref_get_key(xref,key)[0]=='null':continue
            if not clean:raise Rejected('PDF副本仍含对象级元数据或私有历史。')
            doc.xref_set_key(xref,key,'null')
