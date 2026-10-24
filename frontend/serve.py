"""Static dev server for the frontend: python frontend/serve.py [port]

Python's http.server serves .js as text/plain on many Windows machines, which
browsers refuse to run as ES modules; this registers the right type first.
"""

import functools
import http.server
import mimetypes
import sys
from pathlib import Path

mimetypes.add_type("text/javascript", ".js")

port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
handler = functools.partial(
    http.server.SimpleHTTPRequestHandler, directory=str(Path(__file__).resolve().parent)
)
with http.server.ThreadingHTTPServer(("0.0.0.0", port), handler) as server:
    print(f"Frontend on http://localhost:{port}/auth.html?mock=1&debug=1")
    server.serve_forever()
