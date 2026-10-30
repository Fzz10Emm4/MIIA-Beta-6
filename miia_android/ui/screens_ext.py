"""Pantallas nuevas: Fuentes, Descargar y Correo y agenda."""

import threading

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.progressbar import ProgressBar

from .. import webtools
from ..downloader import DownloadError
from ..mailbox import MailError
from ..agenda import AgendaError
from ..util import log_exc
from . import theme
from .kit import Dialog, Panel, WLabel, button, field, hrow, rowlabel, small, spacer, spinner, title


def _box():
    b = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
    b.bind(minimum_height=b.setter("height"))
    return b


def _bg(fn, done):
    """Corre fn() en un hilo y llama done(resultado, error_texto) en el hilo de la interfaz."""
    def run():
        res, err = None, ""
        try:
            res = fn()
        except (webtools.WebError, MailError, AgendaError, DownloadError) as e:
            err = str(e)
        except Exception as e:
            log_exc("pantalla")
            err = f"{type(e).__name__}: {e}"
        Clock.schedule_once(lambda dt: done(res, err), 0)
    threading.Thread(target=run, daemon=True).start()


# ====================================================================== FUENTES
def open_sources(app):
    eng = app.engine
    dlg = Dialog("Fuentes")
    dlg.add(small("Las webs y redes que agregues acá las consulta MIIA cuando le preguntes algo («mirá en mi fuente "
                  "Clarín qué pasó hoy»). Solo lee: no publica ni escribe nada. Las redes sociales casi siempre exigen "
                  "iniciar sesión: si no se puede leer, MIIA te lo dice."))
    lst = _box()
    dlg.add(lst)
    out = WLabel("", size=13, color=theme.TEXT_DIM)

    def refresh():
        lst.clear_widgets()
        items = eng.sources.list()
        if not items:
            lst.add_widget(WLabel("Aún no hay fuentes.", color=theme.TEXT_DIM))
        for it in items:
            card = Panel(bg=theme.SURFACE, orientation="horizontal", size_hint_y=None, height=dp(64),
                         padding=dp(8), spacing=dp(6))
            card.add_widget(rowlabel(f"{it['name']}\n{it['url']}", size=13))

            def test(i=it):
                out.set_text(f"Probando {i['name']}...", theme.TEXT_DIM)

                def done(res, err):
                    out.set_text(("No pude leerla: " + err) if err else ("Se lee bien:\n" + res[:500]),
                                 theme.ERR if err else theme.TEXT)
                _bg(lambda: webtools.read_url(i["url"], cookie=eng.sources.cookie_for(i["url"]), max_chars=500), done)

            def rm(n=it["name"]):
                eng.sources.remove(n)
                refresh()
            card.add_widget(button("Probar", test, "secondary", height=40, size=13, size_hint_x=None, width=dp(72)))
            card.add_widget(button("Quitar", rm, "danger", height=40, size=13, size_hint_x=None, width=dp(72)))
            lst.add_widget(card)
    refresh()

    dlg.add(title("Añadir fuente"))
    name_e = field("Nombre (ej. Clarín, Mi Instagram, Wikipedia)")
    url_e = field("Link (https://...)")
    note_e = field("Para qué sirve (opcional)")
    cookie_e = field("Cookie de sesión (opcional, solo para webs con login)", password=True)
    msg = WLabel("", size=13, color=theme.ERR)
    for w in (name_e, url_e, note_e, cookie_e, msg):
        dlg.add(w)

    def add():
        err = eng.sources.add(name_e.text, url_e.text, cookie_e.text, note_e.text)
        if err:
            msg.set_text(err, theme.ERR)
            return
        msg.set_text("Guardada.", theme.OK if hasattr(theme, "OK") else theme.TEXT)
        for e in (name_e, url_e, note_e, cookie_e):
            e.text = ""
        refresh()
    dlg.add(button("Guardar fuente", add, "primary"))
    dlg.add(out)
    dlg.add(small("La cookie (si la usás) queda solo en este teléfono y solo se envía a esa misma web.", theme.TEXT_FAINT))
    dlg.open()


# ====================================================================== DESCARGAR
def open_downloader(app):
    eng = app.engine
    dlg = Dialog("Descargar")
    dl = eng.downloader
    if dl is None:
        dlg.add(WLabel("El módulo de descargas no se pudo iniciar en esta compilación.", color=theme.ERR))
        dlg.open()
        return
    dlg.add(small("Pegá el link, tocá Analizar y elegí la calidad. Los videos se guardan en Películas/MIIA y el audio "
                  "en Música/MIIA. El audio sale en M4A (no MP3). YouTube muchas veces no deja bajar desde el celular; "
                  "otras webs funcionan mejor. Descargá solo lo que tengas derecho a guardar."))
    url_e = field("Link del video o audio")
    dlg.add(url_e)
    status = WLabel("", size=13, color=theme.TEXT_DIM)
    bar = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(10))
    opts_box = _box()
    state = {"info": None, "busy": False}

    def analyze():
        if state["busy"]:
            return
        state["busy"] = True
        opts_box.clear_widgets()
        status.set_text("Analizando el link...", theme.TEXT_DIM)

        def done(info, err):
            state["busy"] = False
            if err:
                status.set_text(err, theme.ERR)
                return
            state["info"] = info
            mins = f" · {info['duration'] // 60}:{info['duration'] % 60:02d}" if info["duration"] else ""
            status.set_text(f"{info['title']}{mins}\nElegí una calidad:", theme.TEXT)
            for o in info["options"]:
                opts_box.add_widget(button(o["label"], lambda o=o: start(o), "primary" if o["kind"] == "video" else "secondary"))
        _bg(lambda: dl.analyze(url_e.text), done)

    def start(opt):
        if state["busy"]:
            return
        state["busy"] = True
        bar.value = 0
        status.set_text("Descargando...", theme.TEXT_DIM)

        def prog(p, text):
            Clock.schedule_once(lambda dt: (setattr(bar, "value", p * 100), status.set_text("Descargando " + text, theme.TEXT_DIM)), 0)

        def done(res, err):
            state["busy"] = False
            if err:
                status.set_text(err, theme.ERR)
            else:
                bar.value = 100
                status.set_text("Listo. Guardado en: " + str(res[1]), theme.TEXT)

        _bg(lambda: dl.download(state["info"]["url"], opt, prog), done)

    dlg.add(hrow(button("Analizar", analyze, "primary"), button("Cancelar descarga", dl.cancel, "neutral")))
    dlg.add(status)
    dlg.add(bar)
    dlg.add(opts_box)
    dlg.open()


# ====================================================================== CORREO Y AGENDA
def open_mail_agenda(app):
    eng = app.engine
    dlg = Dialog("Correo y agenda")
    dlg.add(title("Correo (Gmail u otro)"))
    dlg.add(small("MIIA puede leer y buscar tus correos sin pedirte permiso, y NO los marca como leídos. Enviar un "
                  "correo siempre te lo pregunta antes. Necesita una «contraseña de aplicación», no tu clave normal: "
                  "Cuenta de Google > Seguridad > Verificación en 2 pasos (actívala) > Contraseñas de aplicaciones."))
    mb = eng.mailbox
    addr_e = field("Tu correo (ej. nombre@gmail.com)", text=mb.address)
    pass_e = field("Contraseña de aplicación (16 letras)", password=True)
    imap_e = field("Servidor IMAP (solo si no es Gmail/Outlook/Yahoo/iCloud)")
    out = WLabel("", size=13, color=theme.TEXT_DIM)

    def say(res, err):
        out.set_text(err or str(res), theme.ERR if err else theme.TEXT)

    def save_mail():
        try:
            mb.configure(addr_e.text, pass_e.text or (mb._cfg().get("password", "") if mb.address == addr_e.text.strip() else ""),
                         imap_e.text)
            pass_e.text = ""
            out.set_text("Guardado. Probando la conexión...", theme.TEXT_DIM)
            _bg(mb.test, say)
        except MailError as e:
            out.set_text(str(e), theme.ERR)

    def forget_mail():
        mb.clear()
        addr_e.text = ""
        out.set_text("Correo olvidado.", theme.TEXT)
    for w in (addr_e, pass_e, imap_e, hrow(button("Guardar y probar", save_mail, "primary"),
                                           button("Olvidar", forget_mail, "danger"))):
        dlg.add(w)

    dlg.add(spacer(10))
    dlg.add(title("Agenda (Calendario de Google)"))
    dlg.add(small("En Google Calendar (web) > Configuración del calendario > «Dirección secreta en formato iCal». "
                  "Copiala y pegala acá: MIIA solo lee. Esa dirección es privada, no la compartas. Para crear "
                  "reuniones, MIIA abre el calendario del teléfono con los datos y vos confirmás."))
    ag = eng.agenda
    ical_e = field("Dirección secreta iCal (https://calendar.google.com/...ics)", password=True)

    def save_ical():
        try:
            ag.set_url(ical_e.text)
        except webtools.WebError as e:
            out.set_text(str(e), theme.ERR)
            return
        ical_e.text = ""
        out.set_text("Guardada. Probando...", theme.TEXT_DIM)
        _bg(ag.test, say)

    def forget_ical():
        ag.set_url("")
        out.set_text("Agenda olvidada.", theme.TEXT)
    dlg.add(ical_e)
    dlg.add(hrow(button("Guardar y probar", save_ical, "primary"), button("Olvidar", forget_ical, "danger")))

    dlg.add(spacer(10))
    dlg.add(title("Probar internet"))
    q_e = field("Algo para buscar (ej. dólar hoy)")
    dlg.add(q_e)
    dlg.add(button("Buscar en internet", lambda: (out.set_text("Buscando...", theme.TEXT_DIM),
                                                   _bg(lambda: webtools.search_text(q_e.text or "noticias", 4), say)), "secondary"))
    dlg.add(out)
    dlg.add(small("Todo se guarda solo en este teléfono (miia_secrets.json) y nunca se sube a GitHub.", theme.TEXT_FAINT))
    dlg.open()
