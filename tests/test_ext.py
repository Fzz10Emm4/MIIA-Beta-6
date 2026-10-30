"""Pruebas de las funciones nuevas (internet, fuentes, correo, agenda, descargas): python tests/test_ext.py"""
import base64
import http.server
import imaplib
import os
import sys
import tempfile
import threading
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import miia_core as core                      # noqa: E402
from miia_android import mailbox, sources, webtools   # noqa: E402


PAGE = b"""<html><head><title>Hola Mundo</title><meta name="description" content="desc"></head>
<body><script>evil()</script><nav>menu</nav><h1>Titulo</h1><p>Primer parrafo con <a href="/x">enlace</a>.</p>
<style>.a{}</style><p>Segundo.</p></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/x")
            self.end_headers()
            return
        if self.path == "/cookie":
            body = self.headers.get("Cookie", "").encode()
        else:
            body = PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def with_server(fn):
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        fn(f"http://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()


def test_web_read():
    def run(base):
        webtools.TESTING_ALLOW_PRIVATE = True
        try:
            t = webtools.read_url(base + "/")
            assert "Titulo" in t and "Primer parrafo" in t and "evil" not in t, t
            assert webtools.EXTERNAL_NOTE in t
            assert webtools.read_url(base + "/cookie", cookie="a=b").count("a=b") >= 1
            try:
                webtools.read_url(base + "/redir")
                raise AssertionError("debió bloquear la redirección")
            except webtools.WebError:
                pass
        finally:
            webtools.TESTING_ALLOW_PRIVATE = False
    with_server(run)
    for bad in ("http://127.0.0.1/", "http://localhost/", "http://192.168.1.1/", "file:///etc/passwd"):
        try:
            webtools.read_url(bad)
            raise AssertionError(bad)
        except webtools.WebError:
            pass
    print("ok web_read")


def test_parsers():
    ddg = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fejemplo.com%2Fa">Uno</a>'
           '<a class="result__snippet" href="x">Resumen uno</a>')
    r = webtools.parse_duckduckgo(ddg)
    assert r and r[0]["url"] == "https://ejemplo.com/a" and r[0]["title"] == "Uno", r
    u = base64.urlsafe_b64encode(b"https://ejemplo.org/b").decode().rstrip("=")
    bing = f'<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1{u}">Dos</a></h2><p>Texto</p></li>'
    r = webtools.parse_bing(bing)
    assert r[0]["url"] == "https://ejemplo.org/b" and r[0]["snippet"] == "Texto", r
    wk = '{"query":{"search":[{"title":"Mate","snippet":"una <span>bebida</span>"}]}}'
    r = webtools.parse_wikipedia(wk)
    assert r[0]["url"].endswith("/wiki/Mate") and r[0]["snippet"] == "una bebida", r
    res, eng, errs = webtools.web_search("x", backends=[("A", lambda q, n: (_ for _ in ()).throw(webtools.WebError("caído"))),
                                                        ("B", lambda q, n: [{"title": "t", "url": "https://a.b", "snippet": ""}])])
    assert eng == "B" and errs and "caído" in errs[0]
    print("ok parsers")


def test_sources():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "miia_sources.json")
    s = sources.SourceStore(p)
    assert s.add("Diario Clarín", "clarin.com", cookie="") == ""
    assert s.add("Mi Instagram", "https://www.instagram.com/yo", cookie="sid=1") == ""
    assert s.add("", "x.com") != "" and s.add("Roto", "ftp://x") != ""
    assert s.find("clarin")["name"] == "Diario Clarín" and s.find("diario clarin")
    assert s.find("https://www.clarin.com/algo")["name"] == "Diario Clarín"
    assert s.cookie_for("https://www.instagram.com/otro") == "sid=1"
    assert s.cookie_for("https://evil.com/?instagram.com") == ""
    s.add("diario clarín", "https://clarin.com/nuevo")          # mismo nombre: reemplaza
    assert len(s.list()) == 2
    s2 = sources.SourceStore(p)
    assert len(s2.list()) == 2 and "clarin.com/nuevo" in s2.summary()
    s2.remove("mi instagram")
    assert len(s2.list()) == 1
    if os.name == "posix":
        assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    print("ok sources")


class FakeIMAP:
    def __init__(self, fail=False):
        self.fail, self.readonly, self.calls = fail, None, []
        m = EmailMessage()
        m["From"] = "=?utf-8?q?Mar=C3=ADa?= <maria@x.com>"
        m["To"] = "yo@gmail.com"
        m["Subject"] = "=?utf-8?q?Reuni=C3=B3n?="
        m["Date"] = "Wed, 28 Oct 2026 10:00:00 -0300"
        m.set_content("Hola, nos vemos mañana.\n\n\n\nSaludos")
        m.add_attachment(b"zz", maintype="application", subtype="pdf", filename="a.pdf")
        self.raw = m.as_bytes()

    def login(self, u, p):
        if self.fail:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    def select(self, folder, readonly=False):
        self.readonly = readonly
        return "OK", [b"1"]

    def uid(self, cmd, *a):
        self.calls.append((cmd,) + a)
        if cmd == "SEARCH":
            return "OK", [b"5 7"]
        if "HEADER" in a[1]:
            return "OK", [(b"1 (FLAGS (\\Seen) UID 7 BODY[HEADER.FIELDS] {10}", self.raw.split(b"\n\n")[0] + b"\n\n"), b")"]
        return "OK", [(b"1 (BODY[] {5}", self.raw), b")"]

    def logout(self):
        pass


def test_mailbox():
    sec = core.Secrets(None)
    fake = FakeIMAP()
    mb = mailbox.Mailbox(sec, imap_factory=lambda h, p: fake)
    assert not mb.configured()
    try:
        mb.list_messages()
        raise AssertionError
    except mailbox.MailError:
        pass
    mb.configure("yo@gmail.com", "abcd efgh ijkl mnop")
    assert sec.data["email"]["password"] == "abcdefghijklmnop" and sec.data["email"]["imap_host"] == "imap.gmail.com"
    rows, n = mb.list_messages(count=5, sender="maría", since_days=3)
    assert fake.readonly is True and n == 2 and rows[0]["subject"] == "Reunión" and "María" in rows[0]["from"], rows
    assert any(c[:3] == ("SEARCH", "CHARSET", "UTF-8") for c in fake.calls), fake.calls
    assert "FROM" not in mailbox.format_list(rows, n) and "uid 7" in mailbox.format_list(rows, n)
    txt = mb.read_message(7)
    assert "nos vemos mañana" in txt and "a.pdf" in txt and "Reunión" in txt and webtools.EXTERNAL_NOTE in txt, txt
    assert any("PEEK" in str(c) for c in fake.calls if c[0] == "FETCH")
    try:
        mb.read_message("1; DELETE")
        raise AssertionError
    except mailbox.MailError:
        pass
    bad = mailbox.Mailbox(sec, imap_factory=lambda h, p: FakeIMAP(fail=True))
    try:
        bad.test()
        raise AssertionError
    except mailbox.MailError as e:
        assert "contraseña de aplicación" in str(e)
    sent = []

    class S:
        def login(self, *a): pass
        def send_message(self, m): sent.append(m)
        def quit(self): pass
    mb2 = mailbox.Mailbox(sec, smtp_factory=lambda h, p: S())
    assert "enviado" in mb2.send("a@b.com", "Hola", "cuerpo") and sent[0]["To"] == "a@b.com"
    for bad_to in ("", "no-es-mail", "a@b.com,"*6):
        try:
            mb2.send(bad_to, "s", "b")
            raise AssertionError(bad_to)
        except mailbox.MailError:
            pass
    mb.clear()
    assert not mb.configured()
    print("ok mailbox")


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Reunion\\, equipo
DTSTART:20261029T150000
DTEND:20261029T160000
LOCATION:Oficina
END:VEVENT
BEGIN:VEVENT
SUMMARY:Gimnasio
DTSTART:20261026T190000
DTEND:20261026T200000
RRULE:FREQ=WEEKLY;BYDAY=MO,TH
EXDATE:20261102T190000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Cumple
DTSTART;VALUE=DATE:20261030
END:VEVENT
BEGIN:VEVENT
SUMMARY:Cancelado
DTSTART:20261029T100000
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def test_agenda():
    import datetime as dt
    from miia_android import agenda
    now = dt.datetime(2026, 10, 29, 9, 0)
    ev = agenda.upcoming(ICS, days=10, now=now)
    titles = [(e["title"], e["start"].strftime("%d/%m")) for e in ev]
    assert ("Reunion, equipo", "29/10") in titles, titles
    assert ("Gimnasio", "29/10") in titles and ("Gimnasio", "02/11") not in titles and ("Gimnasio", "05/11") in titles, titles
    assert any(t == "Cumple" for t, _ in titles) and not any(t == "Cancelado" for t, _ in titles)
    assert [e["start"] for e in ev] == sorted(e["start"] for e in ev)
    sec = core.Secrets(None)
    ag = agenda.Agenda(sec, fetcher=lambda u: ICS)
    assert not ag.configured()
    ag.set_url("webcal://calendar.google.com/x.ics")
    assert ag.url.startswith("https://") and "Reunion" in ag.events(days=60, start_day=dt.date(2026, 10, 29))
    bad = agenda.Agenda(sec, fetcher=lambda u: "<html>")
    try:
        bad.events()
        raise AssertionError
    except agenda.AgendaError:
        pass
    print("ok agenda")


def test_downloader():
    ytsrc = os.path.join(os.path.dirname(ROOT), "ytdlp_src")
    if not os.path.isdir(ytsrc):
        ytsrc = "/tmp/claude-0/-home-claude/12bf9760-7fe3-57e1-a984-36e28f288a38/scratchpad/ytdlp_src"
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        if not os.path.isdir(ytsrc):
            print("salto test_downloader (sin yt-dlp)")
            return
        sys.path.insert(0, ytsrc)
    import subprocess
    from miia_android import downloader, phone
    d = tempfile.mkdtemp()
    mp4 = os.path.join(d, "demo.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-shortest", "-pix_fmt", "yuv420p", mp4], check=True)

    class FH(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=d, **k)
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FH)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    webtools.TESTING_ALLOW_PRIVATE = True
    try:
        ph = phone.NullPhone()
        dl = downloader.Downloader(os.path.join(d, "out"), ph)
        url = f"http://127.0.0.1:{srv.server_port}/demo.mp4"
        info = dl.analyze(url)
        assert info["options"] and info["options"][0]["kind"] == "video", info
        prog = []
        path, where = dl.download(url, info["options"][0], on_progress=lambda f, t: prog.append(f))
        assert os.path.getsize(path) > 1000 and ph.calls[-1][0] == "publish", (path, ph.calls)
        assert prog and prog[-1] == 1.0
        try:
            dl.analyze("http://10.0.0.1/x.mp4") if not webtools.TESTING_ALLOW_PRIVATE else None
        except downloader.DownloadError:
            pass
    finally:
        webtools.TESTING_ALLOW_PRIVATE = False
        srv.shutdown()
    try:
        dl.analyze("http://192.168.1.5/video.mp4")
        raise AssertionError("debió bloquear la red local")
    except downloader.DownloadError:
        pass
    # opciones a partir de una lista de formatos de YouTube típica
    fake = {"formats": [
        {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1", "acodec": "mp4a"},
        {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a", "filesize": 50_000_000},
        {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "none"},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 129},
        {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160}]}
    o = downloader.build_options(fake)
    assert [x["id"] for x in o] == ["v720", "v360", "a-best"] and o[2]["format"] == "140", o
    assert "robot" in downloader.friendly(Exception("Sign in to confirm you're not a bot"))
    print("ok downloader")


def test_tools():
    from miia_android import agenda, downloader, phone, tools_ext
    sec = core.Secrets(None)
    ph = phone.NullPhone()
    src = sources.SourceStore(None)
    src.add("Clarin", "https://www.clarin.com")
    asked = []
    answer = {"v": True}

    def confirm(t):
        asked.append(t)
        return answer["v"]
    sent = []

    class S:
        def login(self, *a): pass
        def send_message(self, m): sent.append(m)
        def quit(self): pass
    mb = mailbox.Mailbox(sec, imap_factory=lambda h, p: FakeIMAP(), smtp_factory=lambda h, p: S())
    ag = agenda.Agenda(sec, fetcher=lambda u: ICS)
    sv = tools_ext.Services(src, mb, ag, ph, downloader.Downloader(tempfile.mkdtemp(), ph))
    mem = core.MemoryManager(None) if False else None
    tb = tools_ext.AndroidToolBox(mem, None, None, confirm, sv)
    names = lambda m: [t["name"] for t in tb.schemas(m)]
    assert "web_search" in names("chat") and "email_list" not in names("chat") and "calendar_events" not in names("chat")
    assert "open_app" in names("chat") and names("spec") == []
    mb.configure("yo@gmail.com", "abcdabcdabcdabcd")
    ag.set_url("https://x.com/a.ics")
    assert "email_send" in names("chat") and "email_list" in names("task") and "email_send" not in names("task")
    assert "open_app" not in names("task") and "download_media" not in names("task") and "schedule_task" not in names("task")
    assert "Clarin" in tb.execute("list_sources", {})
    assert "No tengo una Fuente" in tb.execute("read_source", {"name": "inexistente"})
    assert "no es del sitio" in tb.execute("read_source", {"name": "clarin", "url": "https://evil.com/x"})
    assert "uid 7" in tb.execute("email_list", {}) and not asked
    assert "no autorizó" in (answer.update(v=False) or tb.execute("email_send", {"to": "a@b.com", "subject": "s", "body": "b"}))
    assert not sent and asked
    answer["v"] = True
    assert "enviado" in tb.execute("email_send", {"to": "a@b.com", "subject": "s", "body": "b"}) and sent
    assert "no está disponible" in tb.execute("email_send", {"to": "a@b.com", "subject": "s", "body": "b"}, mode="task")
    n = len(sent)
    assert "calendario" in tb.execute("calendar_add", {"title": "Dentista", "start": "2026-11-02 10:30"})
    assert len(sent) == n and ph.calls[-1][0] == "calendar"
    assert ph.calls[-1][2] == dt_(2026, 11, 2, 10, 30)
    assert "Error" in tb.execute("calendar_add", {"title": "x", "start": "mañana"})
    assert "WhatsApp" in tb.execute("open_app", {"name": "whats"})
    assert tb.execute("open_app", {"name": "noexiste"}).startswith("Error")
    assert "Reunion" in tb.execute("calendar_events", {"days": 60, "from_date": "2026-10-29"})
    assert "Falta" in tb.execute("web_search", {"query": ""})
    print("ok tools")


def dt_(*a):
    import datetime
    return datetime.datetime(*a)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("EXT OK")
