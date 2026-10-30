[app]
title = MIIA
package.name = miia
package.domain = org.miia
source.dir = .
# onnx = el modelo de la voz offline (carpeta voice_model, la baja tools/fetch_voice.py al compilar)
source.include_exts = py,png,json,txt,onnx
source.exclude_dirs = tests, tools, .github, signing, java_src, voice_libs, bin, .buildozer, p4a_src, __pycache__
source.exclude_patterns = *.keystore, miia_secrets.json, miia_*.json
version = 4.3.0

# certifi es Python puro; pyjnius y android dan acceso a las APIs de Android. La voz offline va en Java + librerías
# nativas de sherpa-onnx (ver add_libs más abajo), no como paquete de Python.
requirements = python3,openssl,kivy==2.3.0,pyjnius,android,certifi,yt-dlp

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #0a0a0a
icon.adaptive_foreground.filename = %(source.dir)s/assets/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/icon_bg.png

android.permissions = INTERNET, RECORD_AUDIO, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, POST_NOTIFICATIONS, WAKE_LOCK, MODIFY_AUDIO_SETTINGS, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

android.api = 33
android.minapi = 24
android.ndk = 25b
# Solo 32 bits: el Galaxy A02s lo usa, y también corre en teléfonos de 64 bits. Una sola arquitectura = mitad de tamaño y tiempo
android.archs = armeabi-v7a
# Librerías nativas de la voz offline (sherpa-onnx + onnxruntime). Las deja tools/fetch_voice.py; solo se empaquetan
# las de las arquitecturas de android.archs.
android.add_libs_armeabi_v7a = voice_libs/armeabi-v7a/*.so
android.add_libs_arm64_v8a = voice_libs/arm64-v8a/*.so
android.accept_sdk_license = True
android.private_storage = True
android.debug_artifact = apk

# python-for-android se descarga y se parchea en el workflow (tools/patch_p4a.py) para declarar el servicio de escucha
p4a.source_dir = ./p4a_src

[buildozer]
log_level = 2
warn_on_root = 1
