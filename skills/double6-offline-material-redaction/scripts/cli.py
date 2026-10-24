"""本地 skill 命令入口；原文及替换词只从本机文件读取。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import stat
import sys
import tempfile

from PIL import Image, ImageChops
import engine
import formats
import compat
import output_policy


class Failure(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def load_file(path, limit=engine.MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise Failure('只接受本地普通文件。')
        value = f.read(limit + 1)
    if len(value) > limit:
        raise Failure('文件超过允许大小。')
    return value


def kind(path):
    ext = Path(path).suffix.lower()
    if ext == '.docx': return 'word'
    if ext in {'.png', '.jpg', '.jpeg', '.webp'}: return 'image'
    if ext in compat.KINDS: return compat.KINDS[ext]
    if ext in formats.EXTENSIONS: return formats.EXTENSIONS[ext]
    raise Failure('该格式尚未验证；支持范围见doctor，不对旧版/加密文件静默转换。')


def load_plan(path, expected):
    try: plan = json.loads(load_file(path, 256 * 1024).decode('utf-8-sig'))
    except (ValueError, UnicodeError, RecursionError): raise Failure('计划文件不是有效UTF-8 JSON。')
    common = {'version', 'kind', 'reviewed', 'keep', 'output_format', 'pdf_mode'}
    allowed = common | ({'terms', 'acknowledge_loss', 'clean_only'} if expected == 'word' else {'rectangles'} if expected == 'image' else {'pages','reviewed_pages','acknowledge_loss'} if expected == 'pdf' else {'terms','acknowledge_loss','clean_only','input_encoding'})
    if not isinstance(plan, dict) or set(plan) - allowed or type(plan.get('version')) is not int or plan.get('version') != 1 or plan.get('kind') != expected or plan.get('reviewed') is not True:
        raise Failure('计划需声明version=1、对应kind与reviewed=true，且不能有未知字段。')
    plan['keep'] = engine.keep_checked(plan.get('keep', []))
    if expected not in {'image','pdf'}:
        plan['terms'] = engine.terms_checked(plan.get('terms'))
        if expected in {'word','csv','tsv','excel','slides'} and plan.get('acknowledge_loss') is not True:
            raise Failure('Word计划需接受图片移除和版式重排。')
        if not plan['terms'] and plan.get('clean_only') is not True:
            raise Failure('未补选正文；仅清理隐藏内容需显式clean_only=true。')
        if plan['terms'] and plan.get('clean_only'):
            raise Failure('clean_only与正文替换词不能同时使用。')
    return plan


def write_new(path, data):
    target = Path(path).absolute()
    if target.exists() or target.is_symlink():
        raise Failure('输出已存在，未覆盖。请指定新文件。')
    # 在同一文件系统暂存，再以硬链接独占创建目标；失败不留下半成品。
    fd, name = tempfile.mkstemp(prefix='.redaction-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        try: os.link(name, target)
        except FileExistsError: raise Failure('输出已存在，未覆盖。')
        except OSError: raise Failure('当前目录不支持安全创建输出，请换本地目录。')
    finally:
        Path(name).unlink(missing_ok=True)


def doctor():
    assets = Path(__file__).parent / 'web'
    checks = {'python_runtime': (3,10) <= sys.version_info[:2] <= (3,14), 'web_assets': all((assets / n).is_file() for n in ['index.html', 'app.js', 'style.css']), 'supported_platform': sys.platform in {'darwin', 'win32'}}
    if not all(checks.values()): raise Failure('运行环境不完整或平台未纳入支持，请重新安装对应版本。', 4)
    return {'version': engine.VERSION, 'platform': platform.system(), 'machine': platform.machine(), 'python': platform.python_version(), 'self_contained': False, 'checks': checks, 'package': {'mode':'open_source','dependency_integrity':'use hash-locked bootstrap'}, 'processing_network': 'not_required', 'ocr': False, 'formats': ['PNG/JPEG/WebP','DOCX',*formats.EXTENSIONS], 'pdf_dpi':144, 'compatibility':compat.status(), 'compatibility_formats':list(compat.KINDS)}


def selftest():
    from docx import Document
    checks = {}
    d = Document();d.add_paragraph('示例姓名 保留这句业务内容');d.core_properties.author = '示例姓名'
    b = io.BytesIO();d.save(b)
    out, report = engine.export_docx(b.getvalue(), ['示例姓名'], True)
    checks['word_clean_and_keep'] = all(report['checks'].values()) and '保留这句业务内容' in engine.inspect_docx(out)['preview']
    im = Image.new('RGB', (80, 80), 'white');ex = Image.Exif();ex[270] = 'example-private';b = io.BytesIO();im.save(b, format='JPEG', exif=ex)
    out, report = engine.export_image(b.getvalue(), [[0, 0, 20, 20]])
    checks['image_mask_metadata_keep'] = all(report['checks'].values())
    with tempfile.TemporaryDirectory(prefix='redaction-selftest-') as tmp:
        target = Path(tmp) / 'result.png';write_new(target, out)
        try: write_new(target, b'should-not-overwrite')
        except Failure: checks['no_overwrite'] = target.read_bytes() == out
        else: checks['no_overwrite'] = False
    # 在本机真正加载新增格式的解析器与PDF原生库，安装自检覆盖所有适配器。
    marker='示例姓名';keep='保留这句业务内容'
    common={'terms':[marker],'acknowledge_loss':True,'keep':[keep]}
    for category in ['text','markdown','csv','tsv']:
        raw=(marker+' '+keep).encode();out=formats.export(raw,category,common);checks[category+'_roundtrip']=all(formats.verify(out,category,common)['checks'].values())
    from openpyxl import Workbook
    wb=Workbook();wb.active['A1']=marker;wb.active['B1']=keep;b=io.BytesIO();wb.save(b);out=formats.export(b.getvalue(),'excel',common);checks['excel_roundtrip']=all(formats.verify(out,'excel',common)['checks'].values())
    from pptx import Presentation
    from pptx.util import Inches
    prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6]);slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2)).text=marker+' '+keep;b=io.BytesIO();prs.save(b);out=formats.export(b.getvalue(),'slides',common);checks['slides_roundtrip']=all(formats.verify(out,'slides',common)['checks'].values())
    source=formats.make_pdf([Image.new('RGB',(80,80),'white')]);plan={'reviewed_pages':[1],'pages':[{'page':1,'rectangles':[[0,0,20,20]]}],'acknowledge_loss':True};out=formats.export(source,'pdf',plan);checks['pdf_native_render_roundtrip']=all(formats.verify(out,'pdf',plan,source)['checks'].values())
    checks.update(compat.selftest())
    if not all(checks.values()): raise Failure('自检未通过，请停止处理材料。', 4)
    return {'version': engine.VERSION, 'checks': checks, 'synthetic_only': True, 'native_office_tested': False, 'legacy_converter_tested':False}


def check_output(data, category, plan, source=None):
    if category not in {'word','image'}:
        return formats.verify(data,category,plan,source)
    if category == 'word':
        checks = engine.verify_docx(data, plan['terms'])
        text = engine.inspect_docx(data)['preview']
        keep=engine.keep_checked(plan.get('keep', []))
        if keep:checks['keep_phrases_preserved'] = all(k in text for k in keep)
    else:
        if source is None:raise Failure('图片复检需要原图。')
        return output_policy.image_native.verify(data,plan.get('rectangles'),source)
    if not all(checks.values()): raise Failure('导出复检未通过，未交付为可用副本。', 3)
    return {'checks': checks, 'not_checked':['keep_phrases_preserved']if category=='word'and not keep else [], 'output_sha256': engine.digest(data), 'scope': '仅核对计划指定内容和已支持载体；未自动确认补选完整性'}


def main():
    # 管道输出也固定为UTF-8，不能依赖Windows当前代码页。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')
    p = argparse.ArgumentParser(description='本地材料脱敏；处理过程不调用在线服务。')
    p.add_argument('--version', action='version', version=engine.VERSION)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor');sub.add_parser('selftest')
    inspect_p = sub.add_parser('inspect');inspect_p.add_argument('--input', required=True);inspect_p.add_argument('--show-preview', action='store_true');inspect_p.add_argument('--encoding',choices=['utf-8','utf-16','gb18030']);inspect_p.add_argument('--allow-conversion',action='store_true')
    redact_p = sub.add_parser('redact');redact_p.add_argument('--input', required=True);redact_p.add_argument('--plan', required=True);redact_p.add_argument('--output', required=True);redact_p.add_argument('--output-format',help='仅显式指定才转换，例如.png/.docx');redact_p.add_argument('--pdf-mode',choices=['preserve','rasterize'])
    verify_p = sub.add_parser('verify');verify_p.add_argument('--input', required=True);verify_p.add_argument('--plan', required=True);verify_p.add_argument('--source')
    gui_p = sub.add_parser('gui');gui_p.add_argument('--no-browser', action='store_true');gui_p.add_argument('--session-file')
    args = p.parse_args()
    try:
        if args.command == 'doctor': result = doctor()
        elif args.command == 'selftest': result = selftest()
        elif args.command == 'gui':
            doctor()
            import desktop_launch
            sys.argv = [sys.argv[0]] + (['--no-browser'] if args.no_browser else []) + (['--session-file', args.session_file] if args.session_file else [])
            desktop_launch.main();return 0
        elif args.command == 'inspect':
            category = kind(args.input);data = load_file(args.input)
            if Path(args.input).suffix.lower() in output_policy.LEGACY and not args.allow_conversion:raise Failure('旧格式预览需显式--allow-conversion，未调用兼容引擎。')
            data, compatibility = compat.normalize(data,Path(args.input).suffix.lower())
            if category == 'word':
                info = engine.inspect_docx(data)
                result = {'kind': category, 'characters': len(info['preview']), 'suggestion_count': len(info['suggestions']), 'removed': info['removed'], 'notice': info['notice']}
                if args.show_preview: result['preview'] = info['preview']
            elif category != 'image':
                info=formats.inspect(data,category,args.encoding);result={'kind':category,**{k:v for k,v in info.items()if k not in {'preview','suggestions'}}}
                if 'preview'in info:result['characters']=len(info['preview']);result['suggestion_count']=len(info['suggestions'])
                if args.show_preview and 'preview'in info:result['preview']=info['preview']
            else:
                im = engine.image_source(data);result = {'kind': category, 'display_width': im.width, 'display_height': im.height, 'manual_rectangles_required': True}
        elif args.command == 'redact':
            category = kind(args.input);raw = load_file(args.input);plan = load_plan(args.plan, category)
            if args.pdf_mode:plan['pdf_mode']=args.pdf_mode
            if Path(args.output).resolve() in {Path(args.input).resolve(), Path(args.plan).resolve()}:raise Failure('输出不能覆盖输入或计划文件。')
            ext=Path(args.input).suffix.lower();requested=args.output_format or plan.get('output_format')
            expected=output_policy.target(ext,requested)
            if Path(args.output).suffix.lower()!=expected:raise Failure('默认保持原格式；如需转换，请明确使用--output-format。')
            out,result,_=output_policy.export(raw,ext,plan,requested)
            compatibility=result.get('compatibility');write_new(args.output,out);result['created']=True
        else:
            ext=Path(args.input).suffix.lower()
            if ext in output_policy.LEGACY:raise Failure('verify：该旧格式尚不提供原格式副本；请检查明确转换后的实际文件。')
            category=kind(args.input);data=load_file(args.input);plan=load_plan(args.plan,category)
            source=load_file(args.source) if args.source else None
            if source is not None and Path(args.source).suffix.lower() in compat.KINDS:source=compat.normalize(source,Path(args.source).suffix.lower())[0]
            result=output_policy.verify(data,ext,plan,source)
        if args.command in {'inspect','redact'} and compatibility: result['compatibility']=compatibility
        print(json.dumps({'ok': True, **result}, ensure_ascii=False));return 0
    except (Failure, engine.Rejected) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False));return getattr(exc, 'code', 2)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        print(json.dumps({'ok': False, 'error': '本地文件、计划或运行包无效，未执行替代处理。'}, ensure_ascii=False));return 2

if __name__ == '__main__': raise SystemExit(main())
