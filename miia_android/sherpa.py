"""Voz offline de MIIA: sherpa-onnx con una voz Piper en español, dentro del teléfono.

Reemplaza a Edge TTS: no necesita internet, ni cuenta, ni claves, ni tokens, y no depende de que Microsoft cambie
nada. La síntesis ocurre en org.miia.voice.MiiaTts (Java); aquí solo se carga el modelo en segundo plano y se pide
audio trozo a trozo. El modelo (carpeta «voice_model») lo copia a la app el workflow de compilación.
"""

import json
import os
import threading

from .util import IS_ANDROID, autoclass, log, log_exc

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(APP_DIR, "voice_model")


class VoiceError(Exception):
    pass


def model_present(model_dir=MODEL_DIR) -> bool:
    try:
        names = os.listdir(model_dir)
    except OSError:
        return False
    has_onnx = any(n.endswith(".onnx") for n in names)
    return has_onnx and "tokens.txt" in names and os.path.isdir(os.path.join(model_dir, "espeak-ng-data"))


def speaker_ids(model_dir=MODEL_DIR) -> dict:
    """Voces de un modelo Piper, p. ej. {'M': 0, 'F': 1}. Vacío si el modelo tiene una sola."""
    try:
        for n in os.listdir(model_dir):
            if n.endswith(".onnx.json"):
                with open(os.path.join(model_dir, n), "r", encoding="utf-8") as f:
                    m = json.load(f).get("speaker_id_map") or {}
                return {str(k): int(v) for k, v in m.items()}
    except Exception:
        log_exc("speaker_ids")
    return {}


def pick_voice(model_dir, gender: str) -> int:
    """'mujer' / 'hombre' -> número de voz del modelo (0 si el modelo solo tiene una)."""
    ids = speaker_ids(model_dir)
    if not ids:
        return 0
    key = "M" if (gender or "mujer").strip().lower() in ("hombre", "m", "masculina", "male") else "F"
    return ids.get(key, next(iter(ids.values())))


class SherpaTTS:
    """load() corre en un hilo al abrir la app (leer el modelo tarda unos segundos); synth() espera a que esté lista."""

    def __init__(self, cfg, cache_dir, model_dir=MODEL_DIR, java=None, load_timeout=90.0):
        self.cfg, self.cache_dir, self.model_dir = cfg, cache_dir, model_dir
        self._java = java
        self._ready = threading.Event()
        self._started = False
        self._lock = threading.Lock()
        self._n = 0
        self.load_timeout = load_timeout
        self.last_error = ""
        self.load_seconds = 0.0
        self.sample_rate = 0
        self.kind = ""
        self.speakers = 0
        self._class_error = ""
        # IMPORTANTE: en Android las clases de la app solo se encuentran desde el hilo principal (los hilos creados
        # por Python usan otro cargador de clases y dan ClassNotFoundException). Por eso la clase se busca AQUÍ,
        # que se ejecuta al abrir la app en el hilo principal, y no dentro del hilo de carga.
        if self._java is None and IS_ANDROID:
            try:
                self._java = autoclass("org.miia.voice.MiiaTts")
            except Exception as e:
                self._class_error = f"{type(e).__name__}: {e}"
                log("No encontré la clase Java de la voz:", self._class_error)

    # ---- carga ----
    def _jvm(self):
        if self._java is None:
            if self._class_error:
                raise VoiceError("No encuentro la clase Java de la voz (MiiaTts): " + self._class_error)
            self._java = autoclass("org.miia.voice.MiiaTts")
        return self._java

    def start_loading(self):
        """Empieza a cargar en segundo plano (varias llamadas = una sola carga)."""
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        import time
        t0 = time.time()
        try:
            if not model_present(self.model_dir):
                raise VoiceError("La voz offline no viene en esta compilación (falta la carpeta voice_model).")
            V = self._jvm()
            threads = int(self.cfg.get("voice_threads") or 4) if self.cfg else 4
            err = str(V.load(self.model_dir, threads) or "")
            if err:
                raise VoiceError(err)
            self.sample_rate = int(V.sampleRate())
            self.speakers = int(V.numSpeakers())
            self.kind = str(V.kind())
            self.load_seconds = time.time() - t0
            log(f"Voz offline lista ({self.kind}, {self.sample_rate} Hz, {self.speakers} voces) en "
                f"{self.load_seconds:.1f} s")
            self._ready.set()
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}" if not isinstance(e, VoiceError) else str(e)
            log("Voz offline no cargó:", self.last_error)
            self._ready.set()           # despierta a quien espera; synth() verá el error

    @property
    def loaded(self) -> bool:
        return self._ready.is_set() and not self.last_error

    @property
    def failed(self) -> bool:
        return self._ready.is_set() and bool(self.last_error)

    # ---- síntesis ----
    def synth(self, text: str, speed: float = 1.0, wait=None) -> bytes:
        """WAV (bytes) del texto. Lanza VoiceError si la voz no está disponible.
        wait: segundos máximos a esperar si el modelo aún está cargando (por defecto, load_timeout)."""
        self.start_loading()
        if not self._ready.wait(self.load_timeout if wait is None else wait):
            raise VoiceError("La voz offline sigue cargando")
        if self.last_error:
            raise VoiceError(self.last_error)
        voice = pick_voice(self.model_dir, (self.cfg.get("voice_gender") if self.cfg else None) or "mujer")
        self._n = (self._n + 1) % 6
        path = os.path.join(self.cache_dir, f"tts_{self._n}.wav")
        n = int(self._jvm().synthToWav(text, int(voice), float(speed), path))
        if n <= 0:
            err = str(self._jvm().lastError() or "") if n < 0 else "sin audio"
            raise VoiceError(f"La voz offline falló ({n}): {err}")
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 100:
            raise VoiceError("La voz offline devolvió un audio vacío")
        return data


def is_wav(audio: bytes) -> bool:
    return audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
