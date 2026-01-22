import http.server
import socketserver
import os

PORT = 8010
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, out)

class Handler(http.server.SimpleHTTPRequestHandler)
    def __init__(self, args, kwargs)
        super().__init__(args, directory=OUT_DIR, kwargs)

with socketserver.TCPServer((, PORT), Handler) as httpd
    print(fServing OUT on httplocalhost{PORT}dashboard_tv_heatedrivalry.html)
    httpd.serve_forever()
