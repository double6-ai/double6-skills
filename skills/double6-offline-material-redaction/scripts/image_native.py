"""图片保持原编码格式；JPEG明确记录有损重编码容差。"""
import io
import struct
from PIL import Image, ImageChops, ImageStat
import engine

EXTENSIONS = {'.png':'PNG', '.jpg':'JPEG', '.jpeg':'JPEG', '.webp':'WEBP'}


def image_format(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in EXTENSIONS.values():
            raise engine.Rejected('图片编码不在支持范围。')
        return image.format


def container_clean(data, fmt):
    if fmt == 'PNG':
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            return False
        pos=8
        while pos+12 <= len(data):
            n=int.from_bytes(data[pos:pos+4],'big');tag=data[pos+4:pos+8]
            if tag not in {b'IHDR',b'IDAT',b'IEND'} or n>engine.MAX_BYTES:return False
            pos+=12+n
            if tag==b'IEND':return pos==len(data)
        return False
    if fmt == 'WEBP':
        if not data.startswith(b'RIFF') or data[8:12]!=b'WEBP' or int.from_bytes(data[4:8],'little')+8!=len(data):return False
        pos=12
        while pos+8<=len(data):
            tag=data[pos:pos+4];n=int.from_bytes(data[pos+4:pos+8],'little')
            if tag!=b'VP8L':return False
            pos+=8+n+(n%2)
        return pos==len(data)
    if not data.startswith(b'\xff\xd8'):return False
    pos=2
    while pos+4<=len(data):
        if data[pos]!=255:return False
        tag=data[pos+1];n=int.from_bytes(data[pos+2:pos+4],'big')
        if n<2 or pos+2+n>len(data):return False
        if tag==0xDA:
            return data.find(b'\xff\xd9',pos+2+n)==len(data)-2
        if tag not in {0xE0,0xDB,0xC0,0xC4}:return False
        if tag==0xE0 and data[pos+4:pos+9]!=b'JFIF\0':return False
        pos+=2+n
    return False


def verify(data, selected, source, expected_format=None):
    if source is None:raise engine.Rejected('图片复检需要原图。')
    original=engine.image_source(source);boxes=engine.rectangles(selected,original.size)
    fmt=image_format(data)
    if expected_format and fmt!=expected_format:raise engine.Rejected('副本编码与要求的格式不一致。')
    with Image.open(io.BytesIO(data)) as target:
        if target.size!=original.size or getattr(target,'n_frames',1)!=1:raise engine.Rejected('图片尺寸或帧数不一致。')
        allowed={'jfif','jfif_version','jfif_unit','jfif_density'} if fmt=='JPEG' else {'loop','background'} if fmt=='WEBP' else set()
        metadata_clean=not (set(target.info)-allowed) and not target.getexif() and container_clean(data,fmt)
        target=target.convert('RGB')
    tolerance=8 if fmt=='JPEG' else 0
    solid=all(max(channel[1] for channel in target.crop(box).getextrema())<=tolerance for box in boxes)
    delta=ImageChops.difference(original,target)
    for box in boxes:delta.paste((0,0,0),box)
    outside=delta.getbbox() is None
    if fmt=='JPEG':outside=max(channel[1]for channel in delta.getextrema())<=8 and max(ImageStat.Stat(delta).rms)<=1.5
    checks={'metadata_removed':bool(metadata_clean),'selected_regions_solid':solid,
            'outside_pixels_within_jpeg_tolerance' if fmt=='JPEG' else 'outside_pixels_preserved':outside}
    if not all(checks.values()):raise engine.Rejected('图片实际编码、元数据、遮盖或框外复检失败。')
    return {'checks':checks,'output_sha256':engine.digest(data),'format':fmt.lower(),
            'jpeg_reencoded':fmt=='JPEG','scope':'所选区域已覆盖；JPEG质量100重编码，框外每通道最大误差8、均方根误差不超过1.5。' if fmt=='JPEG' else '框选实色覆盖，框外像素一致；仅检查已选范围。'}


def export(data, selected, output_format=None):
    source=engine.image_source(data);boxes=engine.rectangles(selected,source.size)
    fmt=output_format or image_format(data)
    if fmt not in EXTENSIONS.values():raise engine.Rejected('输出图片格式无效。')
    target=source.copy()
    for box in boxes:target.paste((0,0,0),box)
    fresh=Image.frombytes('RGB',target.size,target.tobytes());dest=io.BytesIO()
    options={'quality':100,'subsampling':0}if fmt=='JPEG'else{'lossless':True,'exact':True}if fmt=='WEBP'else{}
    fresh.save(dest,format=fmt,**options);out=dest.getvalue()
    if len(out)>engine.MAX_BYTES:raise engine.Rejected('副本超过20MB，请缩小材料范围。')
    report=verify(out,selected,data,fmt);report.update(version=engine.VERSION,regions=len(boxes),sha256=engine.digest(out))
    return out,report
