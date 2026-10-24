"""仅绑定回环地址的原型；文件在内存中处理，不记录原文。"""
import argparse
import io
import json
import secrets
import threading
import time
import urllib.parse
import formats
import compat
import output_policy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from engine import VERSION, MAX_BYTES, Rejected, digest, export_docx, export_image, image_source, inspect_docx, png_bytes

ASSETS = Path(__file__).parent / "web"


class LocalServer(HTTPServer):
    # 单人原型顺序处理请求，避免多个导出同时修改 XML 序列化配置。
    def __init__(self, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.nonce = secrets.token_urlsafe(24)
        self.jobs = {}
        self.lock = threading.Lock()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalRedaction/" + VERSION

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        pass

    def send(self, status, payload, mime="application/json; charset=utf-8", attachment=None):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="material-redacted' + Path(attachment).suffix + '"; filename*=UTF-8\'\'' + urllib.parse.quote(attachment, safe=''))
        self.end_headers()
        self.wfile.write(payload)

    def route(self, mutation=False):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            raise Rejected("请求地址无效。")
        prefix = "/" + self.server.nonce + "/"
        if not self.path.startswith(prefix) or "?" in self.path:
            raise Rejected("本地会话已失效，请使用启动时给出的地址。")
        if mutation and self.headers.get("Origin") != self.server.base:
            raise Rejected("只接受本地页面发起的处理请求。")
        return self.path[len(prefix):]

    def job(self, value):
        with self.server.lock:
            now = time.monotonic()
            self.server.jobs = {k: v for k, v in self.server.jobs.items() if now - v["created"] < 1800}
            job = self.server.jobs.get(value)
        if not job:
            raise Rejected("文件会话已过期，请重新选择文件。")
        return job

    def do_GET(self):
        try:
            path = self.route()
            files = {"": ("index.html", "text/html; charset=utf-8"), "app.js": ("app.js", "text/javascript; charset=utf-8"), "style.css": ("style.css", "text/css; charset=utf-8")}
            if path in files:
                name, mime = files[path]
                content=(ASSETS/name).read_bytes()
                if name=='index.html':
                    inputs=['.png','.jpg','.jpeg','.webp','.docx',*formats.EXTENSIONS,*compat.KINDS]
                    content=content.replace(b'__VERSION__',VERSION.encode()).replace(b'__SUPPORTED_INPUTS__',', '.join(inputs).encode())
                return self.send(200, content, mime)
            parts = path.split("/")
            if len(parts) == 3 and parts[0] == "file":
                job = self.job(parts[1])
                if parts[2] == "preview" and job["kind"] == "image":
                    return self.send(200, job["preview"], "image/png")
                if parts[2] == "output" and job.get("output"):
                    return self.send(200, job['output'], output_policy.mime(job['output_ext']), job['output_name'])
            if len(parts)==4 and parts[0]=="file" and parts[2]=="page":
                job=self.job(parts[1])
                if job["kind"]=="pdf" and parts[3].isdigit():
                    return self.send(200,png_bytes(formats.pdf_image(job["data"],int(parts[3])-1)),"image/png")
            self.send(404, {"error": "页面不存在。"})
        except Rejected as exc:
            self.send(400, {"error": str(exc)})

    def do_POST(self):
        try:
            path = self.route(mutation=True)
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise Rejected("文件长度无效。")
            if not 0 < size <= MAX_BYTES:
                raise Rejected("请选择不超过 20 MB 的文件。")
            data = self.rfile.read(size)
            if len(data) != size:
                raise Rejected("文件传输不完整。")
            if path == "api/import":
                kind = self.headers.get("X-File-Kind")
                original_sha = digest(data)
                original_data=data
                ext=self.headers.get("X-File-Extension", "").lower()
                if output_policy.category(ext)!=kind:raise Rejected('文件类型与扩展名不符。')
                if ext in output_policy.LEGACY and self.headers.get('X-Convert-To')!=output_policy.LEGACY[ext]:raise Rejected('旧格式预览需要先明确选择转换；未调用兼容引擎。')
                if ext in compat.KINDS and kind != compat.KINDS[ext]:raise Rejected("文件类型与扩展名不符。")
                data,compatibility=compat.normalize(data,ext)
                if kind == "image":
                    im = image_source(data)
                    preview = png_bytes(im)
                    plan = {"width": im.width, "height": im.height}
                elif kind == "word":
                    preview = None
                    plan = inspect_docx(data)
                    plan.pop("blocks")
                elif kind in formats.OUTPUT and kind not in {"word","image"}:
                    preview=None;plan=formats.inspect(data,kind,self.headers.get("X-Text-Encoding")or None)
                else:
                    raise Rejected("文件格式不在当前支持范围。")
                ident = secrets.token_urlsafe(18)
                with self.server.lock:
                    # 超过容量时明确要求清空，不静默移除另一个下载会话。
                    if len(self.server.jobs) >= 4:
                        raise Rejected("本会话已载入四份材料，请先清空。")
                    self.server.jobs[ident] = {"kind": kind, "data": data, "original":original_data,"extension":ext,"original_name":urllib.parse.unquote(self.headers.get("X-File-Name","material")), "preview": preview, "created": time.monotonic(), "source_sha256": original_sha,"encoding":self.headers.get("X-Text-Encoding")or None}
                if compatibility:plan["notice"]=compatibility["notice"]+plan.get("notice", "");plan["compatibility"]=compatibility
                return self.send(200, {"id": ident, "kind": kind,"input_extension":ext,"output_options":output_policy.options(ext),"original_format_supported":ext not in output_policy.LEGACY, **plan})
            values = json.loads(data)
            if not isinstance(values, dict):
                raise Rejected("请求格式无效。")
            if path == "api/clear":
                with self.server.lock:
                    self.server.jobs.clear()
                return self.send(200, {"cleared": True})
            if path == "api/stop":
                self.server.jobs.clear()
                self.send(200, {"stopped": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == "api/snap-pdf":
                job=self.job(values.get('id'))
                if job['kind']!='pdf':raise Rejected('整字对齐只适用于PDF。')
                import pdf_preserve
                region=pdf_preserve.snap_region(job['data'],values.get('page'),values.get('rectangle'))
                return self.send(200,{'rectangle':region})
            if path == "api/invalidate":
                self.job(values.get("id")).pop("output",None)
                return self.send(200,{"invalidated":True})
            if path == "api/export":
                job = self.job(values.get("id"))
                job.pop('output',None)
                if values.get("reviewed") is not True:
                    raise Rejected("请先核对预览和补选范围。")
                values['input_encoding']=job['encoding']
                output,report,ext=output_policy.export(job['original'],job['extension'],values,values.get('output_format'))
                # 下载名不沿用原名，避免正文已处理而姓名/号码仍随文件名上传。
                job['output_name']='redacted-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(6)+ext
                report['checks']['neutral_output_filename']=True
                job['output_ext']=ext
                job["output"] = output
                return self.send(200, {"download": "file/" + values["id"] + "/output", "report": report})
            self.send(404, {"error": "接口不存在。"})
        except (Rejected, json.JSONDecodeError) as exc:
            self.send(400, {"error": str(exc)})
        except Exception:
            # 不把包含原文、文件路径或内部栈的异常发给浏览器或写入日志。
            self.send(500, {"error": "处理未完成。原文件未改动，请核对文件是否在支持范围内。"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    server = LocalServer(args.port)
    print(json.dumps({"url": server.base + "/" + server.nonce + "/", "version": VERSION, "pid_scope": "owned local loopback process"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.jobs.clear()
        server.server_close()


if __name__ == "__main__":
    main()
