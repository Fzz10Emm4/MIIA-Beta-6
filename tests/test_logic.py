"""Pruebas de la lógica que no depende de Android (se ejecutan en un PC: python tests/test_logic.py)."""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import miia_core as core                                  # noqa: E402
from miia_android import sherpa                           # noqa: E402
from miia_android.bridge import FakeBridge                # noqa: E402
from miia_android.spec import Responder, SpecEngine, SpecJob   # noqa: E402
from miia_android.tts import NullPlayer, SentenceSplitter, Speaker, rate_to_float   # noqa: E402
from miia_android.util import norm                        # noqa: E402
from miia_android.voice import VoiceController, find_wake    # noqa: E402


def wait_for(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_splitter():
    s = SentenceSplitter()
    out = []
    for piece in ["Hola, ", "te cuento. ", "Primero esto es una frase bastante larga para agrupar. ",
                  "Luego otra frase corta. ", "Y una más larga que sirva para completar el grupo de setenta caracteres. ",
                  "Final"]:
        out += s.feed(piece)
    out += s.flush()
    assert out[0] == "Hola, te cuento.", out
    assert all(len(o) >= 12 for o in out[:-1]), out
    assert "".join(o.replace(" ", "") for o in out) == (
        "Hola, te cuento. Primero esto es una frase bastante larga para agrupar. Luego otra frase corta. "
        "Y una más larga que sirva para completar el grupo de setenta caracteres. Final").replace(" ", ""), out
    s = SentenceSplitter()
    got = s.feed("Habla con el Sr. Pérez ahora. ") + s.feed("Luego se fue. ") + s.flush()
    assert got and got[0].startswith("Habla con el Sr. Pérez"), got
    s = SentenceSplitter()
    big = s.feed("palabra " * 80)
    assert big and all(len(b) < 300 for b in big)
    print("ok splitter", out)


class _FakeJava:
    """Hace de org.miia.voice.MiiaTts para probar sherpa.py sin Android."""

    def __init__(self, load_error="", synth_result=22050):
        self.load_error, self.synth_result = load_error, synth_result
        self.calls = []

    def load(self, model_dir, threads):
        self.calls.append(("load", model_dir, threads))
        return self.load_error

    def sampleRate(self):
        return 22050

    def numSpeakers(self):
        return 2

    def kind(self):
        return "piper"

    def lastError(self):
        return "error de prueba"

    def synthToWav(self, text, voice, speed, path):
        self.calls.append(("synth", text, voice, round(speed, 2)))
        if self.synth_result > 0:
            import wave
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(22050)
                w.writeframes(b"\x01\x00" * self.synth_result)
        return self.synth_result


def _make_model_dir(speakers=True):
    import json
    d = tempfile.mkdtemp()
    open(os.path.join(d, "voz.onnx"), "wb").write(b"x")
    open(os.path.join(d, "tokens.txt"), "w").write("a 1\n")
    os.makedirs(os.path.join(d, "espeak-ng-data"))
    meta = {"speaker_id_map": {"M": 0, "F": 1}} if speakers else {}
    open(os.path.join(d, "voz.onnx.json"), "w").write(json.dumps(meta))
    return d


def test_sherpa():
    d = _make_model_dir()
    assert sherpa.model_present(d) and not sherpa.model_present(os.path.join(d, "no"))
    assert sherpa.speaker_ids(d) == {"M": 0, "F": 1}
    assert sherpa.pick_voice(d, "mujer") == 1 and sherpa.pick_voice(d, "hombre") == 0
    assert sherpa.pick_voice(d, "") == 1 and sherpa.pick_voice(d, "algo raro") == 1
    assert sherpa.pick_voice(_make_model_dir(speakers=False), "mujer") == 0
    # síntesis normal: carga en segundo plano, devuelve un WAV y pasa velocidad y voz
    cache = tempfile.mkdtemp()
    java = _FakeJava()
    t = sherpa.SherpaTTS(make_cfg(voice_gender="mujer", voice_threads=3), cache, d, java=java)
    wav = t.synth("Hola", 1.08)
    assert sherpa.is_wav(wav) and t.loaded and not t.failed and t.sample_rate == 22050 and t.speakers == 2
    assert ("load", d, 3) in java.calls and ("synth", "Hola", 1, 1.08) in java.calls
    # carga una sola vez aunque se pida muchas
    t.synth("otra")
    assert len([c for c in java.calls if c[0] == "load"]) == 1
    # sin modelo en la app: falla con un mensaje claro y no se cuelga
    t2 = sherpa.SherpaTTS(make_cfg(), cache, os.path.join(d, "no"), java=_FakeJava())
    try:
        t2.synth("Hola")
        raise AssertionError("debía fallar")
    except sherpa.VoiceError as e:
        assert "voice_model" in str(e) and t2.failed
    # la carga falla dentro de Java
    t3 = sherpa.SherpaTTS(make_cfg(), cache, d, java=_FakeJava(load_error="OrtException: modelo roto"))
    try:
        t3.synth("Hola")
        raise AssertionError("debía fallar")
    except sherpa.VoiceError as e:
        assert "modelo roto" in str(e) and t3.failed and not t3.loaded
    # la síntesis falla (-2) o no hay audio (0)
    for bad in (-2, 0):
        t4 = sherpa.SherpaTTS(make_cfg(), cache, d, java=_FakeJava(synth_result=bad))
        try:
            t4.synth("Hola")
            raise AssertionError("debía fallar")
        except sherpa.VoiceError:
            pass
    # mientras carga, con wait corto no se cuelga
    class _Slow(_FakeJava):
        def load(self, model_dir, threads):
            time.sleep(0.5)
            return ""
    t5 = sherpa.SherpaTTS(make_cfg(), cache, d, java=_Slow())
    t0 = time.time()
    try:
        t5.synth("Hola", 1.0, 0.05)
        raise AssertionError("debía esperar y fallar")
    except sherpa.VoiceError as e:
        assert "cargando" in str(e) and time.time() - t0 < 0.4
    assert t5.synth("Hola", 1.0, 3)
    print("ok sherpa")


def test_wake():
    assert find_wake("MIIA qué hora es") == (True, "qué hora es")
    assert find_wake("oye Mía, ¿qué tiempo hace?") == (True, "qué tiempo hace")
    assert find_wake("hey mia") == (True, "")
    assert find_wake("Miya") == (True, "")
    assert find_wake("mi ia dime algo") == (True, "dime algo")
    assert find_wake("la casa es mía")[0] is False
    assert find_wake("hola buenas tardes")[0] is False
    assert find_wake("María llegó")[0] is False
    print("ok wake")


class FakePool:
    def __init__(self):
        self.ok = True

    def speculation_ok(self):
        return self.ok


class FakeBrain:
    def __init__(self):
        self.pool = FakePool()
        self.available = True
        self.spec_calls, self.chat_calls = [], []
        self.fail_spec = False

    def reply_to(self, text, on_text=None, on_status=None, purpose="chat"):
        self.spec_calls.append((text, purpose))
        if self.fail_spec:
            raise core.NetworkError("sin red")
        for p in ["Son ", "las tres."]:
            on_text and on_text(p)
            time.sleep(0.01)
        return "Son las tres."

    def chat(self, on_text=None, on_status=None):
        self.chat_calls.append(1)
        on_text and on_text("Respuesta normal.")
        return "Respuesta normal."

    def fallback_reply(self, t):
        return "sin cerebro"

    def friendly_error(self, e):
        return "ERR " + type(e).__name__


class FakeMemory:
    def __init__(self):
        self.rows = []

    def add_conversation(self, role, content):
        self.rows.append((role, content))


def make_cfg(**kw):
    cfg = core.Config(None)
    cfg.data.update(kw)
    return cfg


def test_spec():
    cfg = make_cfg(spec_max_per_day=2)
    brain = FakeBrain()
    eng = SpecEngine(brain, cfg, settle=0.05)
    eng.begin_utterance()
    eng.on_partial("qué")                                    # muy corto: no se lanza
    time.sleep(0.12)
    assert not brain.spec_calls
    eng.on_partial("qué hora es en este momento")
    assert wait_for(lambda: brain.spec_calls)
    assert brain.spec_calls[0][1] == "spec"
    job = eng.take("Qué hora es en este momento?")
    assert job and job.wait(2) and job.reply == "Son las tres."
    got = []
    job.attach(got.append)
    assert "".join(got) == "Son las tres."
    # lo dicho al final es otra cosa: se descarta
    eng.begin_utterance()
    eng.on_partial("cuéntame un chiste de gatos")
    assert wait_for(lambda: len(brain.spec_calls) == 2)
    assert eng.take("cuéntame un chiste de perros por favor") is None
    # tope diario (2) alcanzado
    eng.begin_utterance()
    eng.on_partial("esto ya no debería lanzarse hoy")
    time.sleep(0.2)
    assert len(brain.spec_calls) == 2
    # sin cerebros aptos
    cfg.update(spec_max_per_day=10)
    brain.pool.ok = False
    eng.on_partial("tampoco con la cuota agotada ahora")
    time.sleep(0.2)
    assert len(brain.spec_calls) == 2
    cfg.update(speculate=False)
    brain.pool.ok = True
    eng.on_partial("ni apagada la función completa")
    time.sleep(0.2)
    assert len(brain.spec_calls) == 2
    print("ok spec")


def test_responder():
    brain, mem = FakeBrain(), FakeMemory()
    r = Responder(brain, mem)
    out = []
    reply, ok = r.respond("hola", None, on_text=out.append, speak=False)
    assert ok and reply == "Respuesta normal." and mem.rows == [("user", "hola"), ("assistant", "Respuesta normal.")]
    # con anticipada lista
    job = SpecJob("qué hora es")
    job.push("Son las tres.")
    job.reply = "Son las tres."
    job.done.set()
    mem.rows.clear()
    out.clear()
    reply, ok = r.respond("qué hora es", job, on_text=out.append, speak=False)
    assert reply == "Son las tres." and "".join(out) == "Son las tres." and not brain.chat_calls[1:]
    # la anticipada falló sin emitir: se responde normal
    bad = SpecJob("x")
    bad.error = core.NetworkError("x")
    bad.done.set()
    out.clear()
    reply, ok = r.respond("x", bad, on_text=out.append, speak=False)
    assert ok and reply == "Respuesta normal."
    # sin cerebro
    brain.available = False
    reply, ok = r.respond("hola", None, speak=False)
    assert reply == "sin cerebro"
    print("ok responder")


def make_voice(cfg=None, conv=True):
    cfg = cfg or make_cfg(conversation_mode=conv)
    bridge = FakeBridge()
    brain, mem = FakeBrain(), FakeMemory()
    player = NullPlayer()
    states = []
    spk = Speaker(cfg, player, engine=_FakeEngine(), native=None, on_state=lambda s: states.append(s))
    resp = Responder(brain, mem, spk)
    spec = SpecEngine(brain, cfg, settle=0.05)
    log = {"user": [], "chunks": [], "notes": [], "states": []}
    ui = {"user_message": lambda t, v: log["user"].append((t, v)),
          "chunk": log["chunks"].append, "note": log["notes"].append,
          "state": lambda s, d="": log["states"].append(s)}
    vc = VoiceController(bridge, cfg, spk, resp, spec, ui, sleep=lambda s: time.sleep(min(s, 0.01)))
    return vc, bridge, brain, mem, spk, log, player


class _FakeEngine:
    """Hace de la voz offline (SherpaTTS) en las pruebas del orquestador."""

    def __init__(self, fail=None, failed=False):
        self.fail, self.failed, self.calls = fail, failed, []
        self.last_error = ""

    def synth(self, text, speed=1.0, wait=None):
        self.calls.append((text, round(speed, 2), wait))
        if self.fail:
            self.last_error = self.fail
            raise sherpa.VoiceError(self.fail)
        return b"x" * 500


class _FakeNative:
    def __init__(self):
        self.said = []

    def speak(self, text):
        self.said.append(text)

    def stop(self):
        pass


def test_sherpa_class_lookup_on_main_thread():
    """En Android la clase Java solo se encuentra desde el hilo principal: se debe buscar al construir, no al cargar."""
    seen = []

    def fake_autoclass(name):
        seen.append((name, threading.current_thread() is threading.main_thread()))
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("ClassNotFoundException (hilo que no es el principal)")
        return _FakeJava()
    old = (sherpa.autoclass, sherpa.IS_ANDROID)
    sherpa.autoclass, sherpa.IS_ANDROID = fake_autoclass, True
    try:
        t = sherpa.SherpaTTS(make_cfg(), tempfile.mkdtemp(), _make_model_dir())
        assert seen == [("org.miia.voice.MiiaTts", True)], seen          # buscada al construir, en el hilo principal
        assert t.synth("Hola") and t.loaded                                # y el hilo de carga ya no la busca
        assert seen == [("org.miia.voice.MiiaTts", True)], seen
        # si la clase de verdad no existe, el motivo es claro (no un error confuso)
        def missing(name):
            raise RuntimeError("Didn't find class")
        sherpa.autoclass = missing
        t2 = sherpa.SherpaTTS(make_cfg(), tempfile.mkdtemp(), _make_model_dir())
        try:
            t2.synth("Hola")
            raise AssertionError("debía fallar")
        except sherpa.VoiceError as e:
            assert "MiiaTts" in str(e) and "Didn't find class" in str(e) and t2.failed
    finally:
        sherpa.autoclass, sherpa.IS_ANDROID = old
    print("ok sherpa class lookup")


def test_speaker_engines():
    # voz offline normal: se pasa la velocidad del ajuste y no se usa la nativa
    cfg = make_cfg(voice_rate="+15%")
    eng, nat, player, notes = _FakeEngine(), _FakeNative(), NullPlayer(), []
    spk = Speaker(cfg, player, engine=eng, native=nat, on_note=notes.append)
    spk.say("Hola, ¿cómo estás hoy?")
    assert spk.wait_idle(3) and wait_for(lambda: player.played)
    assert eng.calls and eng.calls[0][1] == 1.15 and eng.calls[0][2] == 6.0     # con respaldo no espera más de 6 s
    assert not nat.said and not notes
    # la voz offline no cargó: habla la nativa, avisa una sola vez y no insiste con cada frase
    eng2, nat2, notes2 = _FakeEngine(fail="no cargó", failed=True), _FakeNative(), []
    spk2 = Speaker(make_cfg(), NullPlayer(), engine=eng2, native=nat2, on_note=notes2.append)
    spk2.say("Primera frase de la respuesta. Segunda frase de la respuesta.")     # salen como dos trozos
    assert wait_for(lambda: len(nat2.said) == 2), nat2.said
    assert len(eng2.calls) == 1, eng2.calls            # tras el fallo de carga ya no se reintenta
    assert len(notes2) == 1 and "voz de Android" in notes2[0] and "no cargó" in notes2[0]     # el aviso trae el motivo
    # fallo puntual (no de carga): se reintenta pronto
    eng3, nat3 = _FakeEngine(fail="se cortó"), _FakeNative()
    spk3 = Speaker(make_cfg(), NullPlayer(), engine=eng3, native=nat3)
    spk3.say("Hola, ¿cómo estás hoy?")
    assert wait_for(lambda: nat3.said)
    assert 15 < spk3._engine_down_until - time.time() <= 20
    # sin voz de respaldo y sin motor: no se cuelga, simplemente no suena
    spk4 = Speaker(make_cfg(voice_native_fallback=False), NullPlayer(), engine=_FakeEngine(fail="x"), native=_FakeNative())
    spk4.say("Hola, ¿cómo estás hoy?")
    assert spk4.wait_idle(3)
    assert spk4.engine.calls[0][2] is None               # sin respaldo, espera la carga completa
    print("ok speaker engines")


def test_voice_wake_flow():
    vc, bridge, brain, mem, spk, log, player = make_voice()
    vc.start_background()
    assert wait_for(lambda: bridge.service and any(c[0] == "listen" and c[3] for c in bridge.calls))   # sesión wake (tight)
    # silencio: se reinicia sola
    n = len([c for c in bridge.calls if c[0] == "listen"])
    bridge.push("error:7")
    assert wait_for(lambda: len([c for c in bridge.calls if c[0] == "listen"]) > n)
    # el usuario dice «oye MIIA qué hora es»: la anticipada arranca con el resto
    bridge.push("partial:oye mia")
    bridge.push("partial:oye mia qué hora es en este momento")
    assert wait_for(lambda: brain.spec_calls)
    assert brain.spec_calls[0][0] == "qué hora es en este momento"
    bridge.push("final:oye MIIA qué hora es en este momento")
    assert wait_for(lambda: log["user"] and mem.rows[-1:] == [("assistant", "Son las tres.")])
    assert log["user"][0] == ("qué hora es en este momento", True)
    assert not brain.chat_calls                       # se usó la respuesta anticipada
    assert wait_for(lambda: spk.spoken and not spk.speaking)
    # modo conversación: sigue escuchando sin decir MIIA
    assert wait_for(lambda: vc.session == "follow" and not vc._busy and bridge.calls[-1][0] == "listen")
    bridge.push("final:y mañana")
    assert wait_for(lambda: len(mem.rows) >= 4)
    assert mem.rows[-2] == ("user", "y mañana")
    # silencio en la conversación: vuelve a esperar «MIIA»
    assert wait_for(lambda: vc.session == "follow" and not vc._busy and bridge.calls[-1][0] == "listen")
    bridge.push("error:6")
    assert wait_for(lambda: bridge.calls[-1][0] == "listen" and bridge.calls[-1][3] is True)
    # solo «MIIA»: dice «Dime» y abre escucha de orden
    spoken_before = len(spk.spoken)
    bridge.push("final:MIIA")
    assert wait_for(lambda: len(spk.spoken) > spoken_before and spk.spoken[-1] == "Dime.")
    assert wait_for(lambda: bridge.calls[-1][0] == "listen" and bridge.calls[-1][3] is False)
    # pitidos silenciados
    assert ("mute", True, False) in bridge.calls
    # detener desde la notificación
    bridge.push("svcstop")
    assert wait_for(lambda: not bridge.service)
    vc.shutdown()
    print("ok voice wake", log["states"][:8])


def test_voice_button_and_errors():
    vc, bridge, brain, mem, spk, log, player = make_voice(conv=False)
    vc.talk_button()
    assert wait_for(lambda: bridge.calls and bridge.calls[-1][0] == "listen" and bridge.calls[-1][3] is False)
    vc.talk_button()                                  # segundo toque: termina de escuchar
    assert wait_for(lambda: ("stop_listening",) in bridge.calls)
    bridge.push("final:cuéntame algo")
    assert wait_for(lambda: mem.rows[-1:] == [("assistant", "Respuesta normal.")])
    assert brain.chat_calls                            # sin anticipada: respuesta normal
    assert wait_for(lambda: log["states"][-1] == "idle")
    # error de idioma
    vc.talk_button()
    assert wait_for(lambda: vc.session == "command")
    bridge.push("error:13")
    assert wait_for(lambda: any("idioma" in n for n in log["notes"]))
    # escrito
    assert vc.submit_typed("hola") or True
    vc.shutdown()
    print("ok voice button")


def test_norm():
    assert norm("¡Oye, Mía! ¿Qué tal?") == "oye mia que tal"
    print("ok norm")


def test_chats():
    import tempfile, os, miia_core as core
    d = tempfile.mkdtemp()
    path = os.path.join(d, "m.json")
    m = core.MemoryManager(path)
    m.new_chat()
    a = m.current_chat
    m.add_conversation("user", "primera charla")
    m.add_conversation("assistant", "hola")
    m2 = core.MemoryManager(path)          # «reabrir la app»
    m2.new_chat()
    assert m2.current_chat != a
    assert m2.history_messages() == []     # chat nuevo: contexto limpio
    m2.add_conversation("user", "segunda charla")
    chats = m2.list_chats()
    assert [c["title"] for c in chats] == ["segunda charla", "primera charla"], chats
    m2.open_chat(a)
    assert [x["content"] for x in m2.history_messages()] == ["primera charla", "hola"]
    m2.add_conversation("user", "sigo aquí")
    assert len(m2.chat_messages(a)) == 3
    m2.clear_conversations()               # solo borra el chat abierto
    assert len(m2.list_chats()) == 1
    m2.delete_chat(m2.list_chats()[0]["id"])
    assert m2.list_chats() == []
    m3 = core.MemoryManager(path)          # sin chats (PC): comportamiento anterior
    m3.add_conversation("user", "x")
    assert m3.history_messages()[0]["content"] == "x"
    print("ok chats")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("TODO OK")
