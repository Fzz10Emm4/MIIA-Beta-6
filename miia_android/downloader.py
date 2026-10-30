"""Descargador: pegás un link, MIIA lo analiza (yt-dlp) y bajás el video (mp4) o solo el audio (m4a) con la calidad elegida.

Límites honestos de esta versión (no hay ffmpeg en el teléfono):
- Video: solo formatos «progresivos» (imagen y sonido juntos), que suelen llegar a 360p-720p. Las calidades más altas
  de YouTube vienen con el audio aparte y necesitarían ffmpeg para unirse.
- Audio: queda en M4A (suena igual que un MP3 y lo reproduce cualquier celular), no se convierte a MP3.
- YouTube cambia seguido y a veces bloquea; otros sitios (Vimeo, TikTok, Facebook público, archivos directos...) suelen ir mejor.
- Solo para contenido que tengas derecho a guardar.
"""

import os
import re
import threading

from . import webtools
from .util import log, log_exc


class DownloadError(Exception):
    pass


def _yt():
    try:
        import yt_dlp
        return yt_dlp
    except Exception as e:
        raise DownloadError(f"Falta el componente de descargas (yt-dlp): {e}")


def friendly(e) -> str:
    m = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    low = m.lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return "YouTube pidió comprobar que no soy un robot y no me deja bajarlo desde acá. Probá con otro sitio o más tarde."
    if "unsupported url" in low:
        return "Ese link no lo reconozco como un video o audio descargable."
    if "private" in low or "login" in low or "log in" in low:
        return "Ese contenido es privado o pide iniciar sesión. Si es una de tus Fuentes con cookie, puede que haya vencido."
    if "javascript runtime" in low or "js runtime" in low or "n challenge" in low:
        return "YouTube exige un componente extra que este celular no tiene, así que esa web no se puede bajar desde la app."
    if "ffmpeg" in low:
        return "Ese formato necesita ffmpeg (aún no incluido). Probá otra calidad."
    if "http error 403" in low or "http error 429" in low:
        return "El sitio rechazó la descarga (403/429). Probá de nuevo más tarde."
    return m.replace("ERROR: ", "")[:240]


def _size_text(n):
    return f"{n / 1e6:.0f} MB" if n and n > 5e5 else ""


def build_options(info: dict):
    """Lista de opciones [{id,label,kind,format,ext,height}] a partir de la info de yt-dlp."""
    fmts = info.get("formats") or []
    opts, seen = [], set()
    heights = sorted({int(f["height"]) for f in fmts
                      if f.get("height") and f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none")},
                     reverse=True)
    for h in heights:
        best = [f for f in fmts if f.get("height") == h and f.get("vcodec") not in (None, "none")
                and f.get("acodec") not in (None, "none")]
        mp4 = [f for f in best if f.get("ext") == "mp4"]
        pick = (mp4 or best)[-1]
        if h in seen:
            continue
        seen.add(h)
        sel = f"{pick['format_id']}"
        opts.append({"id": f"v{h}", "kind": "video", "label": f"Video {h}p ({pick.get('ext', 'mp4')})" +
                     (f" · {_size_text(pick.get('filesize') or pick.get('filesize_approx'))}" if
                      _size_text(pick.get('filesize') or pick.get('filesize_approx')) else ""),
                     "format": sel, "ext": pick.get("ext", "mp4"), "height": h})
    if not opts and fmts and info.get("url"):                    # enlace directo / un solo formato
        opts.append({"id": "vbest", "kind": "video", "label": "Video (calidad original)", "format": "best",
                     "ext": info.get("ext", "mp4"), "height": int(info.get("height") or 0)})
    audio = [f for f in fmts if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")]
    m4a = [f for f in audio if f.get("ext") == "m4a"]
    if audio:
        a = (m4a or audio)
        a = sorted(a, key=lambda f: f.get("abr") or 0)[-1]
        abr = f"{int(a['abr'])} kbps" if a.get("abr") else "mejor calidad"
        opts.append({"id": "a-best", "kind": "audio", "label": f"Solo audio ({a.get('ext', 'm4a')}, {abr})",
                     "format": a["format_id"], "ext": a.get("ext", "m4a"), "height": 0})
    elif opts:
        pass                                                      # sin pista de audio suelta: solo video
    return opts


class Downloader:
    def __init__(self, out_dir, phone, sources=None):
        self.out_dir, self.phone, self.sources = out_dir, phone, sources
        os.makedirs(out_dir, exist_ok=True)
        self.cancel_event = threading.Event()
        self.busy = threading.Lock()

    def _base_opts(self, url):
        opts = {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 25, "retries": 3,
                "noplaylist": True, "outtmpl": os.path.join(self.out_dir, "%(title).80B [%(id)s].%(ext)s"),
                "restrictfilenames": False, "windowsfilenames": True, "nocheckcertificate": False,
                "http_headers": {}}
        cookie = self.sources.cookie_for(url) if self.sources else ""
        if cookie:
            opts["http_headers"]["Cookie"] = cookie
        return opts

    def analyze(self, url):
        """-> {title, uploader, duration, options}. Lanza DownloadError con un texto para mostrar."""
        try:
            url = webtools.normalize_url(url)
            webtools.check_public(url)
        except webtools.WebError as e:
            raise DownloadError(str(e))
        yt = _yt()
        try:
            with yt.YoutubeDL(dict(self._base_opts(url), skip_download=True)) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise DownloadError(friendly(e))
        if not info:
            raise DownloadError("No encontré nada descargable en ese link.")
        if info.get("_type") == "playlist" and info.get("entries"):
            info = next((x for x in info["entries"] if x), info)
        opts = build_options(info)
        if not opts:
            raise DownloadError("Ese link no ofrece ninguna calidad que pueda bajar sin ffmpeg.")
        return {"url": url, "title": info.get("title") or "Sin título", "uploader": info.get("uploader") or "",
                "duration": int(info.get("duration") or 0), "options": opts}

    def cancel(self):
        self.cancel_event.set()

    def download(self, url, option, on_progress=None):
        """Descarga la opción elegida. -> (ruta_privada, ubicación_publicada_o_texto). on_progress(0..1, texto)."""
        if not self.busy.acquire(blocking=False):
            raise DownloadError("Ya hay una descarga en curso.")
        self.cancel_event.clear()
        try:
            yt = _yt()

            def hook(d):
                if self.cancel_event.is_set():
                    raise yt.utils.DownloadCancelled("cancelado")
                if on_progress and d.get("status") == "downloading":
                    tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    done = d.get("downloaded_bytes") or 0
                    pct = (done / tot) if tot else 0.0
                    speed = d.get("speed")
                    on_progress(min(pct, 0.99), f"{pct * 100:.0f}%" + (f" · {speed / 1e6:.1f} MB/s" if speed else ""))

            opts = dict(self._base_opts(url), format=option["format"], progress_hooks=[hook])
            try:
                with yt.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    path = ydl.prepare_filename(info)
            except yt.utils.DownloadCancelled:
                raise DownloadError("Descarga cancelada.")
            except Exception as e:
                if self.cancel_event.is_set():
                    raise DownloadError("Descarga cancelada.")
                raise DownloadError(friendly(e))
            if not os.path.isfile(path):
                cands = [os.path.join(self.out_dir, f) for f in os.listdir(self.out_dir)]
                path = max(cands, key=os.path.getmtime) if cands else ""
            if not path or not os.path.isfile(path) or os.path.getsize(path) < 1000:
                raise DownloadError("La descarga terminó pero el archivo quedó vacío.")
            if on_progress:
                on_progress(1.0, "Guardando...")
            try:
                where = self.phone.publish_media(path, option["kind"])
                if where != path and not where.startswith(path):       # ya está en Música/Películas: sobra la copia privada
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            except Exception as e:
                log_exc("publicar")
                where = f"{path} ({e})"
            return path, where
        finally:
            self.busy.release()
