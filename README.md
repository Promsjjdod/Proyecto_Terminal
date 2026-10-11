# NEXO TERMINAL — TERMINAL INTELLIGENCE
### Agente de Inteligencia Artificial Avanzado para Android (Termux) y Linux

```
 ███╗   ██╗███████╗██╗  ██╗ ██████╗ 
 ████╗  ██║██╔════╝╚██╗██╔╝██╔═══██╗
 ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║
 ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║
 ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝
 ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ 
 TERMINAL INTELLIGENCE — CODEX-CLASS AGENT
```

**NEXO Terminal** es un entorno de desarrollo profesional y agente autónomo de inteligencia artificial de nivel Codex, diseñado específicamente para funcionar sin privilegios `root` en **Android con Termux** y en cualquier servidor Linux. 

Permite programar, inspeccionar arquitecturas de proyectos, crear y modificar archivos de forma segura, comparar diferencias de código línea por línea con resaltado visual, ejecutar comandos autorizados mediante una terminal integrada, conectarse con múltiples proveedores de modelos de lenguaje (OpenAI, DeepSeek, Groq, OpenRouter, Ollama local/remoto) y gestionar repositorios Git y GitHub con protección preventiva de credenciales y secretos.

---

## 📑 Índice de Contenidos

1. [Identidad Visual y Filosofía de Diseño](#-identidad-visual-y-filosofía-de-diseño)
2. [Funcionalidades Principales](#-funcionalidades-principales)
3. [Arquitectura del Sistema](#-arquitectura-del-sistema)
4. [Requisitos Previos](#-requisitos-previos)
5. [Instalación en Termux (Android)](#-instalación-en-termux-android)
6. [Inicio y Modos de Uso (Web y CLI)](#-inicio-y-modos-de-uso-web-y-cli)
7. [Configuración de Proveedores y Modelos](#-configuración-de-proveedores-y-modelos)
8. [Sistema de Seguridad y Permisos Granulares](#-sistema-de-seguridad-y-permisos-granulares)
9. [Editor de Código y Motor de Diferencias (Diffs)](#-editor-de-código-y-motor-de-diferencias-diffs)
10. [Consola Terminal y Ejecución Segura](#-consola-terminal-y-ejecución-segura)
11. [Integración con Git y GitHub (Secret Scanner)](#-integración-con-git-y-github-secret-scanner)
12. [Persistencia, Tareas y Recuperación](#-persistencia-tareas-y-recuperación)
13. [Suite de Pruebas](#-suite-de-pruebas)
14. [Solución de Problemas Frecuentes](#-solución-de-problemas-frecuentes)
15. [Limitaciones Conocidas](#-limitaciones-conocidas)

---

## 🎨 Identidad Visual y Filosofía de Diseño

NEXO Terminal cuenta con un sistema de diseño propio y moderno, concebido para brindar una experiencia de ingeniería de software de primer nivel en pantallas táctiles y escritorios:

- **Paleta cromática:** Fondo negro azulado / carbón (`#0b0f14`, `#111722`), verde neón tecnológico (`#00e676`) como acento principal, rojo (`#f43f5e`) para errores y eliminaciones, verde esmeralda (`#10b981`) para adiciones y operaciones exitosas, y azul cielo (`#38bdf8`) para reflexiones de razonamiento.
- **Logotipo SVG original:** Emblema hexagonal de enlaces neuronales y nodo central luminoso, implementado en SVG puro sin dependencias de imágenes externas ni CDNs.
- **Jerarquía y Adaptabilidad Táctil:** Interfaz adaptable a pantallas de smartphones en Android con barra de navegación inferior de acceso rápido (Agente, Archivos, Diferencias, Terminal, Git, Seguridad) y controles táctiles con objetivo mínimo de 44px.
- **Colores de Diferencias Reales:** 
  - `+` verde para líneas agregadas.
  - `-` rojo para líneas eliminadas.
  - ` ` neutro para líneas de contexto no modificadas.

---

## 🚀 Funcionalidades Principales

- **Agente de Programación Autónomo (Codex-like):**
  - Recepción de instrucciones en lenguaje natural.
  - Planificación desglosada en pasos y modos de esfuerzo:
    - `LOW`: Ejecución rápida y directa para consultas puntuales.
    - `MEDIUM`: Análisis paso a paso, plan de trabajo de 3-5 pasos y validación.
    - `MAX`: Análisis exhaustivo del proyecto, inspección de dependencias, ejecución de pruebas completas y bucle de autocorrección ante errores.
  - Respuestas en streaming en tiempo real vía Server-Sent Events (SSE).
  - Bloques colapsables de razonamiento para modelos de pensamiento (`<think>`).
- **Sistema de Archivos Sandbox:**
  - Exploración de directorios, lectura paginada por líneas para archivos masivos (ahorrando RAM en móviles).
  - Búsqueda recursiva por texto y expresiones regulares (Grep integrado).
  - Edición con coincidencia exacta y difusa (*fuzzy matching* tolerante a identación).
  - Prevención estricta de escape de directorio mediante `..`, enlaces simbólicos hacia el exterior o bytes nulos.
- **Motor de Copias de Seguridad y Reversión:**
  - Creación automática de instantáneas fechadas en `.nexo/backups/` antes de cada sobreescritura o eliminación.
  - Reversión reversible (*rollback*) a cualquier versión anterior con un solo clic o llamada a herramienta.
- **Motor de Comparación (Diff Engine):**
  - Algoritmo real Myers / LCS (*Longest Common Subsequence*).
  - Detección proactiva de conflictos si el archivo en disco cambió antes de aplicar la propuesta.
  - Vista unificada y vista dividida (*side-by-side*).
  - Aprobación o descarte selectivo de cambios.
- **Consola Terminal Integrada:**
  - Ejecución asíncrona de comandos de Termux mediante `spawn` con captura de salida estándar, errores y duración.
  - Detección y bloqueo inmediato de comandos destructivos (`rm -rf /`, bombas fork, formateos).
  - Detención de procesos en ejecución mediante señales `SIGTERM` / `SIGKILL`.
- **Git & GitHub Hub:**
  - Estado en tiempo real del repositorio (rama, modificados, preparados, sin seguimiento).
  - Historial de commits detallado.
  - **Escáner Preventivo de Secretos (Secret Scanner):** Auditoría estricta de archivos preparados antes de `commit` o `push` para impedir la fuga accidental de claves API (`sk-`, `ghp_`, tokens, archivos `.env`, llaves privadas SSH).
- **Extensibilidad de Proveedores de IA:**
  - Soporte nativo para OpenAI, DeepSeek, Groq Cloud, OpenRouter, endpoints compatibles y Ollama local/remoto.
  - Proveedor local simulado (*Built-in Mock Agent*) que permite probar toda la cadena de herramientas y pruebas de forma offline sin configurar claves externas.
  - Claves API cifradas y enmascaradas en la interfaz (`sk-...ab12`).

---

## 🏛 Arquitectura del Sistema

```
Proyecto_Terminal/
├── bin/
│   └── nexo.js                 # Punto de entrada CLI ejecutable
├── src/
│   ├── server.js               # Servidor Express REST API y SSE Streaming
│   └── core/
│       ├── storage/
│       │   └── StorageManager.js   # Persistencia atómica JSON en .nexo/data/
│       ├── permissions/
│       │   ├── PermissionManager.js # 3 Modos de seguridad y sandbox de rutas
│       │   └── BackupManager.js    # Copias de seguridad automáticas y reversión
│       ├── fs/
│       │   └── SafeFileSystem.js   # Operaciones de archivos, lectura paginada, grep
│       ├── diff/
│       │   └── DiffEngine.js       # Algoritmo Myers/LCS, hunks y detección de conflictos
│       ├── terminal/
│       │   └── TerminalManager.js  # Ejecución de comandos, procesos activos, kill
│       ├── git/
│       │   ├── GitManager.js       # Wrapper Git (status, branch, stage, commit, log)
│       │   └── GitHubManager.js    # Integración GitHub CLI y escáner de secretos
│       ├── providers/
│       │   ├── BaseProvider.js     # Interfaz base de proveedores
│       │   ├── OpenAICompatibleProvider.js # Proveedor SSE compatible OpenAI / DeepSeek
│       │   ├── OllamaProvider.js   # Proveedor nativo Ollama
│       │   ├── MockProvider.js     # Proveedor local fuera de línea
│       │   └── ProviderManager.js  # Gestor de configuraciones y pruebas de latencia
│       └── agent/
│           ├── Agent.js            # Ciclo autónomo de razonamiento y herramientas
│           ├── ToolRegistry.js     # Herramientas reales del agente
│           ├── TaskManager.js      # Plan de pasos, estado y recuperación
│           └── PromptBuilder.js    # Constructor de instrucciones contextuales
├── public/
│   ├── index.html              # Interfaz de usuario responsive para móviles y desktop
│   ├── css/
│   │   └── style.css           # Sistema de diseño NEXO en tema oscuro con verde neón
│   └── js/
│       └── app.js              # Controlador cliente, lector de eventos SSE y vistas
├── tests/                      # Suite completa de pruebas unitarias e integrales
├── install.sh                  # Script de instalación para Termux
└── start.sh                    # Script de inicio del servidor y apertura en navegador
```

---

## 📋 Requisitos Previos

1. **Android con Termux** (versión recomendada de F-Droid o GitHub Releases).
2. **Node.js** v18 o superior (probado exhaustivamente en v22+).
3. **Git** v2.30 o superior.
4. *(Opcional)* **GitHub CLI (`gh`)** si deseas autenticación rápida con tu cuenta de GitHub.
5. *(Opcional)* **Ollama** si deseas ejecutar modelos locales en tu dispositivo o en un equipo dentro de tu red local.

---

## 📲 Instalación en Termux (Android)

Abre la aplicación Termux en tu teléfono Android y ejecuta los siguientes comandos:

```bash
# 1. Actualizar repositorios e instalar paquetes base
pkg update && pkg install nodejs git -y

# 2. Clonar el repositorio
git clone https://github.com/Promsjjdod/Proyecto_Terminal.git
cd Proyecto_Terminal

# 3. Ejecutar el instalador automático
chmod +x install.sh
./install.sh
```

El script verificará el entorno, instalará las dependencias necesarias y creará el acceso directo global `nexo` si está disponible el prefijo de Termux.

*(Opcional: Si deseas que NEXO tenga acceso a carpetas de almacenamiento compartido en Android como `/sdcard/Download`, ejecuta previamente en Termux `termux-setup-storage`).*

---

## 🏁 Inicio y Modos de Uso

### Modo Servidor Web (Recomendado para Móviles)

Inicia el entorno visual de desarrollo en Termux:

```bash
./start.sh
# O alternativamente:
node bin/nexo.js start
```

Termux imprimirá:
```
======================================================
  NEXO TERMINAL — ADVANCED AI AGENT FOR TERMUX
  TERMINAL INTELLIGENCE
======================================================
  Server listening on: http://0.0.0.0:3000
  Local Termux URL:    http://localhost:3000
  Working Directory:   /data/data/com.termux/files/home/Proyecto_Terminal
======================================================
```

Abre cualquier navegador web en tu dispositivo (Google Chrome, Firefox, Brave) y visita:
👉 **`http://localhost:3000`**

### Modo Terminal Interactiva (CLI)

También puedes interactuar directamente con NEXO desde la línea de comandos de Termux sin necesidad de abrir el navegador:

```bash
# Ver estado del sistema, proveedor y Git
./bin/nexo.js status

# Enviar una consulta o instrucción en vivo
./bin/nexo.js chat "Inspecciona el proyecto y resume su arquitectura"

# Ver ayuda general
./bin/nexo.js help
```

---

## 🤖 Configuración de Proveedores y Modelos

NEXO Terminal incluye un gestor completo de proveedores accesible desde la pestaña **Configuración** o haciendo clic en la píldora de proveedor en el encabezado.

### 1. Proveedor Local de Fábrica (Offline Mock)
Activado por defecto. Permite experimentar con todas las capacidades del agente, planificación y herramientas de inmediato, sin requerir conexión a internet ni claves de API.

### 2. Ollama Local o en Red Local (LAN)
Ideal para ejecutar modelos como `qwen2.5-coder:7b`, `llama3.2` o `deepseek-r1` en tu propia máquina o servidor casero:
- **Tipo:** `Ollama`
- **URL Base:** `http://127.0.0.1:11434` (o la IP de tu PC en la red local, ej. `http://192.168.1.50:11434`)
- **Modelo:** `qwen2.5-coder:7b`

### 3. OpenAI / DeepSeek / Groq / OpenRouter
- **Tipo:** `OpenAI Compatible`
- **URL Base:**
  - OpenAI: `https://api.openai.com/v1`
  - DeepSeek: `https://api.deepseek.com/v1`
  - Groq Cloud: `https://api.groq.com/openai/v1`
  - OpenRouter: `https://openrouter.ai/api/v1`
- **Clave API:** Tu API Key correspondiente (se almacenará de forma segura y se enmascarará en pantalla como `sk-...a1b2`).
- **Modelo:** `deepseek-coder`, `gpt-4o`, `llama-3.3-70b-versatile`, etc.

Puedes probar la conectividad y latencia de cualquier proveedor configurado pulsando el botón **Probar**.

---

## 🛡 Sistema de Seguridad y Permisos Granulares

Para proteger tu dispositivo contra modificaciones accidentales, NEXO cuenta con un panel visual de seguridad con tres niveles:

| Modo | Comportamiento |
| :--- | :--- |
| **Lectura Estricta (`read-only`)** | El agente puede inspeccionar archivos y formular análisis, pero tiene terminantemente prohibido modificar el disco o ejecutar comandos. |
| **Aprobación Previa (`approval`)** *(Recomendado)* | El agente prepara los planes, diffs y comandos propuestos, pero detiene la ejecución y solicita confirmación interactiva al usuario antes de aplicar cualquier cambio. |
| **Ejecución Autorizada (`authorized`)** | El agente ejecuta de manera autónoma las herramientas permitidas dentro del directorio autorizado del proyecto. |

### Controles Granulares
Puedes activar o desactivar independientemente:
- Lectura de archivos
- Creación y escritura de archivos
- Eliminación de archivos (requiere confirmación adicional por defecto)
- Ejecución de comandos
- Instalación de paquetes
- Acceso a la red
- Operaciones Git locales
- Publicación en GitHub

---

## 🔀 Editor de Código y Motor de Diferencias (Diffs)

Al modificar cualquier archivo, NEXO genera una comparación estructurada basada en el algoritmo LCS/Myers:

- **Líneas con `+` verde:** Contenido nuevo agregado por la propuesta.
- **Líneas con `-` rojo:** Contenido eliminado de la versión anterior.
- **Líneas sin prefijo:** Contexto adyacente del código original.
- **Detección de Conflictos:** Si el archivo en disco fue modificado por otra herramienta o proceso mientras la propuesta estaba en preparación, NEXO muestra una alerta de conflicto para evitar sobrescrituras accidentales.
- **Aceptar / Rechazar:** Permite aplicar la propuesta directamente o descartarla.
- **Reversión (Rollback):** Cada modificación almacena una copia exacta previa en `.nexo/backups/`. Si un cambio no produce el resultado esperado, puedes revertir al estado anterior con un solo clic.

---

## ⚡ Consola Terminal y Ejecución Segura

La consola integrada permite interactuar con el entorno Linux de Termux:

- Ejecución de pruebas (`npm test`, `pytest`, `cargo test`).
- Seguimiento de salida estándar (`stdout`) y errores (`stderr`) con temporizador de ejecución en milisegundos y código de salida.
- Supervisión de procesos en segundo plano con botón para enviar la señal `SIGTERM` / `SIGKILL`.
- **Filtro de Seguridad:** Bloquea de raíz instrucciones potencialmente destructivas como `rm -rf /`, bombas fork o escrituras directas sobre particiones de disco.

---

## 🌿 Integración con Git y GitHub (Secret Scanner)

El módulo de Git facilita el ciclo de desarrollo desde el teléfono:

- Consulta el estado de ramas, modificaciones y archivos sin seguimiento.
- Preparación selectiva de cambios (*staging*) y confirmación de commits.
- Creación y conmutación de ramas de trabajo.
- **Escáner Preventivo de Secretos:** Antes de autorizar un commit o realizar un `push` a GitHub, el motor escanea los archivos en busca de:
  - Archivos de entorno (`.env`, `.env.local`)
  - Claves API de OpenAI (`sk-...`)
  - Tokens de GitHub (`ghp_...`, `github_pat_...`)
  - Credenciales de AWS
  - Llaves privadas SSH (`id_rsa`, `.pem`, `.key`)
- Si se detecta un secreto, la operación se cancela de inmediato y se informa la línea exacta afectada.

---

## 💾 Persistencia, Tareas y Recuperación

- Todos los datos de configuración, proveedores, registros de auditoría y copias de seguridad se almacenan en `.nexo/data/` mediante escrituras atómicas (garantizando que un corte de energía o cierre repentino en Android no corrompa la base de datos).
- Las tareas interrumpidas conservan el estado del plan, permitiendo reanudar el trabajo exactamente en el paso pendiente sin duplicar operaciones ya completadas.

---

## 🧪 Suite de Pruebas

NEXO Terminal incluye 19 pruebas exhaustivas que validan cada componente del sistema mediante el ejecutor nativo de Node.js:

```bash
npm test
```

### Áreas Validadas:
1. `tests/storage.test.js`: Operaciones atómicas CRUD e inicialización de esquemas.
2. `tests/permissions.test.js`: Aislamiento de rutas contra ataques de escape (`..`, `/etc/`, bytes nulos) y conmutación de los 3 modos de seguridad.
3. `tests/backup.test.js`: Generación de copias de seguridad fechadas y reversión íntegra.
4. `tests/fs.test.js`: Lectura por trozos, búsqueda de contenido (grep), escritura y borrado seguro.
5. `tests/diff.test.js`: Algoritmo Myers de adiciones (`+`) y eliminaciones (`-`), hunks unificados y detección de conflictos.
6. `tests/terminal.test.js`: Ejecución estructurada, captura de salida, temporizadores, bloqueo de comandos peligrosos y cancelación con `SIGTERM`.
7. `tests/git.test.js`: Estado del repositorio, ramas, logs y escaneo preventivo de secretos.
8. `tests/providers.test.js`: Gestión de proveedores, enmascaramiento de claves y pruebas de latencia.
9. `tests/agent.test.js`: Planificación autónoma, llamadas a herramientas en bucle, interrupción por aprobación y recuperación de tareas.
10. `tests/server.test.js`: Integración de los endpoints HTTP REST y flujo de eventos en streaming SSE.

---

## 🛠 Solución de Problemas Frecuentes

### 1. El navegador indica que no se puede conectar a `localhost:3000`
- Asegúrate de que el servidor esté activo ejecutando `./start.sh` o `node src/server.js`.
- Si el puerto 3000 está ocupado por otra aplicación en Termux, puedes cambiarlo especificando el puerto en la variable de entorno:
  ```bash
  PORT=3001 ./start.sh
  ```

### 2. Error al intentar acceder a carpetas del teléfono en Termux
- Android aísla el almacenamiento de cada app. Para permitir que Termux acceda a carpetas compartidas como Descargas o Documentos, ejecuta:
  ```bash
  termux-setup-storage
  ```
  y concede el permiso correspondiente en la ventana del sistema.

### 3. Conexión con Ollama rechazada
- Si ejecutas Ollama en una computadora de tu red local y Termux en tu teléfono Android, asegúrate de que Ollama esté escuchando en `0.0.0.0` configurando la variable de entorno en tu equipo:
  ```bash
  export OLLAMA_HOST=0.0.0.0:11434
  ollama serve
  ```

### 4. Secret Scanner bloquea un commit
- Si el escáner bloquea un commit, revisa la salida en la consola o interfaz. Te indicará el archivo y línea donde se detectó una posible clave o token. Remueve la credencial y agrega el archivo a `.gitignore`.

---

## ⚠️ Limitaciones Conocidas

- **Restricciones de permisos de Android:** NEXO Terminal no asume ni requiere acceso `root`. Las operaciones están sujetas a los permisos concedidos al entorno de Termux.
- **Compilaciones nativas C++ pesadas:** En dispositivos móviles con memoria RAM reducida, la compilación de paquetes nativos muy voluminosos puede ser lenta. NEXO ha sido diseñado con dependencias puras en JavaScript para maximizar la velocidad y compatibilidad en Android.
- **Modelos locales muy grandes:** La ejecución de modelos de lenguaje directamente dentro del procesador del teléfono móvil depende de la memoria RAM disponible en tu dispositivo Android. Para modelos de más de 8B parámetros, se recomienda conectar NEXO con un servidor Ollama en red local o una API remota.

---

## 📜 Licencia

Desarrollado bajo licencia **MIT**. Diseñado para desarrolladores móviles y entusiastas de la inteligencia artificial en terminales.
