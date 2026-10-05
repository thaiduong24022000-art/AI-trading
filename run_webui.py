"""
Khoi dong bang dieu khien web.

    python run_webui.py              # mo tai http://127.0.0.1:5000
    python run_webui.py --port 8080

Server CHI lang nghe tren 127.0.0.1 - khong ai ngoai may nay vao duoc.
Day la co y: bang dieu khien co quyen chay tien trinh tren may ban, nen no
khong nen mo ra mang. Neu can xem tu xa, dung SSH tunnel chu dung doi sang
0.0.0.0 - lam vay la mo mot cong chay lenh tuy y cho ca mang LAN.
"""
import argparse
import logging
import sys
import webbrowser

from webui.app import app


def main() -> int:
    parser = argparse.ArgumentParser(description="Bang dieu khien web cho AI Trade Bot")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true", help="khong tu mo trinh duyet")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s | %(message)s")
    url = "http://127.0.0.1:%d" % args.port
    print("=" * 58)
    print("Bang dieu khien: %s" % url)
    print("Dung lai: Ctrl+C")
    print("=" * 58)

    if not args.no_browser:
        webbrowser.open(url)
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
