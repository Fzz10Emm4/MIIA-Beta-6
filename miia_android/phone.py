"""Acciones sobre el teléfono: abrir apps y links, compartir texto, crear eventos de calendario, guardar descargas
en Música/Películas y poner la hora local.  En un PC (o si algo falla) se usa NullPhone, que solo avisa.

Las clases de Android del sistema se pueden usar desde cualquier hilo; ninguna clase propia de la app se necesita
aquí, así que no hay el problema de cargador de clases que tuvo la voz.
"""

import datetime as dt
import os
import shutil
import time

from .util import IS_ANDROID, activity, autoclass, log, log_exc, norm


class PhoneError(Exception):
    pass


def posix_tz(offset_seconds: int) -> str:
    """Offset UTC (segundos, positivo al este) -> variable TZ de POSIX (invierte el signo): -10800 -> 'UTC3'."""
    secs = -int(offset_seconds)
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    h, m = secs // 3600, (secs % 3600) // 60
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def setup_timezone() -> str:
    """En Android Python no conoce la zona horaria y usa UTC: la copia del sistema. Devuelve lo que puso ('' si nada)."""
    if not IS_ANDROID:
        return ""
    try:
        tz = autoclass("java.util.TimeZone").getDefault()
        off = int(tz.getOffset(int(time.time() * 1000))) // 1000
        os.environ["TZ"] = posix_tz(off)
        time.tzset()
        log("Zona horaria:", os.environ["TZ"], str(tz.getID()))
        return os.environ["TZ"]
    except Exception:
        log_exc("setup_timezone")
        return ""


class NullPhone:
    """Para el PC y las pruebas: guarda lo pedido en .calls y no hace nada más."""
    available = False

    def __init__(self):
        self.calls = []
        self.apps = {"whatsapp": "WhatsApp", "calculadora": "Calculadora"}

    def open_url(self, url):
        self.calls.append(("open_url", url))
        return f"(PC) abriría {url}"

    def open_app(self, name):
        self.calls.append(("open_app", name))
        key = norm(name)
        for k, v in self.apps.items():
            if key in k or k in key:
                return f"(PC) abriría la app {v}"
        raise PhoneError(f"No encontré una app llamada «{name}».")

    def share_text(self, text, app=""):
        self.calls.append(("share_text", text, app))
        return "(PC) compartiría el texto"

    def add_calendar_event(self, title, start, end=None, where="", notes=""):
        self.calls.append(("calendar", title, start, end, where, notes))
        return "(PC) abriría el calendario con el evento"

    def publish_media(self, path, kind):
        self.calls.append(("publish", path, kind))
        return path


class PhoneActions:
    available = True

    def __init__(self):
        self._apps = None

    # ---- links y apps ----
    def _start(self, intent):
        from jnius import autoclass as _ac
        intent.addFlags(_ac("android.content.Intent").FLAG_ACTIVITY_NEW_TASK)
        activity().startActivity(intent)

    def open_url(self, url):
        Intent, Uri = autoclass("android.content.Intent"), autoclass("android.net.Uri")
        self._start(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        return f"Abrí {url}"

    def _load_apps(self):
        Intent = autoclass("android.content.Intent")
        pm = activity().getPackageManager()
        i = Intent(Intent.ACTION_MAIN)
        i.addCategory(Intent.CATEGORY_LAUNCHER)
        apps = {}
        for ri in pm.queryIntentActivities(i, 0).toArray():
            label = str(ri.loadLabel(pm))
            apps[label] = str(ri.activityInfo.packageName)
        self._apps = apps
        return apps

    def installed_apps(self):
        return sorted((self._apps or self._load_apps()).keys())

    def open_app(self, name):
        apps = self._apps or self._load_apps()
        key = norm(name)
        match = [l for l in apps if norm(l) == key] or [l for l in apps if key and (key in norm(l) or norm(l) in key)]
        if not match:
            self._load_apps()                # puede haberse instalado algo nuevo
            apps = self._apps
            match = [l for l in apps if norm(l) == key] or [l for l in apps if key and key in norm(l)]
        if not match:
            raise PhoneError(f"No encontré una app llamada «{name}» en el teléfono.")
        label = match[0]
        intent = activity().getPackageManager().getLaunchIntentForPackage(apps[label])
        if intent is None:
            raise PhoneError(f"No pude abrir «{label}».")
        self._start(intent)
        return f"Abrí la app {label}."

    def share_text(self, text, app=""):
        Intent = autoclass("android.content.Intent")
        i = Intent(Intent.ACTION_SEND)
        i.setType("text/plain")
        i.putExtra(Intent.EXTRA_TEXT, text)
        if app:
            apps = self._apps or self._load_apps()
            key = norm(app)
            lab = next((l for l in apps if key and key in norm(l)), None)
            if lab:
                i.setPackage(apps[lab])
        self._start(Intent.createChooser(i, "Compartir con..."))
        return "Abrí el menú de compartir con el texto listo; falta que elijas a quién y toques enviar."

    def add_calendar_event(self, title, start, end=None, where="", notes=""):
        """Abre el calendario del teléfono con el evento ya cargado; el usuario toca «Guardar»."""
        Intent = autoclass("android.content.Intent")
        CC = autoclass("android.provider.CalendarContract")
        end = end or (start + dt.timedelta(hours=1))
        i = Intent(Intent.ACTION_INSERT)
        i.setData(autoclass("android.provider.CalendarContract$Events").CONTENT_URI)
        i.putExtra("title", title)
        i.putExtra("beginTime", int(time.mktime(start.timetuple()) * 1000))
        i.putExtra("endTime", int(time.mktime(end.timetuple()) * 1000))
        if where:
            i.putExtra("eventLocation", where)
        if notes:
            i.putExtra("description", notes)
        self._start(i)
        return "Abrí el calendario con el evento cargado; falta que toques «Guardar»."

    # ---- descargas: copiar a Música / Películas con MediaStore ----
    def publish_media(self, path, kind):
        """Copia el archivo a Music/MIIA o Movies/MIIA y devuelve una descripción de dónde quedó."""
        if not IS_ANDROID:
            return path
        try:
            sdk = int(autoclass("android.os.Build$VERSION").SDK_INT)
            name = os.path.basename(path)
            mime = "audio/mp4" if kind == "audio" else "video/mp4"
            rel = ("Music" if kind == "audio" else "Movies") + "/MIIA"
            if sdk >= 29:
                CV = autoclass("android.content.ContentValues")
                MS = autoclass("android.provider.MediaStore$Audio$Media" if kind == "audio"
                               else "android.provider.MediaStore$Video$Media")
                cv = CV()
                cv.put("_display_name", name)
                cv.put("mime_type", mime)
                cv.put("relative_path", rel)
                cv.put("is_pending", 1)
                res = activity().getContentResolver()
                uri = res.insert(MS.EXTERNAL_CONTENT_URI, cv)
                if uri is None:
                    raise PhoneError("Android no me dejó crear el archivo")
                out = res.openOutputStream(uri)
                try:
                    with open(path, "rb") as f:
                        while True:
                            chunk = f.read(1 << 18)
                            if not chunk:
                                break
                            out.write(chunk)
                finally:
                    out.close()
                cv2 = CV()
                cv2.put("is_pending", 0)
                res.update(uri, cv2, None, None)
                return f"{rel}/{name}"
            env = autoclass("android.os.Environment")
            base = str(env.getExternalStoragePublicDirectory(
                env.DIRECTORY_MUSIC if kind == "audio" else env.DIRECTORY_MOVIES).getAbsolutePath())
            dest = os.path.join(base, "MIIA")
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(path, os.path.join(dest, name))
            return f"{rel}/{name}"
        except PhoneError:
            raise
        except Exception as e:
            log_exc("publish_media")
            raise PhoneError(f"No pude copiarlo a Música/Películas ({e}); queda en la carpeta privada de MIIA.")


def build_phone():
    return PhoneActions() if IS_ANDROID else NullPhone()
