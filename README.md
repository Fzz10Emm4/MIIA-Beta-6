# MIIA para Android (v4.3.0)

MIIA con todas las funciones del PC (cerebros múltiples con traspaso de cuota, memoria y lecciones, plataformas,
tareas y entrenamiento, nube en GitHub) **menos las descargas** (quedan para una futura actualización), más:

- **Botón Hablar** y **palabra «MIIA»** en segundo plano (como «Oye Siri»): dices «MIIA…» y responde por voz.
- **Respuesta anticipada**: mientras hablas, MIIA ya va pensando la respuesta; si lo que terminas diciendo coincide,
  contesta casi al instante.
- **Voz offline** (sherpa-onnx + voz Piper en español): se genera dentro del teléfono, gratis, sin internet, sin cuentas y
  sin tokens. Reemplaza a Edge TTS (Elvira), que dependía de Microsoft. Respaldo: la voz de Android.
- Diseño oscuro con **azul oscuro** en lugar del rosa, esfera arriba, chat debajo y botones en el menú lateral.
- Ícono: el de los anillos azules.

No hay Fish Audio ni ElevenLabs en esta versión, y ya no se usa Edge TTS.

> **Importante:** este proyecto NO trae ninguna API key. Tampoco copies `miia_secrets.json` del PC. Las keys se pegan una
> vez dentro de la app (menú > Cerebros) y quedan en el almacenamiento privado del teléfono.

---

## 1. Compilar el APK con GitHub (no necesitas instalar nada)

1. En GitHub crea un repositorio **privado** (por ejemplo `miia`). Puede ser el mismo que luego uses como nube de MIIA.
2. Sube el proyecto. Elige **una** de estas formas:
   - **A) Sin carpetas que subir (la más fácil):** sube solo `MIIA_Android.zip` (el zip tal cual, sin descomprimir) con
     *Add file > Upload files*. Luego *Add file > Create new file*, escribe como nombre
     `.github/workflows/build-apk.yml` (al escribir las `/` GitHub crea las carpetas solo), pega dentro todo el
     contenido del archivo `workflow/build-apk.yml` y *Commit changes*. El workflow desempaqueta el zip él mismo.
   - **B) GitHub Desktop:** instala GitHub Desktop, clona tu repositorio, copia dentro la carpeta descomprimida
     (con todas sus subcarpetas, incluida `.github`), y pulsa *Commit* y *Push*. Conserva las carpetas.
   - **C) Navegador en PC:** en *Upload files* **arrastra la carpeta entera** (no selecciones los archivos con el
     botón «choose your files», que los sube sueltos).
3. Abre la pestaña **Actions**. Si GitHub pide activar los workflows, acéptalo.
4. Elige **Compilar APK de MIIA** > **Run workflow**. La primera vez tarda entre 30 y 60 minutos (después, menos).
   El campo *voice_model* puede quedar vacío (usa `vits-piper-es_ES-sharvard-medium`); ver la sección 4 para cambiar de voz.
5. Al terminar, entra en esa ejecución y baja el archivo **MIIA-apk** (un .zip con el `.apk` dentro).

Si el workflow falla, abre la ejecución, copia las últimas ~60 líneas del paso **Compilar** y pásamelas para corregirlo
(el log completo queda en el archivo **MIIA-build-log** de esa ejecución). Esta versión no se pudo compilar en el entorno donde se escribió (no tiene el SDK de Android), así que es
posible que haga falta algún ajuste en la primera compilación.

## 2. Instalar en el Galaxy A02s

1. El APK será mucho más pesado que antes (del orden de 100 MB) porque lleva la voz dentro. Pasa el `.apk` al teléfono y ábrelo. Android te pedirá permitir «instalar apps de esta fuente».
2. **El primer arranque tarda más** (Android desempaqueta la voz, unos 90 MB; en el A02s puede ser medio minuto), y
   cada actualización lo repite una vez. Si Play Protect avisa de una app no verificada, elige *Instalar de todos modos* (es tu propia app).
3. Las próximas versiones se instalan **encima** sin perder datos (el APK usa siempre la misma firma, la de
   `signing/debug.keystore`). No desinstales la app para actualizar: se perdería la memoria local.

## 3. Primer arranque

1. **Cerebros**: menú > Cerebros. Elige un proveedor, pega su API key y toca *Añadir cerebro*. Usa keys **nuevas**
   (las que subiste antes al chat conviene regenerarlas).
2. **Hablar**: toca el botón *Hablar*; acepta el permiso de micrófono (y el de notificaciones).
3. **«MIIA» en segundo plano**: menú > *Escuchar «MIIA»*. Aparece una notificación fija «MIIA escuchando» (es
   obligatoria en Android mientras el micrófono está en uso). Para apagarlo: el mismo botón, o *Detener* en la notificación.
4. **Samsung (importante para escuchar con la pantalla apagada)**:
   - Ajustes > Aplicaciones > MIIA > Batería > **Sin restricciones** (o Ajustes dentro de MIIA > *Ajustes de batería*).
   - Cuidado del dispositivo > Batería > Límites de uso en segundo plano: quita MIIA de «apps en suspensión».
   - No deslices MIIA para cerrarla desde recientes; usa el botón atrás o *Segundo plano* del menú.
5. **Nube (opcional)**: menú > Nube (GitHub). Repositorio privado `usuario/repositorio`, token *fine-grained* con
   *Contents* y *Workflows* en lectura y escritura, *Guardar*, *Probar conexión*, *Instalar servidor*. Luego crea los
   secretos de tus proveedores en el repositorio (la pantalla te lista los nombres).

## 4. Cómo funciona la voz

- **Palabra «MIIA»**: el micrófono se escucha por tandas con el reconocimiento de voz de Google del teléfono. Es una
  aproximación: reconoce «MIIA», «oye MIIA», «hey MIIA» al **principio** de la frase. No es un detector dedicado como el
  de Siri, así que gasta algo más de batería y puede fallar en ambientes ruidosos. Sin internet solo funciona si
  descargaste el idioma sin conexión (Ajustes de Android > Google > Reconocimiento de voz) y activas *Preferir
  reconocimiento sin internet*.
- **Respuesta anticipada**: cuando haces una pausa a mitad de frase, MIIA lanza una respuesta con lo que lleva. Si lo que
  finalmente dices coincide, usa esa respuesta; si no, la descarta. **Solo usa cerebros sin tope diario** (no gasta tu
  cuota limitada), no ejecuta herramientas y tiene un tope diario configurable (60 por defecto).
- **Modo conversación**: tras responder sigue escuchando unos segundos para que no repitas «MIIA».
- **Pitidos del micrófono**: MIIA silencia notificaciones/sistema mientras escucha. Si en tu teléfono el pitido sale por
  *multimedia*, activa en Ajustes *Silenciar también multimedia* (apaga la música de otras apps mientras esperas «MIIA»).
- **Voz offline**: la voz se genera en el teléfono con [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 1.13.8 y la
  voz Piper `es_ES-sharvard-medium` (Español de España, dos voces: mujer por defecto y hombre; se elige en Ajustes).
  - Al abrir la app el modelo tarda unos segundos en cargarse (en segundo plano). Si hablas antes, MIIA usa la voz de
    Android ese rato.
  - Cada respuesta se corta en frases: la primera es corta para que MIIA arranque pronto, y mientras suena una se
    sintetiza la siguiente.
  - **Mide la velocidad real en tu teléfono**: Ajustes > *Diagnóstico*. Verás «N s de audio generados en M s (factor X)».
    Un factor menor que 1 significa que la voz se genera más rápido de lo que dura. En un PC de pruebas Piper medio dio
    0,07 y Kokoro 1,1; el A02s es bastante más lento que ese PC, así que Kokoro no es recomendable ahí.
  - **Cambiar de voz** sin tocar código: *Actions > Compilar APK de MIIA > Run workflow* y en *voice_model* escribe el
    nombre de otro modelo de la lista de https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models, por ejemplo
    `vits-piper-es_MX-claude-high` (México, 63 MB, mismo ritmo) o `vits-piper-es_ES-carlfm-x_low` (20 MB, la más liviana).
    `vits-piper-es_AR-daniela-high` es la única argentina, pero en pruebas fue unas 6 veces más lenta: probablemente
    demasiado para este teléfono.
  - Se fijó sherpa-onnx **1.13.8** a propósito: la 2.x quitó espeak-ng, que las voces Piper en español necesitan.
  - Si la voz offline no cargara, MIIA habla con la voz de Android y te lo avisa. Ajustes > *Diagnóstico* muestra el motivo.
- **Chats**: cada vez que abres la app empieza un chat nuevo. Menú > *Chats* lista los anteriores (abrir o borrar);
  al abrir uno, MIIA retoma esa conversación. *Nuevo chat* abre uno en blanco sin cerrar la app.

## 4b. Novedades de la 4.3: internet, Fuentes, descargas, correo y agenda
Todo está en el menú de la izquierda.

- **Fuentes**: nombre + link de webs o redes. MIIA las lee cuando se lo pedís. Las redes (Instagram, X, Facebook...)
  casi siempre exigen iniciar sesión y mucho JavaScript; si no se pueden leer, lo dice. Para webs con login se puede
  pegar una cookie (solo se manda a esa misma web).
- **Internet**: MIIA busca (DuckDuckGo, y si falla Bing y Wikipedia) y lee páginas. Bloquea direcciones internas (red local).
- **Descargar**: pegá un link, **Analizar**, elegí calidad. Video progresivo (mp4) y audio **M4A** (MP3 real necesita
  ffmpeg: queda para una próxima versión). Sale en Películas/MIIA y Música/MIIA. YouTube suele fallar desde el celular.
- **Correo y agenda**: Gmail con *contraseña de aplicación* (leer y buscar libre, sin marcar como leído; enviar solo
  con tu confirmación) y Calendario de Google por su dirección secreta iCal (solo lectura; crear eventos abre el
  calendario del teléfono). También abrir apps y compartir texto, siempre pidiendo permiso.
- Regla general: **leer es libre; enviar, borrar, crear o modificar siempre te lo pregunta**. Lo que MIIA lee de internet o
  de correos se trata como datos, nunca como órdenes.

## 5. Contenido

| Ruta | Qué es |
|---|---|
| `main.py`, `miia_android/` | La app (interfaz Kivy, voz, respuesta anticipada, motor) |
| `miia_core.py` | El núcleo de MIIA (el mismo del PC; sin descargas ni voces de pago) |
| `java_src/` | Puente con el reconocimiento de voz de Android, el servicio de escucha en segundo plano y `MiiaTts.java` (voz offline) |
| `tools/fetch_voice.py` | Baja al compilar las librerías de sherpa-onnx, su API Java y la voz (carpetas `voice_libs/`, `voice_model/`, `java_src/com/`) |
| `tools/patch_p4a.py` | Declara el servicio de escucha en el manifiesto y copia el Java durante la compilación |
| `buildozer.spec` | Configuración de la compilación (API 33, ARM de 32 bits: corre también en teléfonos de 64 bits) |
| `.github/workflows/build-apk.yml` | Receta de GitHub Actions que compila el APK |
| `signing/debug.keystore` | Firma estable de tu APK (repositorio privado; no la compartas) |
| `tests/` | Pruebas de la lógica que no depende de Android |

## 6. Créditos y licencias de la voz

sherpa-onnx (Apache-2.0), onnxruntime (MIT), espeak-ng (GPL-3.0, para convertir texto en fonemas) y la voz Piper
`es_ES-sharvard-medium`, entrenada con el corpus Harvard sentences en español (CC BY 3.0, Universidad de Edimburgo).
MIIA es de uso personal: si algún día la distribuyes, revisa esas licencias.

## 7. Seguridad

- Ninguna API key ni memoria personal está en este proyecto. `.gitignore` evita subirlas por accidente.
- El repositorio debe ser **privado**: contiene la firma de tu app y, si activas la nube, tu memoria y charlas.
- Regenera las API keys que compartiste por chat antes de usar la app.
