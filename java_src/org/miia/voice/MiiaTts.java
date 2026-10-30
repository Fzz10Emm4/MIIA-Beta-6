package org.miia.voice;

import com.k2fsa.sherpa.onnx.GeneratedAudio;
import com.k2fsa.sherpa.onnx.LibraryLoader;
import com.k2fsa.sherpa.onnx.OfflineTts;
import com.k2fsa.sherpa.onnx.OfflineTtsConfig;
import com.k2fsa.sherpa.onnx.OfflineTtsKokoroModelConfig;
import com.k2fsa.sherpa.onnx.OfflineTtsModelConfig;
import com.k2fsa.sherpa.onnx.OfflineTtsVitsModelConfig;

import java.io.File;

/**
 * Voz de MIIA 100 % en el teléfono (sherpa-onnx). Sin internet, sin cuentas, sin tokens.
 *
 * Python (pyjnius) solo llama a estos métodos estáticos:
 *   load(carpetaDelModelo, hilos)            -> "" si cargó bien, o el texto del error
 *   synthToWav(texto, voz, velocidad, ruta)  -> cantidad de muestras (0 o menos = falló)
 *
 * La carpeta del modelo es la de un modelo Piper de sherpa-onnx (model.onnx + tokens.txt + espeak-ng-data/).
 * Si tiene voices.bin se interpreta como Kokoro (experimental: en un Snapdragon 450 va demasiado lento).
 * No usa nada de la API de Android, así que también se puede probar en un PC con Java.
 */
public class MiiaTts {
    private static final Object LOCK = new Object();

    private static OfflineTts tts;
    private static boolean nativeLoaded = false;
    private static volatile String lastError = "";
    private static volatile int sampleRate = 0;
    private static volatile int numSpeakers = 0;
    private static volatile String kind = "";

    // ------------------------------------------------------------------ carga

    /** Carga las librerías nativas. Con -Dmiia.native.dir=... (solo pruebas en PC) las toma de esa carpeta. */
    private static void loadNative() {
        if (nativeLoaded) {
            return;
        }
        // Se evita el cargador de sherpa (pensado para PC): en Android basta System.loadLibrary.
        LibraryLoader.setAutoLoadEnabled(false);
        String dir = System.getProperty("miia.native.dir");
        if (dir != null && dir.length() > 0) {
            System.load(new File(dir, "libonnxruntime.so").getAbsolutePath());
            System.load(new File(dir, "libsherpa-onnx-jni.so").getAbsolutePath());
        } else {
            System.loadLibrary("onnxruntime");
            System.loadLibrary("sherpa-onnx-jni");
        }
        nativeLoaded = true;
    }

    private static String findOnnx(File dir) {
        File[] files = dir.listFiles();
        if (files == null) {
            return null;
        }
        String best = null;
        for (File f : files) {
            String n = f.getName();
            if (n.endsWith(".onnx") && !n.endsWith(".onnx.json")) {
                // si hay varias (p. ej. model.onnx y model.int8.onnx) se prefiere la más liviana
                if (best == null || n.contains("int8")) {
                    best = f.getAbsolutePath();
                }
            }
        }
        return best;
    }

    /** @return "" si todo salió bien; si no, el motivo (también queda en lastError()). */
    public static String load(String modelDir, int threads) {
        synchronized (LOCK) {
            try {
                if (tts != null) {
                    return "";
                }
                File dir = new File(modelDir);
                if (!dir.isDirectory()) {
                    return fail("No existe la carpeta de la voz: " + modelDir);
                }
                String onnx = findOnnx(dir);
                File tokens = new File(dir, "tokens.txt");
                File espeak = new File(dir, "espeak-ng-data");
                if (onnx == null) {
                    return fail("No encontré el archivo .onnx de la voz en " + modelDir);
                }
                if (!tokens.isFile()) {
                    return fail("Falta tokens.txt en " + modelDir);
                }
                if (!espeak.isDirectory()) {
                    return fail("Falta la carpeta espeak-ng-data en " + modelDir);
                }
                loadNative();

                OfflineTtsModelConfig.Builder mb = OfflineTtsModelConfig.builder()
                        .setNumThreads(Math.max(1, threads))
                        .setDebug(false)
                        .setProvider("cpu");
                File voices = new File(dir, "voices.bin");
                if (voices.isFile()) {
                    kind = "kokoro";
                    File lex = new File(dir, "lexicon-us-en.txt");
                    OfflineTtsKokoroModelConfig.Builder kb = OfflineTtsKokoroModelConfig.builder()
                            .setModel(onnx)
                            .setVoices(voices.getAbsolutePath())
                            .setTokens(tokens.getAbsolutePath())
                            .setDataDir(espeak.getAbsolutePath())
                            .setLang("es");
                    if (lex.isFile()) {
                        kb.setLexicon(lex.getAbsolutePath());
                    }
                    mb.setKokoro(kb.build());
                } else {
                    kind = "piper";
                    mb.setVits(OfflineTtsVitsModelConfig.builder()
                            .setModel(onnx)
                            .setTokens(tokens.getAbsolutePath())
                            .setDataDir(espeak.getAbsolutePath())
                            .build());
                }
                OfflineTtsConfig cfg = OfflineTtsConfig.builder()
                        .setModel(mb.build())
                        .setMaxNumSentences(1)
                        .build();
                OfflineTts t = new OfflineTts(cfg);
                sampleRate = t.getSampleRate();
                numSpeakers = t.getNumSpeakers();
                tts = t;
                lastError = "";
                return "";
            } catch (Throwable e) {
                return fail(e.getClass().getSimpleName() + ": " + e.getMessage());
            }
        }
    }

    private static String fail(String msg) {
        lastError = msg;
        return msg;
    }

    // ------------------------------------------------------------------ uso

    public static boolean ready() {
        return tts != null;
    }

    public static String lastError() {
        return lastError;
    }

    public static int sampleRate() {
        return sampleRate;
    }

    public static int numSpeakers() {
        return numSpeakers;
    }

    public static String kind() {
        return kind;
    }

    /**
     * Genera la voz de un trozo de texto y la guarda como WAV de 16 bits.
     * @param voice  número de voz (en los modelos de varias voces, p. ej. 0 = hombre y 1 = mujer)
     * @param speed  1.0 normal, mayor = más rápido
     * @return cantidad de muestras generadas; 0 si no hubo audio; -1 si no se pudo guardar; -2 si falló
     */
    public static int synthToWav(String text, int voice, float speed, String outPath) {
        synchronized (LOCK) {
            if (tts == null) {
                lastError = "La voz offline todavía no está cargada";
                return -2;
            }
            try {
                int sid = numSpeakers > 0 ? Math.max(0, Math.min(voice, numSpeakers - 1)) : 0;
                GeneratedAudio audio = tts.generate(text, sid, speed > 0 ? speed : 1.0f);
                if (audio == null || audio.getSamples() == null || audio.getSamples().length == 0) {
                    return 0;
                }
                if (!audio.save(outPath)) {
                    lastError = "No pude guardar el audio en " + outPath;
                    return -1;
                }
                return audio.getSamples().length;
            } catch (Throwable e) {
                lastError = e.getClass().getSimpleName() + ": " + e.getMessage();
                return -2;
            }
        }
    }

    public static void release() {
        synchronized (LOCK) {
            if (tts != null) {
                try {
                    tts.release();
                } catch (Throwable e) {
                    // nada
                }
                tts = null;
            }
        }
    }
}
