import http.server
import json
import os
import socketserver
import subprocess
import time
import requests
import webbrowser

from .logging import debug, info, warning, error
from .checker import get_missing_files

# Host IP
URL = 'http://129.16.69.36:54321'


def serve_map():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    directory = os.path.join(script_dir, "templates")
    os.chdir(directory)

    class HttpRequestHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self.coordinates = None
            super().__init__(*args, **kwargs)

        def do_GET(self):
            if self.path == '/get_coordinates':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if self.coordinates:
                    self.wfile.write(json.dumps({'coordinates': self.coordinates}).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({'coordinates': None}).encode('utf-8'))
            else:
                if self.path == '/map' or self.path == '/':
                    self.path = 'index.html'
                super().do_GET()

        def do_POST(self):
            if self.path == '/submit':
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                self.coordinates = json.loads(post_data)
                print(f"Coordinates received: {self.coordinates}")
                self.send_response(200)
                self.send_header('Content-Type', 'application/jsons')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))

    port = 8000
    max_port = 8100

    while port <= max_port:
        try:
            with socketserver.TCPServer(("", port), HttpRequestHandler) as httpd:
                webbrowser.open(f"http://localhost:{port}/map")
                httpd.handle_request()  # Handles the get request
                httpd.handle_request()  # Handles the post request (submit) before closing
                break
        except OSError as ex:
            print(f"Port {port} is in use, trying the next port...")
            print(ex)
            port += 1

    if port > max_port:
        raise RuntimeError("No available ports between 8000 and 8100.")


def download_footprints(bbox, parameters):
    return get_missing_files(bbox, URL, "bygg", parameters)


def download_pointcloud(bbox, parameters):
    return get_missing_files(bbox, URL, "laz", parameters)


def download_roadnetwork(bbox, parameters):
    return get_missing_files(bbox, URL, "vl", parameters)


def get_bounding_box():
    try:
        serve_map()
    except Exception as e:
        info(f"Failed to open the map. Error: {e}")
        return None
