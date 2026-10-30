"""Correo de MIIA por IMAP/SMTP con una contraseña de aplicación (Gmail u otro proveedor).

- Leer es libre y NO modifica nada: las carpetas se abren en solo lectura y los mensajes con BODY.PEEK (no se marcan
  como leídos).
- Enviar solo ocurre después de que el usuario lo confirma (eso lo pide la herramienta, ver tools_ext.py).
- La contraseña de aplicación vive en miia_secrets.json (privado, nunca se sube) y se pide una sola vez.
- Todo lo que sale de un correo es contenido externo: se marca como datos, no como instrucciones.
"""

import datetime as dt
import email
import imaplib
import re
import smtplib
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate, parsedate_to_datetime

from . import webtools

PROVIDERS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "outlook.com": ("outlook.office365.com", "smtp.office365.com"),
    "hotmail.com": ("outlook.office365.com", "smtp.office365.com"),
    "live.com": ("outlook.office365.com", "smtp.office365.com"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com"),
}
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
EMAIL_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


class MailError(Exception):
    pass


def _hdr(value) -> str:
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value)))).replace("\r", " ").replace("\n", " ").strip()
    except Exception:
        return str(value).replace("\n", " ")


def _date(value) -> str:
    try:
        d = parsedate_to_datetime(str(value))
        if d.tzinfo is not None:
            d = d.astimezone()
        return d.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value or "")[:25]


def providers_for(address: str):
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    return PROVIDERS.get(domain)


class Mailbox:
    def __init__(self, secrets, imap_factory=None, smtp_factory=None):
        self.secrets = secrets
        self._imap = imap_factory or (lambda host, port: imaplib.IMAP4_SSL(host, port, timeout=25))
        self._smtp = smtp_factory or (lambda host, port: smtplib.SMTP_SSL(host, port, timeout=25))

    # ---- configuración (en miia_secrets.json) ----
    def _cfg(self) -> dict:
        with self.secrets.lock:
            return dict(self.secrets.data.get("email") or {})

    def configured(self) -> bool:
        c = self._cfg()
        return bool(c.get("address") and c.get("password"))

    @property
    def address(self) -> str:
        return self._cfg().get("address", "")

    def configure(self, address, app_password, imap_host="", smtp_host=""):
        address = (address or "").strip()
        pw = re.sub(r"\s+", "", app_password or "")          # Google la muestra en bloques con espacios
        if not EMAIL_RE.match(address):
            raise MailError("Ese correo no parece válido.")
        if not pw:
            raise MailError("Falta la contraseña de aplicación.")
        prov = providers_for(address)
        imap_host = (imap_host or "").strip() or (prov[0] if prov else "")
        smtp_host = (smtp_host or "").strip() or (prov[1] if prov else "")
        if not imap_host:
            raise MailError("No conozco el servidor de ese proveedor: escribí el servidor IMAP (ej. imap.midominio.com).")
        with self.secrets.lock:
            self.secrets.data["email"] = {"address": address, "password": pw, "imap_host": imap_host,
                                          "smtp_host": smtp_host or imap_host.replace("imap", "smtp", 1)}
            self.secrets._save()

    def clear(self):
        with self.secrets.lock:
            self.secrets.data.pop("email", None)
            self.secrets._save()

    # ---- conexión ----
    def _connect(self):
        c = self._cfg()
        if not (c.get("address") and c.get("password")):
            raise MailError("El correo no está configurado. Configurarlo en el menú: «Correo y agenda».")
        try:
            m = self._imap(c["imap_host"], 993)
            m.login(c["address"], c["password"])
            return m
        except imaplib.IMAP4.error as e:
            msg = str(e)
            if "AUTHENTICATIONFAILED" in msg.upper() or "invalid credentials" in msg.lower():
                raise MailError("El correo rechazó la contraseña. Tiene que ser una «contraseña de aplicación» "
                                "(no la normal) y la verificación en 2 pasos debe estar activada.")
            raise MailError(f"El servidor de correo respondió: {msg[:150]}")
        except OSError as e:
            raise MailError(f"No pude conectar con el correo (¿sin internet?): {e}")

    def _open(self, folder="INBOX"):
        m = self._connect()
        typ, _ = m.select('"' + folder.replace('"', "") + '"', readonly=True)
        if typ != "OK":
            try:
                m.logout()
            except Exception:
                pass
            raise MailError(f"No existe la carpeta «{folder}».")
        return m

    @staticmethod
    def _close(m):
        try:
            m.logout()
        except Exception:
            pass

    def test(self) -> str:
        """Prueba usuario y contraseña. Devuelve un texto para mostrar."""
        m = self._open("INBOX")
        try:
            typ, data = m.uid("SEARCH", None, "UNSEEN")
            n = len((data[0] or b"").split()) if typ == "OK" and data else 0
        finally:
            self._close(m)
        return f"Conexión correcta con {self.address}. Mensajes sin leer en la bandeja de entrada: {n}."

    # ---- leer ----
    @staticmethod
    def _criteria(unread_only=False, sender="", since_days=0, text="", subject=""):
        crit = []
        if unread_only:
            crit.append("UNSEEN")
        if sender:
            crit += ["FROM", sender]
        if subject:
            crit += ["SUBJECT", subject]
        if text:
            crit += ["TEXT", text]
        if since_days and int(since_days) > 0:
            d = dt.date.today() - dt.timedelta(days=int(since_days))
            crit += ["SINCE", f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"]
        return crit or ["ALL"]

    def _search_uids(self, m, crit):
        args = []
        needs_utf8 = any(not a.isascii() for a in crit)
        for a in crit:
            args.append(a.encode("utf-8") if needs_utf8 and not a.isascii() else a)
        if needs_utf8:
            typ, data = m.uid("SEARCH", "CHARSET", "UTF-8", *[x.encode("utf-8") if isinstance(x, str) else x for x in args])
        else:
            typ, data = m.uid("SEARCH", None, *args)
        if typ != "OK":
            raise MailError("La búsqueda en el correo falló.")
        return (data[0] or b"").split()

    def _headers(self, m, uids):
        out = []
        for uid in uids:
            typ, data = m.uid("FETCH", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not data:
                continue
            head, flags = b"", b""
            for part in data:
                if isinstance(part, tuple):
                    flags = part[0]
                    head = part[1]
                    break
            msg = email.message_from_bytes(head, policy=policy.compat32)
            out.append({"uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                        "from": _hdr(msg.get("From")), "subject": _hdr(msg.get("Subject")) or "(sin asunto)",
                        "date": _date(msg.get("Date")), "unread": b"\\Seen" not in flags})
        return out

    def list_messages(self, count=10, unread_only=False, sender="", since_days=0, text="", subject="", folder="INBOX"):
        count = max(1, min(int(count or 10), 25))
        m = self._open(folder)
        try:
            uids = self._search_uids(m, self._criteria(unread_only, sender, since_days, text, subject))
            uids = list(reversed(uids))[:count]              # los más nuevos primero
            return self._headers(m, uids), len(uids)
        finally:
            self._close(m)

    def read_message(self, uid, folder="INBOX", max_chars=5000, start=0):
        uid = str(uid).strip()
        if not uid.isdigit():
            raise MailError("El número de mensaje (uid) debe ser un número; sale de email_list o email_search.")
        m = self._open(folder)
        try:
            typ, data = m.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = b""
            for part in data or []:
                if isinstance(part, tuple):
                    raw = part[1]
                    break
            if typ != "OK" or not raw:
                raise MailError(f"No encontré el mensaje {uid}.")
        finally:
            self._close(m)
        msg = email.message_from_bytes(raw, policy=policy.default)
        body = ""
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            content = part.get_content()
            if part.get_content_type() == "text/html":
                content = webtools.html_to_text(content)[1]
            body = content
        atts = [a.get_filename() for a in msg.iter_attachments() if a.get_filename()]
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        chunk = body[int(start or 0):int(start or 0) + max_chars]
        more = len(body) - (int(start or 0) + len(chunk))
        head = (f"De: {_hdr(msg.get('From'))}\nPara: {_hdr(msg.get('To'))}\nFecha: {_date(msg.get('Date'))}\n"
                f"Asunto: {_hdr(msg.get('Subject'))}")
        if atts:
            head += "\nAdjuntos (no se abren): " + ", ".join(atts[:8])
        tail = f"\n...[quedan {more} caracteres; pedí la parte siguiente con start={int(start or 0) + len(chunk)}]" if more > 0 else ""
        return f"{head}\n{webtools.EXTERNAL_NOTE}\n\n{chunk}{tail}"

    # ---- enviar (solo después de confirmar) ----
    def send(self, to, subject, body):
        c = self._cfg()
        if not (c.get("address") and c.get("password")):
            raise MailError("El correo no está configurado.")
        recipients = [r.strip() for r in re.split(r"[;,]", to or "") if r.strip()]
        if not recipients or len(recipients) > 5:
            raise MailError("Indicá entre 1 y 5 destinatarios.")
        for r in recipients:
            if not EMAIL_RE.match(r):
                raise MailError(f"«{r}» no parece un correo válido.")
        msg = EmailMessage()
        msg["From"] = c["address"]
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = (subject or "").replace("\n", " ")[:200]
        msg["Date"] = formatdate(localtime=True)
        msg.set_content(body or "")
        try:
            s = self._smtp(c["smtp_host"], 465)
            try:
                s.login(c["address"], c["password"])
                s.send_message(msg)
            finally:
                try:
                    s.quit()
                except Exception:
                    pass
        except smtplib.SMTPAuthenticationError:
            raise MailError("El correo rechazó la contraseña de aplicación.")
        except (smtplib.SMTPException, OSError) as e:
            raise MailError(f"No pude enviar el correo: {e}")
        return f"Correo enviado a {', '.join(recipients)}."


def format_list(rows, total, title="Correos") -> str:
    if not rows:
        return "No hay correos que coincidan."
    lines = [f"{title} ({len(rows)}). {webtools.EXTERNAL_NOTE}"]
    for r in rows:
        lines.append(f"- uid {r['uid']}{' [SIN LEER]' if r['unread'] else ''} · {r['date']} · {r['from']}\n  Asunto: {r['subject']}")
    lines.append("Para leer uno, usa email_read con su uid.")
    return "\n".join(lines)
