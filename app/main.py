import threading
import time
import urllib.request
import webview
from server import app

def start_server():
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False, threaded=True)


def wait_for_server(url="http://127.0.0.1:5050/version", timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5):
                return True
        except Exception:
            time.sleep(0.1)
    return False


if __name__ == "__main__":
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    wait_for_server()

    webview.create_window(
        title="yt-dlp UI",
        url="http://127.0.0.1:5050",
        width=480,
        height=592,
        min_size=(480, 592),
        background_color="#0a0a0b"
    )
    webview.start()
