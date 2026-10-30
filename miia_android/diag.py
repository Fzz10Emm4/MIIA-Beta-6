"""Diagnóstico: comprueba conexión segura, voz y permisos, y muestra el error técnico real."""

import os
import socket
import ssl
import urllib.request

from .util import IS_ANDROID, LOG_TAIL, has_audio_permission


def _http(url, timeout=15):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "MIIA-diag"}), timeout=timeout) as r:
            return f"OK (HTTP {r.status})"
    except Exception as e:
        return f"FALLÓ -> {type(e).__name__}: {e}"


def run(engine=None) -> str:
    out = []

    def add(k, v):
        out.append(f"{k}: {v}")
    add("Android", IS_ANDROID)
    add("ssl", getattr(ssl, "OPENSSL_VERSION", "NO DISPONIBLE"))
    try:
        import certifi
        ca = certifi.where()
        add("certifi", f"{ca} (existe: {os.path.exists(ca)})")
    except Exception as e:
        add("certifi", f"NO se pudo importar: {e}")
    add("SSL_CERT_FILE", os.environ.get("SSL_CERT_FILE"))
    add("certificados del sistema", os.path.isdir("/system/etc/security/cacerts"))
    try:
        add("DNS openrouter.ai", socket.gethostbyname("openrouter.ai"))
    except Exception as e:
        add("DNS openrouter.ai", f"FALLÓ -> {e}")
    add("HTTP sin cifrar (gstatic)", _http("http://connectivitycheck.gstatic.com/generate_204", 10))
    add("HTTPS openrouter.ai", _http("https://openrouter.ai/api/v1/models"))
    add("HTTPS google.com", _http("https://www.google.com/generate_204", 10))
    if engine is not None:
        add("micrófono (permiso)", has_audio_permission())
        try:
            add("reconocimiento de voz disponible", engine.bridge.available())
        except Exception as e:
            add("reconocimiento de voz disponible", f"error {e}")
        try:
            add("batería sin restricciones", engine.bridge.battery_ok())
        except Exception as e:
            add("batería", f"error {e}")
        add("estado de la voz", engine.voice.state)
        eng = engine.speaker.engine
        if eng is None:
            add("voz offline", "no disponible en este equipo (solo existe en el teléfono)")
        else:
            from .sherpa import model_present, speaker_ids
            add("voz offline: modelo incluido", model_present(eng.model_dir))
            add("voz offline: voces del modelo", speaker_ids(eng.model_dir) or "una sola")
            eng.start_loading()
            try:
                import time
                t0 = time.time()
                eng.synth("Hola.", 1.0, 30)                      # calentamiento (la primera vez es más lenta)
                t0 = time.time()
                audio = eng.synth("Hoy tienes tres tareas pendientes y una reunión a las cinco de la tarde.", 1.0, 30)
                took = time.time() - t0
                secs = max(0.01, (len(audio) - 44) / 2.0 / max(1, eng.sample_rate))
                add("prueba de la voz offline",
                    f"OK: {secs:.1f} s de audio generados en {took:.1f} s (factor {took / secs:.2f}; "
                    f"menos de 1 = más rápido que hablar)")
            except Exception as e:
                add("prueba de la voz offline", f"FALLÓ -> {e}")
            add("voz offline: motor", f"{eng.kind or '?'}, {eng.sample_rate} Hz, cargó en {eng.load_seconds:.1f} s")
            add("voz offline: último error", eng.last_error or "(ninguno)")
    out.append("")
    out.append("--- últimas líneas del registro ---")
    out.extend(list(LOG_TAIL)[-40:])
    return "\n".join(out)
