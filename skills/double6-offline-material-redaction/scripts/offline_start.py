"""生成的双击入口调用此文件，使用安装时固定的Python和本机网页。"""
import sys
import desktop_launch

if __name__ == '__main__':
    from cli import doctor
    try:
        doctor()
        desktop_launch.main()
    except (ValueError, OSError):
        print('本地启动失败，请重新运行安装检查；没有处理材料。',file=sys.stderr)
        raise SystemExit(4)
