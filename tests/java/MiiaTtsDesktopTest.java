import org.miia.voice.MiiaTts;

/** Prueba en un PC con Java (no en el teléfono): carga un modelo real y genera un WAV.
 *  java -Dmiia.native.dir=<carpeta con libonnxruntime.so y libsherpa-onnx-jni.so> MiiaTtsDesktopTest <carpeta_modelo> <salida.wav> */
public class MiiaTtsDesktopTest {
    public static void main(String[] a) {
        long t0 = System.currentTimeMillis();
        String err = MiiaTts.load(a[0], 2);
        System.out.println("load -> [" + err + "] ready=" + MiiaTts.ready() + " kind=" + MiiaTts.kind()
                + " sr=" + MiiaTts.sampleRate() + " speakers=" + MiiaTts.numSpeakers()
                + " (" + (System.currentTimeMillis() - t0) + " ms)");
        if (!MiiaTts.ready()) { System.exit(2); }
        String[] texts = {"Hola, soy MIIA.", "Hoy tenés tres tareas pendientes y una reunión a las cinco de la tarde."};
        for (int voice = 0; voice < MiiaTts.numSpeakers() || voice == 0; voice++) {
            for (int i = 0; i < texts.length; i++) {
                long t = System.currentTimeMillis();
                int n = MiiaTts.synthToWav(texts[i], voice, 1.08f, a[1] + "." + voice + "." + i + ".wav");
                double secs = n / (double) MiiaTts.sampleRate();
                System.out.printf("voz %d frase %d -> %d muestras (%.2f s de audio) en %d ms%n", voice, i, n, secs, System.currentTimeMillis() - t);
            }
        }
        System.out.println("sid fuera de rango -> " + MiiaTts.synthToWav("Prueba.", 99, 1f, a[1] + ".x.wav"));
        System.out.println("ruta inválida -> " + MiiaTts.synthToWav("Prueba.", 0, 1f, "/no/existe/x.wav") + " " + MiiaTts.lastError());
        System.out.println("carpeta falsa -> " + MiiaTts.load("/no/existe", 1));
        MiiaTts.release();
    }
}
