"""No outside call in a full run. A socket guard raises on any non-loopback connect and on
any bind other than 127.0.0.1. A planted attempt to reach a public address must fail."""
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import log
import orchestrator as orch
from casekit import make_case, write_stub

ROOT = Path(__file__).resolve().parents[1]


class NetworkGuardError(AssertionError):
    pass


def _host(addr):
    return addr[0] if isinstance(addr, tuple) else addr


def install_guard(monkeypatch):
    real_connect, real_ex, real_bind = socket.socket.connect, socket.socket.connect_ex, socket.socket.bind

    def check(addr, what):
        if isinstance(addr, (str, bytes)):  # unix socket path: local only
            return
        host = _host(addr)
        if host != "127.0.0.1":
            raise NetworkGuardError(f"{what} to {host!r} refused")

    def connect(self, addr):
        check(addr, "connect")
        return real_connect(self, addr)

    def connect_ex(self, addr):
        check(addr, "connect_ex")
        return real_ex(self, addr)

    def bind(self, addr):
        check(addr, "bind")
        return real_bind(self, addr)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket.socket, "bind", bind)
    real_gai = socket.getaddrinfo

    def getaddrinfo(host, *a, **k):
        if host != "127.0.0.1":
            raise NetworkGuardError(f"DNS lookup of {host!r} refused")
        return real_gai(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def test_guard_refuses_public_connect_and_bad_bind(monkeypatch):
    install_guard(monkeypatch)
    s = socket.socket()
    try:
        with pytest.raises(NetworkGuardError):
            s.connect(("93.184.216.34", 80))
        with pytest.raises(NetworkGuardError):
            s.connect_ex(("8.8.8.8", 53))
        with pytest.raises(NetworkGuardError):
            s.bind(("0.0.0.0", 0))
        with pytest.raises(NetworkGuardError):
            s.bind(("192.168.1.5", 0))
    finally:
        s.close()


def test_full_stub_run_passes_under_the_guard(monkeypatch, tmp_path):
    install_guard(monkeypatch)
    con = log.open_db(":memory:")
    res = orch.run_case(make_case(), con, orch.StubModel(write_stub(tmp_path / "s")))
    assert res["state"] == "CONFIRMED"


def test_full_cli_run_passes_under_the_guard(monkeypatch, tmp_path):
    install_guard(monkeypatch)
    case = tmp_path / "c.json"
    case.write_text(json.dumps(make_case()), encoding="utf-8")
    write_stub(tmp_path / "c.stub")
    assert orch.main(["--case", str(case), "--db", str(tmp_path / "l.db"), "--stub"]) == 0


class Phones(orch.StubModel):
    """Planted bad model: tries to reach a public address in the middle of a run."""

    def generate(self, agent, prompt, seed=0):
        s = socket.socket()
        try:
            s.connect(("93.184.216.34", 443))
        finally:
            s.close()
        return super().generate(agent, prompt, seed)


def test_planted_public_call_in_a_run_is_caught(monkeypatch, tmp_path):
    install_guard(monkeypatch)
    con = log.open_db(":memory:")
    with pytest.raises(NetworkGuardError):
        orch.run_case(make_case(), con, Phones(write_stub(tmp_path / "s")))


def test_real_client_talks_to_loopback_only_with_keep_alive_zero(monkeypatch):
    """The real local-model client, against a fake server on 127.0.0.1, under the guard."""
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"response": "PASS\nline", "done_reason": "stop"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    install_guard(monkeypatch)
    try:
        m = orch.LocalModel(port=srv.server_address[1])
        text, hit = m.generate("reader", "hello", 3)
    finally:
        srv.shutdown()
        srv.server_close()
    assert text == "PASS\nline" and hit is False
    assert seen["body"]["keep_alive"] == 0 and seen["body"]["model"] == "gpt-oss:20b"
    assert seen["body"]["options"]["temperature"] == 0 and seen["body"]["options"]["seed"] == 3
    assert "127.0.0.1" in m.url


def test_real_client_refuses_other_hosts():
    for host in ("localhost", "0.0.0.0", "93.184.216.34", "example.com"):
        with pytest.raises(ValueError):
            orch.LocalModel(host=host)


def test_source_scan_finds_no_outside_client():
    banned = r"\b(requests|httpx|aiohttp|http\.client|ftplib|smtplib|telnetlib|websocket|socket|subprocess)\b"
    for name in ("orchestrator.py", "referee.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", code, re.M)
        assert not [i for i in imports if re.fullmatch(banned, i.split(".")[0])], (name, imports)
        assert "http.client" not in code and "requests" not in code
    src = (ROOT / "orchestrator.py").read_text(encoding="utf-8")
    urls = re.findall(r"https?://[^\s\"'}]+", src)
    assert all(u.startswith("http://{host") or u.startswith("http://127.0.0.1") for u in urls), urls
    assert "urllib" in src and src.count("import urllib.request") == 1
    assert "urllib" not in (ROOT / "referee.py").read_text(encoding="utf-8")
