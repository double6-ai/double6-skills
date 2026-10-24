"""本地界面入口：服务就绪后打开浏览器。"""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import webbrowser

from engine import VERSION
from server import LocalServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true', help='供独立自动化测试使用')
    parser.add_argument('--session-file', type=Path, help='测试时显式保存本次本地地址，不含材料')
    args = parser.parse_args()
    server = LocalServer(0)
    session = {'url': server.base + '/' + server.nonce + '/', 'pid': os.getpid(), 'version': VERSION}
    try:
        if args.session_file:
            # 先写到旁边的文件，写完再换名。检查脚本一看到目标文件就读取，不能让它读到还没写完的空文件。
            if args.session_file.exists():
                raise FileExistsError(args.session_file)
            temporary = args.session_file.with_name(args.session_file.name + '.partial')
            with temporary.open('w', encoding='utf-8') as handle:
                json.dump(session, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, args.session_file)
        if sys.stdout:
            print(json.dumps(session), flush=True)
        if not args.no_browser:
            threading.Timer(0.3, lambda: webbrowser.open(session['url'])).start()
        server.serve_forever()
    finally:
        server.jobs.clear()
        server.server_close()


if __name__ == '__main__':
    main()
