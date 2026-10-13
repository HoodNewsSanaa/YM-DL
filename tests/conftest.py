import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest


@pytest.fixture
def local_files():
    """Serve generated test media locally, without contacting outside services."""
    import contextlib
    import http.server
    import threading
    @contextlib.contextmanager
    def serve(files):
        hits = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                item = files.get(self.path)
                if item is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(item)))
                self.end_headers()
                self.wfile.write(item)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}', hits
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    return serve
