"""Local server for the audit log. Standard library only.

Binds to 127.0.0.1 only. Read-only: the log is opened read-only, no write route exists.
Routes: GET /api/run/<run_id>  rows of one run (JSON)
        GET /events?run=<run_id>  server-sent events, one per new row, id = row id
        GET /api/rule_results/<run_id>, /api/decisions/<run_id>, /api/human_severity/<run_id>  rows (JSON)
        GET /api/log_chain  chain check of the whole log (JSON: ok, rows, broken)
        GET /api/runs  run ids with case ids (JSON)
        GET /view?run=<run_id>&upto=<n>&speed=<n>  the live record screen as an HTML fragment
        GET /<file>  a file inside the fixed web/ folder
Makes no outbound call.
"""
import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import screen

HOST = "127.0.0.1"
WEB_DIR = Path(__file__).resolve().parent / "web"
POLL_SECONDS = 0.05
KEEPALIVE_SECONDS = 1.0
UNREADABLE = "LOG UNREADABLE"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2"}


def open_readonly(db_path):
    """Open the log read-only. Raises sqlite3.Error if missing or not a log."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("SELECT 1 FROM steps LIMIT 1")  # fails if there is no steps table
    except sqlite3.Error:
        con.close()
        raise
    return con


def rows_after(con, run_id, last_id):
    cur = con.execute("SELECT rowid AS row_id, * FROM steps WHERE run_id=? AND rowid>? ORDER BY rowid",
                      (run_id, last_id))
    return [dict(r) for r in cur.fetchall()]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _refuse_write(self):
        # Read the sent body first: closing with unread bytes can abort the client's connection.
        try:
            self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1_048_576))
        except ValueError:
            pass
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse_write

    def do_GET(self):
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        query = parse_qs(parts.query)
        if path.startswith("/api/run/"):
            return self._run_rows(path[len("/api/run/"):])
        if path == "/view":
            return self._view(query)
        if path == "/api/log_chain":
            return self._read_api(lambda con: screen.chain_state(con))
        if path == "/api/runs":
            return self._read_api(lambda con: dict(runs=screen.list_runs(con)))
        for name, fn in (("rule_results", screen.rule_result_rows), ("decisions", screen.decision_rows),
                         ("human_severity", screen.human_severity_rows)):
            if path.startswith(f"/api/{name}/"):
                run_id = path[len(f"/api/{name}/"):]
                return self._read_api(lambda con, fn=fn, run_id=run_id: dict(run_id=run_id, rows=fn(con, run_id)))
        if path == "/events":
            return self._events(query.get("run", [""])[0])
        return self._static(path)

    def _run_rows(self, run_id):
        try:
            con = open_readonly(self.server.db_path)
        except sqlite3.Error:
            return self._send(503, json.dumps({"state": UNREADABLE}), "application/json")
        try:
            rows = rows_after(con, run_id, 0)
        finally:
            con.close()
        self._send(200, json.dumps({"run_id": run_id, "rows": rows}), "application/json")

    def _read_api(self, make):
        try:
            con = open_readonly(self.server.db_path)
        except sqlite3.Error:
            return self._send(503, json.dumps({"state": UNREADABLE}), "application/json")
        try:
            body = json.dumps(make(con))
        except sqlite3.Error:
            return self._send(503, json.dumps({"state": UNREADABLE}), "application/json")
        finally:
            con.close()
        self._send(200, body, "application/json")

    def _view(self, query):
        """The screen as an HTML fragment. The mode comes from the server, never from the browser."""
        run_id = query.get("run", [""])[0]
        mode = self.server.mode
        try:
            speed = int(query.get("speed", [screen.DEFAULT_SPEED])[0])
        except ValueError:
            speed = screen.DEFAULT_SPEED
        upto = query.get("upto", [""])[0]
        upto = int(upto) if upto.isdigit() else None
        show = query.get("show", [""])[0]
        show = int(show) if show.isdigit() else None
        try:
            con = open_readonly(self.server.db_path)
        except sqlite3.Error:
            return self._send(200, screen.unreadable(), TYPES[".html"])
        try:
            rec = screen.build_record(con, run_id) if run_id else None
            if rec is None:
                page = screen.no_run(screen.list_runs(con))
            else:
                page = screen.render(rec, mode, speed, upto, show)
        except sqlite3.Error:
            page = screen.unreadable()
        finally:
            con.close()
        self._send(200, page, TYPES[".html"])

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        if "\x00" in rel or "\\" in rel or ".." in rel.split("/"):
            return self._send(404, "not found")
        root = self.server.web_dir.resolve()
        target = (root / rel).resolve()
        if root not in target.parents or not target.is_file():
            return self._send(404, "not found")
        self._send(200, target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"))

    def _events(self, run_id):
        header = self.headers.get("Last-Event-ID", "")
        last_id = int(header) if header.isdigit() else 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            con = open_readonly(self.server.db_path)
        except sqlite3.Error:
            self.wfile.write(f"event: error\ndata: {UNREADABLE}\n\n".encode())
            self.wfile.flush()
            return
        last_ping = time.monotonic()
        try:
            while not self.server.stopping.is_set():
                for row in rows_after(con, run_id, last_id):
                    last_id = row["row_id"]
                    self.wfile.write(f"id: {last_id}\ndata: {json.dumps(row)}\n\n".encode())
                    self.wfile.flush()
                    last_ping = time.monotonic()
                if time.monotonic() - last_ping >= KEEPALIVE_SECONDS:
                    self.wfile.write(b": keepalive\n\n")  # also finds dropped clients
                    self.wfile.flush()
                    last_ping = time.monotonic()
                self.server.stopping.wait(POLL_SECONDS)
        except (OSError, sqlite3.Error):
            pass
        finally:
            con.close()


class AuditServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, db_path, port=0, host=HOST, web_dir=WEB_DIR, mode="live"):
        if host != HOST:
            raise ValueError(f"host must be {HOST}; got {host!r}")
        if mode not in ("live", "replay"):
            raise ValueError("mode must be 'live' or 'replay'")
        self.mode = mode
        self.db_path = db_path
        self.web_dir = Path(web_dir)
        self.stopping = threading.Event()
        super().__init__((HOST, int(port)), Handler)


def start(db_path, port=0, host=HOST, web_dir=WEB_DIR, mode="live"):
    """Start in a background thread. Returns (server, thread)."""
    srv = AuditServer(db_path, port, host, web_dir, mode)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return srv, t


def stop(srv, thread):
    srv.stopping.set()
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=2)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Local audit log server (127.0.0.1 only)")
    ap.add_argument("db")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--replay", action="store_true", help="the log is a recorded run: label the screen REPLAY")
    a = ap.parse_args()
    try:
        s = AuditServer(a.db, a.port, a.host, mode="replay" if a.replay else "live")
    except ValueError as e:
        sys.exit(str(e))
    print(f"Serving on http://{HOST}:{s.server_address[1]}/  (Ctrl+C to stop)")
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        s.stopping.set()
        s.server_close()
