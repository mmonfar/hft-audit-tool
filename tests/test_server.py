"""Server tests. Synthetic rows only. Stdlib + pytest. Port 0 everywhere."""
import http.client
import json
import socket
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import log  # noqa: E402
import server  # noqa: E402


def add_step(con, n, run="r1"):
    log.write_step(con, "before", f"s{n}", run, "c1", "finder", n, f"2026-01-01T00:00:{n:02d}", asked=f"q{n}")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "audit.db"
    con = log.open_db(str(path))
    con.execute("INSERT INTO runs VALUES ('r1','2026-01-01T00:00:00','dv1','sh1','pilot','off',1,'x')")
    log.add_case(con, "c1", "label", "dev", "ih1")
    yield path, con
    con.close()


@pytest.fixture
def running(db):
    path, con = db
    srv, thread = server.start(str(path), port=0)
    yield srv, con
    server.stop(srv, thread)


def conn(srv, timeout=5):
    return http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=timeout)


def get(srv, target, headers=None):
    c = conn(srv)
    c.request("GET", target, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def read_events(resp, n):
    """Read n events from an open stream. Returns list of (id, data)."""
    events, cur = [], {}
    while len(events) < n:
        line = resp.readline()
        assert line, "stream ended early"
        line = line.decode().rstrip("\n")
        if line.startswith(":"):
            continue
        if line == "":
            if cur:
                events.append((cur.get("id"), cur.get("data"), cur.get("event")))
                cur = {}
            continue
        k, _, v = line.partition(": ")
        cur[k] = v
    return events


def open_stream(srv, headers=None):
    c = conn(srv)
    c.request("GET", "/events?run=r1", headers=headers or {})
    return c, c.getresponse()


# --- bind address -----------------------------------------------------------

def test_bound_address_is_loopback(running):
    srv, _ = running
    assert srv.socket.getsockname()[0] == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "localhost", "", "::"])
def test_other_hosts_refused(db, host):
    with pytest.raises(ValueError):
        server.AuditServer(str(db[0]), 0, host)


# --- read-only --------------------------------------------------------------

@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_write_methods_405_and_rows_unchanged(running, method):
    srv, con = running
    add_step(con, 1)
    c = conn(srv)
    c.request(method, "/api/run/r1", body=b"x")
    assert c.getresponse().status == 405
    c.close()
    assert con.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 1


def test_readonly_handle_refuses_write_and_a_normal_handle_would_not(db):
    path, _ = db
    ro = server.open_readonly(str(path))
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO runs VALUES ('r2','t','d','h','pilot','off',1,'x')")
    ro.close()
    rw = sqlite3.connect(str(path))  # planted bad case: a normal handle accepts the write
    rw.execute("INSERT INTO runs VALUES ('r2','t','d','h','pilot','off',1,'x')")
    rw.commit()
    rw.close()


# --- JSON route -------------------------------------------------------------

def test_run_rows_json(running):
    srv, con = running
    for n in (1, 2):
        add_step(con, n)
    con.execute("INSERT INTO runs VALUES ('other','2026-01-01T00:00:00','dv1','sh1','pilot','off',1,'x')")
    log.write_step(con, "before", "o1", "other", "c1", "finder", 1, "2026-01-01T00:01:00")
    status, body = get(srv, "/api/run/r1")
    rows = json.loads(body)["rows"]
    assert status == 200
    assert [r["step_id"] for r in rows] == ["s1", "s2"]


# --- path traversal ---------------------------------------------------------

def test_web_file_served(running):
    srv, _ = running
    status, body = get(srv, "/index.html")
    assert status == 200 and b"Live record" in body
    assert get(srv, "/")[0] == 200


@pytest.mark.parametrize("target", [
    "/../log.py", "/%2e%2e/log.py", "/%2e%2e%2flog.py", "/..%2flog.py", "/..%5clog.py",
    "/%252e%252e/log.py", "/web/../log.py", "//etc/passwd", "/../schema.sql", "/x/../../server.py",
])
def test_path_traversal_refused(running, target):
    srv, _ = running
    # raw request line so the client does not tidy the path
    s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
    s.sendall(f"GET {target} HTTP/1.0\r\n\r\n".encode())
    data = b""
    while chunk := s.recv(4096):
        data += chunk
    s.close()
    assert data.startswith(b"HTTP/1.0 404")
    assert b"def " not in data and b"CREATE TABLE" not in data


def test_traversal_test_can_fail():
    """Planted bad case: a plain join would reach log.py, so the 404 above is earned."""
    naive = (ROOT / "web" / ".." / "log.py")
    assert naive.is_file()


# --- stream -----------------------------------------------------------------

def test_three_rows_three_events_in_order(running):
    srv, con = running
    c, resp = open_stream(srv)
    assert resp.getheader("Content-Type") == "text/event-stream"
    for n in (1, 2, 3):
        add_step(con, n)
    ev = read_events(resp, 3)
    c.close()
    assert [e[0] for e in ev] == ["1", "2", "3"]
    assert [json.loads(e[1])["step_id"] for e in ev] == ["s1", "s2", "s3"]


def test_resume_with_last_event_id(running):
    srv, con = running
    for n in (1, 2, 3):
        add_step(con, n)
    c, resp = open_stream(srv, {"Last-Event-ID": "2"})
    ev = read_events(resp, 1)
    c.close()
    assert [e[0] for e in ev] == ["3"]
    assert json.loads(ev[0][1])["step_id"] == "s3"


def test_without_last_event_id_all_rows_come(running):
    """Planted bad case: no resume header gives every row, so the test above bites."""
    srv, con = running
    for n in (1, 2, 3):
        add_step(con, n)
    c, resp = open_stream(srv)
    ev = read_events(resp, 3)
    c.close()
    assert [e[0] for e in ev] == ["1", "2", "3"]


def test_new_row_arrives_while_open(running):
    srv, con = running
    c, resp = open_stream(srv)
    time.sleep(0.2)
    add_step(con, 1)
    assert read_events(resp, 1)[0][0] == "1"
    c.close()


def test_missing_database_gives_unreadable_event(tmp_path):
    srv, thread = server.start(str(tmp_path / "nothing.db"), port=0)
    try:
        c, resp = open_stream(srv)
        ev = read_events(resp, 1)
        c.close()
        assert ev[0][2] == "error" and ev[0][1] == "LOG UNREADABLE"
        status, body = get(srv, "/api/run/r1")
        assert status == 503 and b"LOG UNREADABLE" in body
    finally:
        server.stop(srv, thread)
    assert not (tmp_path / "nothing.db").exists()  # reading did not create it


# --- stop and port ----------------------------------------------------------

def test_stops_within_two_seconds_with_open_stream_and_port_free(db):
    path, con = db
    srv, thread = server.start(str(path), port=0)
    port = srv.server_address[1]
    c, resp = open_stream(srv)
    add_step(con, 1)
    read_events(resp, 1)
    t0 = time.monotonic()
    server.stop(srv, thread)
    assert time.monotonic() - t0 < 2
    assert not thread.is_alive()
    c.close()
    s = socket.socket()
    s.bind(("127.0.0.1", port))  # fails if the port is still held
    s.close()


# --- no outbound call -------------------------------------------------------

@pytest.fixture
def guard(monkeypatch):
    real = socket.socket.connect

    def checked(self, addr):
        if not (isinstance(addr, tuple) and addr[0] in ("127.0.0.1", "::1")):
            raise AssertionError(f"outbound connect refused: {addr!r}")
        return real(self, addr)

    monkeypatch.setattr(socket.socket, "connect", checked)


def test_guard_blocks_public_address_and_allows_loopback(guard, running):
    srv, _ = running
    s = socket.socket()
    with pytest.raises(AssertionError):
        s.connect(("8.8.8.8", 80))  # planted outbound call
    s.close()
    assert get(srv, "/index.html")[0] == 200


def test_requests_make_no_outbound_call(guard, running):
    srv, con = running
    add_step(con, 1)
    c, resp = open_stream(srv)
    read_events(resp, 1)
    c.close()
    assert get(srv, "/api/run/r1")[0] == 200


def test_server_source_has_no_network_client_code():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    for word in ("urlopen", "requests", "http.client", "create_connection", "import socket"):
        assert word not in src, word
