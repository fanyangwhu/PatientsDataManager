# -*- coding: utf-8 -*-
"""启动入口：python run.py [--host 0.0.0.0] [--port 5000]"""
import argparse
import socket
import sys
import os
import webbrowser
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))



def _fix_windows_console():
    """让中文提示在 Windows 命令行里正常显示；失败就保持默认，不影响功能"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        return
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


_fix_windows_console()

from app import create_app, BASE_DIR, DATA_DIR  # noqa: E402


def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    ips.discard('127.0.0.1')
    return sorted(ips)


def main():
    parser = argparse.ArgumentParser(description='患者临床信息管理系统')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址，默认 0.0.0.0（允许局域网访问）')
    parser.add_argument('--port', type=int, default=5000, help='端口，默认 5000')
    parser.add_argument('--local-only', action='store_true', help='仅本机访问（127.0.0.1）')
    parser.add_argument('--open', dest='open_browser', action='store_true', help='启动后自动打开浏览器')
    args = parser.parse_args()

    app = create_app()
    host = '127.0.0.1' if args.local_only else args.host

    print('=' * 62)
    print('  患者临床信息管理系统')
    print('  数据库文件：', os.path.join(DATA_DIR, 'registry.db'))
    print('  本机访问： http://127.0.0.1:%d' % args.port)
    for ip in local_ips():
        print('  局域网访问：http://%s:%d    （同科室电脑用这个地址）' % (ip, args.port))
    print('  停止服务：在本窗口按 Ctrl+C')
    print('=' * 62)

    if args.open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}')).start()

    app.run(host=host, port=args.port, debug=False, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()
