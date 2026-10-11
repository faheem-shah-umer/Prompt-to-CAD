"""Run the built CAD interface in a Windows desktop window."""

import argparse
import base64
import ctypes
import html
import logging
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".desktop-runtime"
ICON_PNG = ROOT / "frontend" / "public" / "app-icon.png"
ICON_ICO = ROOT / "frontend" / "public" / "app-icon.ico"


class DesktopBackend:
    def __init__(self, log_directory):
        self.log_directory = log_directory
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.log = None

    def start(self):
        if not (ROOT / "frontend" / "dist" / "index.html").is_file():
            raise RuntimeError("The interface has not been built. Run npm.cmd run build inside frontend first.")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with self.lock:
            if self.stopped.is_set():
                return None
            self.log = (self.log_directory / "backend.log").open("w", encoding="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, "-B", str(ROOT / "desktop-app.py"), "--backend", "--port", str(port)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        deadline = time.monotonic() + 60
        while not self.stopped.is_set():
            if self.process.poll() is not None:
                raise RuntimeError("The CAD backend stopped during startup. See backend.log in the log folder below.")
            try:
                with urlopen(url + "/api/health", timeout=1) as response:
                    if response.status == 200:
                        return url
            except (URLError, OSError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("The CAD backend did not become ready within 60 seconds.")
            self.stopped.wait(0.2)
        return None

    def stop(self):
        self.stopped.set()
        with self.lock:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
                if self.process.stdin is not None:
                    self.process.stdin.close()
            if self.log is not None:
                self.log.close()


def icon_source():
    if not ICON_PNG.is_file():
        return ""
    return "data:image/png;base64," + base64.b64encode(ICON_PNG.read_bytes()).decode("ascii")


def page(title, message):
    logo = f'<img src="{icon_source()}" alt="" width="64" height="64">' if ICON_PNG.is_file() else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>
    body{{margin:0;background:#151821;color:#edf3f6;font:16px 'Segoe UI',sans-serif;
    display:grid;place-items:center;min-height:100vh}}main{{max-width:650px;padding:40px}}
    img{{object-fit:contain;margin-bottom:20px}}
    h1{{font-size:28px}}p{{line-height:1.6;white-space:pre-wrap;color:#b4c4ce}}
    </style></head><body><main>{logo}<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></main></body></html>"""


def loading_page():
    source = icon_source()
    if not source:
        return page("Prompt to CAD", "Starting the CAD engine…")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Starting Prompt to CAD</title><style>
    *{{box-sizing:border-box}}
    body{{margin:0;min-height:100vh;display:grid;place-items:center;
    background:#151821;color:#edf3f6;font:16px 'Segoe UI',sans-serif}}
    main{{text-align:center;padding:40px}}
    .logo{{width:136px;height:136px;object-fit:contain;display:block;margin:0 auto 32px;
    animation:float 2.8s ease-in-out infinite}}
    h1{{margin:0 0 12px;font-size:30px;font-weight:600;letter-spacing:-.5px}}
    p{{margin:0;color:#b4c4ce;line-height:1.6}}
    .dots{{display:flex;justify-content:center;gap:8px;margin:24px auto}}
    .dots span{{width:7px;height:7px;border-radius:50%;background:#c797df;
    animation:pulse 1.4s ease-in-out infinite}}
    .dots span:nth-child(2){{animation-delay:.2s}}
    .dots span:nth-child(3){{animation-delay:.4s}}
    @keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-9px)}}}}
    @keyframes pulse{{0%,80%,100%{{opacity:.3;transform:scale(.85)}}40%{{opacity:1;transform:scale(1.1)}}}}
    @media(prefers-reduced-motion:reduce){{.logo,.dots span{{animation:none}}}}
    </style></head><body><main>
    <img class="logo" src="{source}" alt="Purple pyramid">
    <h1>Prompt to CAD</h1>
    <div role="status" aria-live="polite"><p>Starting the CAD engine…</p>
    <div class="dots" aria-hidden="true"><span></span><span></span><span></span></div></div>
    </main></body></html>"""


def run_backend(port):
    import uvicorn

    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=port, log_level="info")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.backend:
        if args.port is None:
            parser.error("The backend worker requires a port.")
        run_backend(args.port)
        return 0

    log_directory = ROOT / "tmp" / "desktop" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_directory / "desktop.log", encoding="utf-8", level=logging.INFO)
    backend = DesktopBackend(log_directory)
    try:
        if RUNTIME.is_dir():
            sys.path.insert(0, str(RUNTIME))
        try:
            import webview
        except ImportError as error:
            raise RuntimeError("Desktop dependencies are missing. Double-click Setup desktop.cmd once, then try again.") from error

        webview.settings["ALLOW_DOWNLOADS"] = True
        window = webview.create_window(
            "Prompt to CAD", html=loading_page(),
            width=1440, height=900, min_size=(1000, 650), background_color="#151821",
            text_select=True,
        )
        window.events.closed += backend.stopped.set

        def load_interface():
            try:
                url = backend.start()
                if url and not backend.stopped.is_set():
                    window.load_url(url)
            except Exception as error:
                logging.exception("Desktop backend startup failed")
                backend.stop()
                if window in webview.windows:
                    window.load_html(page("Could not start Prompt to CAD", f"{error}\n\nLogs: {log_directory}"))

        webview.start(load_interface, gui="edgechromium", storage_path=str(log_directory / "webview-profile"),
                      icon=str(ICON_ICO))
        return 0
    except Exception as error:
        logging.exception("Desktop startup failed")
        message = f"{error}\n\nLogs: {log_directory}\n\nThis desktop window needs Microsoft Edge WebView2 Runtime."
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, "Prompt to CAD", 0x10)
        elif sys.stderr:
            print(message, file=sys.stderr)
        return 1
    finally:
        backend.stop()


if __name__ == "__main__":
    raise SystemExit(main())
