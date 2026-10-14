# NEXO TERMINAL

> **TU IA · TU TERMINAL · TU PROYECTO**

Agente de inteligencia artificial multimodelo para terminal, diseñado y
optimizado para ejecutarse en **Termux (Android ARM64, sin root)**.

NEXO TERMINAL **no es una página web**: es una aplicación de terminal real,
con interfaz de texto moderna (Rich + prompt_toolkit), que combina un agente
de programación tipo Codex, una terminal inteligente y un asistente
multimodelo autónomo.

---

## Índice

1. [Características](#características)
2. [Instalación en Termux](#instalación-en-termux)
3. [Inicio rápido](#inicio-rápido)
4. [Comandos](#comandos)
5. [Proveedores y modelos](#proveedores-y-modelos)
6. [El agente](#el-agente)
7. [Edición de código y diffs](#edición-de-código-y-diffs)
8. [Permisos y seguridad](#permisos-y-seguridad)
9. [Git y GitHub](#git-y-github)
10. [Memoria y recuperación](#memoria-y-recuperación)
11. [Arquitectura](#arquitectura)
12. [Pruebas](#pruebas)
13. [Solución de problemas](#solución-de-problemas)
14. [Limitaciones honestas](#limitaciones-honestas)

---

## Características

- **Agente real**: planifica → ejecuta → verifica, con límites configurables
  de iteraciones, tiempo y consumo. Nunca afirma que terminó sin comprobarlo.
- **Multimodelo**: Ollama (LAN), APIs compatibles con OpenAI (OpenAI, Groq,
  OpenRouter, vLLM, LM Studio…), Anthropic y endpoints HTTP personalizados.
  Streaming real en todos los proveedores que lo soportan.
- **Sistema de edición tipo Codex**: reemplazo preciso de bloques, diffs
  estilo Git (verde/rojo/amarillo con números de línea), escrituras atómicas,
  copias de seguridad, transacciones todo-o-nada con reversión automática,
  detección de conflictos con sugerencia del fragmento similar, manejo seguro
  de binarios, codificaciones y finales de línea.
- **Permisos reales**: workspace autorizado, protección contra traversal y
  symlinks fugados, tres modos (seguro/autónomo/estricto), autorizaciones
  específicas y revocables, clasificación de comandos
  (informativo/modificador/peligroso).
- **Ejecución de comandos controlada**: timeout, cancelación, muerte del
  árbol de procesos, límites de salida, captura progresiva sin bloquear la UI.
- **Git y GitHub**: estado, diffs, ramas, commits, clonado y publicación con
  escaneo previo de secretos (`.env`, claves, tokens) y la CLI oficial `gh`.
- **Memoria persistente (SQLite)**: conversaciones, tareas (con plan),
  auditoría de operaciones redactada (sin secretos) e historial de archivos.
- **UI adaptada al móvil**: logotipo ASCII responsive, paneles estrechos,
  colores semánticos, salida sin color en terminales que no lo soportan.
- **Claves protegidas**: las API keys viven en `~/.nexo/secrets.json` con
  permisos `0600`, nunca en el repo, los logs ni la salida (redacción
  automática de patrones conocidos).

## Instalación en Termux

```bash
# 1. Instalar Termux desde F-Droid (la versión de Play Store está desactualizada)
# 2. Clonar el repositorio
pkg update -y
pkg install -y git python
git clone https://github.com/Promsjjdod/Proyecto_Terminal.git
cd Proyecto_Terminal

# 3. Ejecutar el instalador
bash install.sh

# 4. Abrir NEXO
nexo
```

El instalador usa solo dependencias **puras en Python** (rich,
prompt_toolkit, httpx): no requieren compilación ni paquetes de escritorio,
por lo que funcionan en Termux ARM64 sin root.

### Instalación manual (cualquier sistema)

```bash
python -m pip install -r requirements.txt
python -m pip install .        # crea el ejecutable 'nexo'
nexo doctor                    # diagnóstico
```

Para desarrollar:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/        # 234 pruebas, proveedores simulados
```

## Inicio rápido

```text
$ nexo

 ███╗   ██╗ ███████╗ ██╗  ██╗  ██████╗
 ████╗  ██║ ██╔════╝ ╚██╗██╔╝ ██╔═══██╗
 ██╔██╗ ██║ █████╗    ╚███╔╝  ██║   ██║
 ██║╚██╗██║ ██╔══╝    ██╔██╗  ██║   ██║
 ██║ ╚████║ ███████╗ ██╔╝ ██╗ ╚██████╔╝
 ╚═╝  ╚═══╝ ╚══════╝ ╚═╝  ╚═╝  ╚═════╝
 N E X O   T E R M I N A L

nexo:mi-proyecto> /provider add nube openai https://api.openai.com/v1 gpt-4o-mini
nexo:mi-proyecto> /provider key nube          # entrada oculta, guardado con 0600
nexo:mi-proyecto> /provider test nube         # prueba REAL de conexión
nexo:mi-proyecto> /workspace ~/proyectos/demo
nexo:mi-proyecto> analiza el proyecto y crea un README con instrucciones de uso
```

También puedes usarlo sin REPL:

```bash
nexo run "crea hola.txt con un saludo y verifícalo" --workspace ~/demo --mode autonomo
nexo doctor
nexo init-config ejemplo.json
```

## Comandos

Todos los comandos ejecutan funciones reales. El texto sin `/` se envía al
agente como instrucción en lenguaje natural. Hay ayuda integrada
(`/help <comando>`) y autocompletado con Tab.

| Comando | Función |
|---|---|
| `/help [cmd]` | Ayuda general o detallada. |
| `/chat [texto]` | Conversación directa con el modelo (sin herramientas). |
| `/model [list\|use <m>]` | Consultar modelos (consulta real al proveedor) y cambiar el modelo del proveedor activo. |
| `/provider …` | `list`, `add`, `edit`, `test`, `use`, `key`, `delkey`, `delete`. |
| `/workspace [ruta]` | Ver o cambiar el directorio de trabajo autorizado. |
| `/files [ruta]` | Explorar archivos del workspace. |
| `/create <ruta> [texto]` | Crear archivo (queda pendiente hasta `/apply`). |
| `/edit <ruta>` | Edición guiada de bloque con diff revisable. |
| `/diff [completo]` | Ver diffs pendientes (o `git diff` si no hay pendientes). |
| `/apply` | Aplicar los cambios revisados (transaccional, verificado). |
| `/discard` | Descartar cambios pendientes. |
| `/undo <ruta>` | Revertir a la última copia de seguridad. |
| `/permissions …` | Ver estado; `mode seguro\|autonomo\|estricto`, `revoke`, `reset`. |
| `/exec <comando>` | Ejecutar comando autorizado (peligrosos piden confirmación). |
| `/git …` | `status`, `diff`, `log`, `branches`, `branch`, `init`, `add`, `commit`, `clone`, `push`. |
| `/github …` | `status`, `scan`, `create <nombre> [--public]`, `remote <url>`. |
| `/history …` | `list`, `show`, `new`, `use`, `delete` conversaciones. |
| `/tasks …` | `list`, `show`, `resume <id>` (recupera tareas interrumpidas). |
| `/config …` | `show`, `set <clave> <valor>`, `path`, `example`. |
| `/doctor` | Diagnóstico real del entorno y la configuración. |
| `/clear` | Limpiar pantalla. |
| `/exit` | Salir guardando el estado. |

## Proveedores y modelos

| Tipo | Uso típico | API key |
|---|---|---|
| `ollama` | Ollama en un PC de la LAN (`http://IP:11434`) | no |
| `openai` | OpenAI, Groq, OpenRouter, Together, vLLM, LM Studio… | según servicio |
| `anthropic` | API oficial de Anthropic (`/v1/messages`, SSE) | sí |
| `custom` | Cualquier endpoint HTTP con plantilla JSON configurable | opcional |

Cada proveedor configura: nombre, URL base, modelo, timeout, streaming,
reintentos y parámetros (`temperature`, `max_tokens`, …). Las claves se
guardan en `~/.nexo/secrets.json` (0600) y se redactan de logs y pantallas.

- `/provider test <nombre>` hace una **prueba real** (lista modelos o
  completado mínimo) y reporta latencia, errores de autenticación, modelos
  inexistentes o servidor caído. Nunca simula una conexión exitosa.
- NEXO usa **el modelo que tú seleccionas**; no lo cambia en silencio.
- Errores tipados: autenticación (401/403), modelo no encontrado (404),
  límite de servicio (429 con `retry-after`), servidor (5xx), timeout,
  respuesta vacía/cortada.

El proveedor `custom` admite plantillas: marcadores `{model}`, `{messages}`,
`{system}`, `{stream}` en el cuerpo, `content_key` con ruta tipo
`result.reply` o `choices.0.message.content`, y streaming `sse`/`ndjson` con
`stream_content_key` configurable.

## El agente

- Ciclo controlado **planificar → ejecutar → verificar** con límites:
  `max_iterations`, `max_seconds`, `max_output_chars`, `max_file_read_chars`
  (editables con `/config set agent.max_iterations 20`, etc.).
- Herramientas reales: `read_file`, `list_dir`, `search` (regex),
  `create_file`, `write_file`, `edit_file` (bloque preciso), `delete_file`,
  `undo_file`, `run_command`, `ask_user`, `finish`.
- El agente **pide información** cuando le falta (`ask_user`) y la tarea
  queda interrumpida y recuperable: `/tasks resume <id>`.
- Los resultados de herramientas vuelven al modelo tal cual (incluidos los
  errores y las denegaciones de permisos): no se ocultan fallos.
- `finish(success=true)` solo es creíble porque las escrituras se verifican
  releyendo el archivo y las operaciones quedan auditadas en SQLite.

## Edición de código y diffs

Antes de aplicar nada verás un diff estilo Git con números de línea:

```text
── src/app.py  +2 −1
   10    10   def suma(a, b):
   11       -     return a + b
       11 +     resultado = a + b
       12 +     return resultado
   12    13
@@ Resumen: 1 archivo(s) — +2 / −1 líneas
```

- Verde = añadido, rojo = eliminado, amarillo = conflicto/atención, sin
  color = contexto intacto.
- `plan_edit` exige que el bloque viejo exista **exactamente una vez** (o
  `replace_all`); si no existe, detecta el conflicto y sugiere el fragmento
  similar más probable.
- Los cambios se aplican de forma **transaccional**: copias de seguridad,
  escritura atómica (temporal + `os.replace` + `fsync`), verificación
  posterior y, si algo falla, **reversión automática** (nunca quedan
  archivos parcialmente modificados).
- Archivos binarios: se sustituyen íntegros byte a byte; nunca se
  decodifican como texto (no se corrompen).
- Codificación (UTF-8/Latin-1) y finales de línea (LF/CRLF) originales se
  preservan en cada edición.

## Permisos y seguridad

Tres modos (`/permissions mode …`):

1. **seguro** — lecturas automáticas; escrituras y comandos piden
   autorización; lo sensible siempre pregunta.
2. **autonomo** — trabaja sin preguntar *dentro del workspace* (con límite
   de escrituras configurable); lo sensible sigue preguntando.
3. **estricto** — pregunta antes de **cada** escritura y **cada** comando.

Operaciones siempre sensibles (preguntan incluso en autónomo): borrar
archivos, comandos peligrosos (`rm -rf`, `dd`, `sudo`, `git push`,
`curl|sh`…), salir del workspace, credenciales, publicar en Git/GitHub,
reescribir historial y cambios de configuración del sistema.

- Las autorizaciones son **específicas** por (operación, objetivo) y
  **revocables** (`/permissions revoke <tipo> <objetivo>`, `/permissions
  reset`). Aprobar un borrador no autoriza otros, ni ejecuciones.
- Protección de rutas: traversal `../`, rutas absolutas externas, bytes NUL
  y **symlinks que escapen del workspace** se bloquean con `PathViolation`.
- NEXO opera con los permisos reales de Termux/Android: **no tiene root** y
  no lo simula. Si Android no concede una ruta, lo explica.
- El agente nunca ejecuta a ciegas lo que sugiere el modelo: cada operación
  pasa por clasificación y autorización, y su resultado se comprueba.
- Sin callback de pregunta disponible (modo no interactivo), lo sensible se
  **deniega** — nunca se permite en silencio.

## Git y GitHub

- `/git` cubre el flujo local completo (init, status, diff, log, ramas,
  add, commit, clone con validación de URL, push con autorización).
- `/github` usa la CLI oficial `gh` cuando está disponible. NEXO **no pide
  ni almacena tokens de GitHub**: la autenticación se delega en
  `gh auth login` (device flow).
- Antes de publicar se ejecuta un **escaneo de secretos** (nombres tipo
  `.env`, `*.pem`, `id_rsa`, `.git-credentials`, `.nexo/`… y contenido con
  patrones `sk-…`, `ghp_…`, `AKIA…`, claves privadas). Si aparece algo, la
  publicación se **bloquea** y se explica qué corregir.
- Si `gh` no está instalado o no hay sesión, NEXO lo dice con instrucciones
  exactas (`pkg install gh`, `gh auth login`), sin fingir éxito.

## Memoria y recuperación

Todo vive en `~/.nexo/` (o `$NEXO_HOME`):

```text
~/.nexo/
├── config.json      # configuración visible (SIN claves)
├── secrets.json     # API keys (permisos 0600)
├── nexo.db          # SQLite: conversaciones, tareas, auditoría, historial
├── backups/files/   # copias de seguridad versionadas de archivos editados
├── backups/trash/   # papelera recuperable de archivos borrados
├── logs/nexo.log    # registro rotativo con secretos redactados
└── input_history    # historial de entrada del REPL
```

- Sesiones largas: el contexto antiguo se compacta en un resumen antes de
  enviarse al modelo (los últimos mensajes se conservan íntegros).
- Tareas interrumpidas (por límites o por `ask_user`) se reanudan con su
  plan y estado: `/tasks resume <id>`.
- Tus archivos **no se envían al proveedor** salvo que la tarea lo requiera
  (el agente los lee con sus herramientas dentro del workspace) y la
  política de permisos lo autorice.

## Arquitectura

```text
nexo/
├── cli.py           # punto de entrada 'nexo' (repl, doctor, run, init-config)
├── app.py           # REPL: comandos, lenguaje natural, wiring de subsistemas
├── ui/              # tema, logotipo ASCII, paneles, diffs coloreados, streaming
├── agent/           # ciclo planificar→ejecutar→verificar, prompts, límites
├── providers/       # base + ollama + openai-compat + anthropic + custom + registro
├── tools/           # ejecutor de comandos y catálogo de herramientas del agente
├── permissions/     # PathGuard (traversal/symlinks) y PermissionManager (modos)
├── filesystem/      # lectura/escritura atómica, backups, papelera
├── editor/          # motor CODEX: diff estilo Git, ChangeSet transaccional, undo
├── gitops/          # operaciones Git reales con permisos
├── github/          # gh CLI + escaneo de secretos pre-publicación
├── memory/          # SQLite (conversaciones, tareas, auditoría, historial)
├── config/          # configuración persistente sin secretos
├── security/        # SecretStore 0600 + redacción de claves
└── utils/           # plataforma/Termux, logging redactado, texto/wrapping
```

## Pruebas

```bash
python -m pytest tests/ -v
```

234 pruebas automatizadas con **proveedores simulados** (HTTP mockeado con
`httpx.MockTransport` y `FakeProvider`): no necesitas API de pago. Cubren
registro/selección de proveedores, streaming (SSE/NDJSON), errores de
conexión/auth/429/timeout/respuestas vacías, reintentos, creación y edición
de archivos, vista diff, aplicación y reversión de parches, rollback
transaccional, protección de rutas (traversal/symlink), permisos por modo,
ejecución de comandos (timeout, truncado, hijos), operaciones Git reales,
escaneo de publicación GitHub, persistencia de conversaciones/tareas,
configuración, contexto compactado y renderizado en terminales de 34–40
columnas.

## Solución de problemas

Ver la guía completa en **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**
y ejecutar `nexo doctor` para un diagnóstico real del entorno.

## Limitaciones honestas

- **Ollama en el propio teléfono**: Ollama no tiene soporte oficial en
  Termux. El proveedor `ollama` está pensado para conectarse a un Ollama en
  tu LAN (PC/servidor). Dentro del teléfono, usa un endpoint compatible
  (p. ej. un servidor llama.cpp local si lo compilas, o APIs en la nube).
- **Sin root**: NEXO opera con los permisos reales de Android/Termux. El
  acceso al almacenamiento compartido requiere `termux-setup-storage`.
- **gh en Termux**: disponible vía `pkg install gh`; si tu distribución no
  lo incluye, `/github status` lo informa y puedes usar git con HTTPS.
- Las operaciones de GitHub exigen autenticación previa (`gh auth login`);
  NEXO no guarda tokens por ti.

---

**Licencia**: MIT. Hecho para Termux, con Python puro donde importa.
