"""Fuentes: webs y redes que el usuario le da a MIIA (nombre + link) para que las consulte al responder.

Guardado en miia_sources.json (solo en el teléfono; puede incluir una cookie opcional para sitios con sesión, así que
el archivo es privado y nunca se sube a GitHub).
"""

import re
import threading
from pathlib import Path

import miia_core as core

from . import webtools
from .webtools import WebError

SOCIAL_HOSTS = ("instagram.com", "facebook.com", "x.com", "twitter.com", "tiktok.com", "linkedin.com", "threads.net")


class SourceStore:
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        data = core._load_json(self.path, []) if self.path else []
        self.items = [d for d in data if isinstance(d, dict) and d.get("name") and d.get("url")] \
            if isinstance(data, list) else []

    def _save(self):
        if self.path:
            core._atomic_write_json(self.path, self.items, private=True)

    # ---- altas y bajas ----
    def add(self, name, url, cookie="", note=""):
        """'' si quedó guardada; si no, el motivo."""
        name = re.sub(r"[^\w\-. ]", "", (name or "").strip())[:40].strip()
        if not name:
            return "Falta el nombre (por ejemplo: «Diario Clarín» o «Mi Instagram»)."
        try:
            u = webtools.normalize_url(url)
        except WebError as e:
            return str(e)
        with self.lock:
            self.items = [i for i in self.items if i["name"].lower() != name.lower()]     # mismo nombre = reemplaza
            self.items.append({"name": name, "url": u, "cookie": (cookie or "").strip(), "note": (note or "").strip()[:300]})
            self._save()
        return ""

    def remove(self, name):
        with self.lock:
            self.items = [i for i in self.items if i["name"].lower() != (name or "").lower()]
            self._save()

    # ---- consultas ----
    def list(self):
        with self.lock:
            return [dict(i) for i in self.items]

    def find(self, name_or_url):
        """Busca por nombre (sin mayúsculas ni tildes), por parte del nombre o por dominio."""
        key = core_norm(name_or_url)
        if not key:
            return None
        with self.lock:
            for i in self.items:
                if core_norm(i["name"]) == key:
                    return dict(i)
            for i in self.items:
                if key in core_norm(i["name"]) or core_norm(i["name"]) in key:
                    return dict(i)
            host = webtools.host_of(name_or_url)
            if host:
                for i in self.items:
                    if webtools.host_of(i["url"]) == host:
                        return dict(i)
        return None

    def cookie_for(self, url) -> str:
        """Cookie guardada para el dominio de ese link (solo se manda al MISMO dominio)."""
        host = webtools.host_of(url)
        if not host:
            return ""
        with self.lock:
            for i in self.items:
                h = webtools.host_of(i["url"])
                if i.get("cookie") and (host == h or host.endswith("." + h)):
                    return i["cookie"]
        return ""

    def summary(self) -> str:
        with self.lock:
            return "\n".join(f"- {i['name']}: {i['url']}" + (f" ({i['note']})" if i.get("note") else "")
                             for i in self.items)

    @staticmethod
    def is_social(url) -> bool:
        h = webtools.host_of(url)
        return any(h == s or h.endswith("." + s) for s in SOCIAL_HOSTS)


def core_norm(text) -> str:
    from .util import norm
    return norm(text)
