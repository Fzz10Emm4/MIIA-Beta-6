"""Agenda: lee el Calendario de Google por su «dirección secreta en formato iCal» (solo lectura, sin cuentas ni claves).

El usuario copia ese enlace una vez (Google Calendar > Configuración del calendario > Dirección secreta en formato iCal)
y lo pega en «Correo y agenda». Las reuniones nuevas se crean con el calendario del teléfono (ver phone.py).
Soporta eventos simples, de todo el día y repeticiones comunes (DAILY/WEEKLY/MONTHLY/YEARLY con INTERVAL, COUNT,
UNTIL, BYDAY y EXDATE). Cosas muy raras de iCal se ignoran en vez de fallar.
"""

import datetime as dt
import re

from . import webtools

WD = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
WD_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


class AgendaError(Exception):
    pass


def _unfold(text: str):
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _parse_dt(value: str, params: str):
    """-> (datetime naive en hora local, todo_el_dia)."""
    value = value.strip()
    if "VALUE=DATE" in params or re.fullmatch(r"\d{8}", value):
        return dt.datetime.strptime(value[:8], "%Y%m%d"), True
    fmt = "%Y%m%dT%H%M%S"
    d = dt.datetime.strptime(value.rstrip("Z")[:15], fmt)
    if value.endswith("Z"):
        d = d.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    else:
        m = re.search(r"TZID=([^;:]+)", params)
        if m:
            try:
                from zoneinfo import ZoneInfo
                d = d.replace(tzinfo=ZoneInfo(m.group(1))).astimezone().replace(tzinfo=None)
            except Exception:
                pass                       # sin base de zonas: se deja tal cual
    return d, False


def parse_ics(text: str):
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"exdate": []}
        elif line == "END:VEVENT":
            if cur and cur.get("start") and not cur.get("cancelled"):
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, _, value = line.partition(":")
            name, _, params = head.partition(";")
            name = name.upper()
            try:
                if name == "SUMMARY":
                    cur["title"] = _unescape(value)
                elif name == "LOCATION":
                    cur["where"] = _unescape(value)
                elif name == "DTSTART":
                    cur["start"], cur["allday"] = _parse_dt(value, params)
                elif name == "DTEND":
                    cur["end"], _ = _parse_dt(value, params)
                elif name == "RRULE":
                    cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
                elif name == "EXDATE":
                    for v in value.split(","):
                        cur["exdate"].append(_parse_dt(v, params)[0].date())
                elif name == "STATUS" and value.strip().upper() == "CANCELLED":
                    cur["cancelled"] = True
                elif name == "RECURRENCE-ID":
                    cur["override"] = True
            except Exception:
                cur = cur                  # propiedad rara: se ignora
    return events


def _occurrences(ev, lo: dt.datetime, hi: dt.datetime, limit=400):
    start = ev["start"]
    dur = (ev["end"] - start) if ev.get("end") and ev["end"] > start else (
        dt.timedelta(days=1) if ev.get("allday") else dt.timedelta(0))
    rule = ev.get("rrule")
    if not rule:
        if start + dur >= lo and start <= hi:
            yield start, start + dur
        return
    freq = rule.get("FREQ", "")
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        try:
            until = _parse_dt(rule["UNTIL"], "")[0]
            if len(rule["UNTIL"]) == 8:
                until += dt.timedelta(days=1)
        except Exception:
            pass
    days = [WD.index(x[-2:]) for x in rule.get("BYDAY", "").split(",") if x[-2:] in WD]
    produced, n, cursor = 0, 0, start
    while n < limit * 20:
        n += 1
        if freq == "DAILY":
            cands = [start + dt.timedelta(days=interval * (n - 1))]
        elif freq == "WEEKLY":
            base = start - dt.timedelta(days=start.weekday()) + dt.timedelta(weeks=interval * (n - 1))
            cands = [base + dt.timedelta(days=d) for d in (days or [start.weekday()])]
        elif freq == "MONTHLY":
            mth = start.month - 1 + interval * (n - 1)
            try:
                cands = [start.replace(year=start.year + mth // 12, month=mth % 12 + 1)]
            except ValueError:
                cands = []
        elif freq == "YEARLY":
            try:
                cands = [start.replace(year=start.year + interval * (n - 1))]
            except ValueError:
                cands = []
        else:
            return
        for c in sorted(cands):
            if c < start:
                continue
            if until and c > until:
                return
            if count is not None and produced >= count:
                return
            produced += 1
            if c.date() in ev["exdate"]:
                continue
            if c > hi:
                return
            if c + dur >= lo:
                yield c, c + dur


def upcoming(ics_text: str, days=7, start_day=None, now=None, max_events=40):
    """Eventos desde el inicio de start_day (o ahora) durante `days` días, ordenados."""
    now = now or dt.datetime.now()
    lo = dt.datetime.combine(start_day, dt.time.min) if start_day else now
    hi = lo + dt.timedelta(days=max(1, min(int(days), 90)))
    out = []
    for ev in parse_ics(ics_text):
        if ev.get("override"):
            continue
        for s, e in _occurrences(ev, lo, hi):
            out.append({"title": ev.get("title", "(sin título)"), "start": s, "end": e,
                        "allday": ev.get("allday", False), "where": ev.get("where", "")})
    out.sort(key=lambda x: x["start"])
    return out[:max_events]


def format_events(events, title="Agenda") -> str:
    if not events:
        return "No hay eventos en ese período."
    lines = [f"{title}. {webtools.EXTERNAL_NOTE}"]
    for e in events:
        s = e["start"]
        when = f"{WD_ES[s.weekday()]} {s.strftime('%d/%m')}" + ("" if e["allday"] else f" {s.strftime('%H:%M')}")
        if not e["allday"] and e["end"] > s:
            when += f"–{e['end'].strftime('%H:%M')}"
        lines.append(f"- {when}: {e['title']}" + (f" ({e['where']})" if e["where"] else ""))
    return "\n".join(lines)


class Agenda:
    def __init__(self, secrets, fetcher=None):
        self.secrets = secrets
        self._fetch = fetcher or self._http

    @staticmethod
    def _http(url):
        _u, ctype, raw = webtools.fetch(url, max_bytes=4_000_000, timeout=20)
        return raw.decode("utf-8", "replace")

    @property
    def url(self) -> str:
        with self.secrets.lock:
            return (self.secrets.data.get("ical_url") or "").strip()

    def configured(self) -> bool:
        return bool(self.url)

    def set_url(self, url: str):
        url = (url or "").strip()
        if url:
            if url.startswith("webcal://"):
                url = "https://" + url[len("webcal://"):]
            url = webtools.normalize_url(url)
        with self.secrets.lock:
            if url:
                self.secrets.data["ical_url"] = url
            else:
                self.secrets.data.pop("ical_url", None)
            self.secrets._save()

    def _text(self) -> str:
        if not self.url:
            raise AgendaError("La agenda no está configurada. Pegá la dirección iCal en «Correo y agenda».")
        try:
            text = self._fetch(self.url)
        except webtools.WebError as e:
            raise AgendaError(f"No pude leer el calendario: {e}")
        if "BEGIN:VCALENDAR" not in text:
            raise AgendaError("Ese enlace no devolvió un calendario iCal (debe ser la «dirección secreta en formato iCal»).")
        return text

    def test(self) -> str:
        evs = parse_ics(self._text())
        return f"Calendario leído: {len(evs)} eventos."

    def events(self, days=7, start_day=None, now=None) -> str:
        return format_events(upcoming(self._text(), days=days, start_day=start_day, now=now),
                             title=f"Agenda de los próximos {days} días")
