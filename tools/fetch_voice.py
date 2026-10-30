#!/usr/bin/env python3
"""Prepara la voz offline de MIIA durante la compilación (la usa el workflow de GitHub Actions).

Baja de GitHub, con la versión FIJA de sherpa-onnx (v1.13.8: es la última que trae el fonemizador espeak-ng que
necesitan las voces Piper en español; la 2.x lo quitó):
  1) las librerías nativas de Android (libonnxruntime.so y libsherpa-onnx-jni.so) -> voice_libs/<arquitectura>/
  2) el código Java de la API de sherpa-onnx (15 archivos, con git)               -> java_src/com/k2fsa/sherpa/onnx/
  3) la voz (modelo Piper + tokens + espeak-ng-data)                             -> voice_model/

Si algo falla, termina con error y un mensaje claro: así no se produce un APK mudo sin darnos cuenta.

Uso:  python tools/fetch_voice.py [--model vits-piper-es_ES-sharvard-medium] [--archs armeabi-v7a] [--root .]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

SHERPA_TAG = "v1.13.8"
DEFAULT_MODEL = "vits-piper-es_ES-sharvard-medium"
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
JAVA_DIR = "sherpa-onnx/java-api/src/main/java/com/k2fsa/sherpa/onnx"

# Las clases que necesita org.miia.voice.MiiaTts (se comprobó compilándola con javac contra esta versión).
JAVA_FILES = [
    "GeneratedAudio", "GenerationConfig", "LibraryLoader", "LibraryUtils",
    "OfflineTts", "OfflineTtsCallback", "OfflineTtsConfig", "OfflineTtsModelConfig",
    "OfflineTtsKittenModelConfig", "OfflineTtsKokoroModelConfig", "OfflineTtsMatchaModelConfig",
    "OfflineTtsPocketModelConfig", "OfflineTtsSupertonicModelConfig", "OfflineTtsVitsModelConfig",
    "OfflineTtsZipVoiceModelConfig",
]
NATIVE_LIBS = ["libonnxruntime.so", "libsherpa-onnx-jni.so"]
# De la carpeta del modelo solo se copia esto (el resto —diccionarios de chino, etc.— no se usa).
MODEL_KEEP_SUFFIX = (".onnx", ".onnx.json")
MODEL_KEEP_NAMES = {"tokens.txt", "espeak-ng-data", "voices.bin", "lexicon-us-en.txt", "MODEL_CARD", "LICENSE"}


def log(*a):
    print("[fetch_voice]", *a, flush=True)


def die(msg):
    raise SystemExit(f"fetch_voice: ERROR: {msg}")


def download(url, dest, tries=5, min_bytes=1000):
    last = None
    for i in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MIIA-build"})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            if os.path.getsize(dest) < min_bytes:
                raise IOError(f"descarga demasiado pequeña ({os.path.getsize(dest)} bytes)")
            return
        except Exception as e:      # red, 5xx, archivo cortado...
            last = e
            log(f"intento {i}/{tries} falló para {url}: {e}")
            time.sleep(min(30, 3 * i))
    die(f"no pude bajar {url}: {last}")


def safe_extract(tar_path, dest):
    with tarfile.open(tar_path, "r:bz2") as tf:
        root = os.path.realpath(dest)
        for m in tf.getmembers():
            target = os.path.realpath(os.path.join(dest, m.name))
            if not (target == root or target.startswith(root + os.sep)):
                die(f"el archivo {tar_path} trae una ruta peligrosa: {m.name}")
            if m.issym() or m.islnk() or m.isdev():
                die(f"el archivo {tar_path} trae un enlace o dispositivo inesperado: {m.name}")
        try:
            tf.extractall(dest, filter="data")
        except TypeError:          # Python sin el parámetro filter
            tf.extractall(dest)


def fetch_libs(root, archs, tmp):
    tar = os.path.join(tmp, "android.tar.bz2")
    url = f"{RELEASES}/{SHERPA_TAG}/sherpa-onnx-{SHERPA_TAG}-android.tar.bz2"
    log("bajando librerías de Android:", url)
    download(url, tar, min_bytes=1_000_000)
    ex = os.path.join(tmp, "android")
    os.makedirs(ex)
    safe_extract(tar, ex)
    for arch in archs:
        src = os.path.join(ex, "jniLibs", arch)
        dst = os.path.join(root, "voice_libs", arch)
        shutil.rmtree(dst, ignore_errors=True)
        os.makedirs(dst)
        for lib in NATIVE_LIBS:
            p = os.path.join(src, lib)
            if not os.path.isfile(p) or os.path.getsize(p) < 100_000:
                die(f"falta {lib} para {arch} en el paquete de sherpa-onnx")
            shutil.copy2(p, dst)
        log(f"  {arch}: {', '.join(NATIVE_LIBS)}")


def fetch_java(root, tmp):
    """Clon parcial de git (solo la carpeta de la API Java, ~1 MB) en la versión fija."""
    repo = os.path.join(tmp, "sherpa_src")
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    cmds = [
        ["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse", "--branch", SHERPA_TAG,
         "https://github.com/k2-fsa/sherpa-onnx", repo],
        ["git", "-C", repo, "sparse-checkout", "set", JAVA_DIR],
    ]
    for attempt in range(1, 4):
        shutil.rmtree(repo, ignore_errors=True)
        if all(subprocess.run(c, env=env).returncode == 0 for c in cmds):
            break
        log(f"intento {attempt}/3 del clon falló")
        time.sleep(5 * attempt)
    else:
        die("no pude clonar sherpa-onnx " + SHERPA_TAG)
    src = os.path.join(repo, JAVA_DIR)
    dst = os.path.join(root, "java_src", "com", "k2fsa", "sherpa", "onnx")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for name in JAVA_FILES:
        p = os.path.join(src, name + ".java")
        if not os.path.isfile(p):
            die(f"sherpa-onnx {SHERPA_TAG} no trae {name}.java")
        with open(p, "r", encoding="utf-8") as f:
            if "package com.k2fsa.sherpa.onnx;" not in f.read():
                die(f"{name}.java no parece el archivo correcto")
        shutil.copy2(p, dst)
    log(f"  {len(JAVA_FILES)} archivos Java en {os.path.relpath(dst, root)}")


def fetch_model(root, model, tmp):
    tar = os.path.join(tmp, "model.tar.bz2")
    url = f"{RELEASES}/tts-models/{model}.tar.bz2"
    log("bajando la voz:", url)
    download(url, tar, min_bytes=1_000_000)
    ex = os.path.join(tmp, "model")
    os.makedirs(ex)
    safe_extract(tar, ex)
    inner = os.path.join(ex, model)
    if not os.path.isdir(inner):
        dirs = [d for d in os.listdir(ex) if os.path.isdir(os.path.join(ex, d))]
        if len(dirs) != 1:
            die(f"no encontré la carpeta del modelo dentro de {model}.tar.bz2")
        inner = os.path.join(ex, dirs[0])
    dst = os.path.join(root, "voice_model")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for name in sorted(os.listdir(inner)):
        if name in MODEL_KEEP_NAMES or name.endswith(MODEL_KEEP_SUFFIX):
            p = os.path.join(inner, name)
            if os.path.isdir(p):
                shutil.copytree(p, os.path.join(dst, name))
            else:
                shutil.copy2(p, dst)
    validate_model(dst)


def validate_model(dst):
    names = os.listdir(dst)
    onnx = [n for n in names if n.endswith(".onnx")]
    if not onnx:
        die("la voz no trae archivo .onnx")
    if os.path.getsize(os.path.join(dst, onnx[0])) < 1_000_000:
        die("el archivo .onnx de la voz es sospechosamente pequeño")
    if "tokens.txt" not in names:
        die("la voz no trae tokens.txt")
    es = os.path.join(dst, "espeak-ng-data")
    if not os.path.isfile(os.path.join(es, "es_dict")) or not os.path.isfile(os.path.join(es, "phontab")):
        die("espeak-ng-data no trae el diccionario de español (es_dict) o phontab")
    mb = sum(os.path.getsize(os.path.join(d, f)) for d, _s, fs in os.walk(dst) for f in fs) / 1e6
    log(f"  voz lista en voice_model/: {', '.join(sorted(names))} ({mb:.0f} MB)")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=os.environ.get("MIIA_VOICE_MODEL") or DEFAULT_MODEL,
                    help="nombre del modelo en https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models")
    ap.add_argument("--archs", default="armeabi-v7a", help="arquitecturas separadas por coma (como android.archs)")
    ap.add_argument("--root", default=".", help="carpeta del proyecto")
    args = ap.parse_args(argv)
    archs = [a.strip() for a in args.archs.split(",") if a.strip()]
    if not archs:
        die("no se indicó ninguna arquitectura")
    root = os.path.abspath(args.root)
    with tempfile.TemporaryDirectory() as tmp:
        fetch_libs(root, archs, tmp)
        fetch_java(root, tmp)
        fetch_model(root, args.model, tmp)
    log("listo.")


if __name__ == "__main__":
    main(sys.argv[1:])
