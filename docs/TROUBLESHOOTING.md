# NEXO TERMINAL — Guía de solución de problemas

Guía para Termux (Android ARM64, sin root) y entornos Linux/macOS.
Empieza siempre ejecutando:

```bash
nexo doctor
```

El diagnóstico comprueba de verdad: Python, dependencias, configuración,
almacén de claves (integridad y permisos 0600), workspace (existencia y
permiso de escritura), git, gh, base de datos y proveedor activo.

---

## 1. Instalación

### `pip install` falla con "externally-managed-environment"
Ocurre en distribuciones con PEP 668 (no en Termux). Soluciones:

```bash
python -m venv ~/.venvs/nexo && source ~/.venvs/nexo/bin/activate
pip install -r requirements.txt && pip install .
```

### `command not found: nexo`
El binario se instala en el directorio `bin` de Python. Comprueba:

```bash
python -m pip show -f nexo-terminal | grep bin
export PATH="$HOME/.local/bin:$PATH"   # añade a ~/.bashrc o ~/.zshrc
```

En Termux con `pkg`/pip normal, suele quedar en `$PREFIX/bin` (ya está en PATH).

### Errores al compilar dependencias
NEXO solo usa paquetes puros (rich, prompt_toolkit, httpx). Si pip intenta
compilar algo, probablemente tu pip/Python es muy antiguo:

```bash
python -m pip install --upgrade pip
```

## 2. Almacenamiento y permisos de Android

### No veo las carpetas del teléfono (Download, Documents…)
Android no concede acceso automático. Ejecuta una sola vez:

```bash
termux-setup-storage
```

Acepta el diálogo y aparecerá `~/storage/shared`. Úsalo como workspace:

```text
/workspace ~/storage/shared/mi-proyecto
```

### "Permiso denegado" al escribir en el workspace
Comprueba `nexo doctor` (línea "Escritura en workspace"). Algunas rutas
(`/sdcard`, externa secundaria) tienen restricciones FUSE de Android:
trabaja bajo `$HOME` de Termux y copia los resultados cuando termines.

### NEXO dice "Ruta fuera del workspace autorizado"
Es el `PathGuard` haciendo su trabajo (anti-traversal y anti-symlink).
Cambia el workspace con `/workspace <ruta>` o mueve el archivo dentro.
NEXO no puede —ni debe— operar fuera del workspace autorizado.

## 3. Proveedores y conectividad

### `/provider test` falla con error de conexión
- **Ollama LAN**: desde el PC, `ollama serve` y variable de entorno
  `OLLAMA_HOST=0.0.0.0`. Desde Termux comprueba la red:
  `curl http://IP-DEL-PC:11434/api/tags`. Teléfono y PC deben estar en la
  misma red y el cortafuegos del PC abierto en ese puerto.
- **APIs en la nube**: verifica que Termux tiene datos/WiFi
  (`ping -c1 api.openai.com`).

### 401 / "Autenticación rechazada"
La clave falta o es inválida. Reintroduce con `/provider key <nombre>`
(entrada oculta) y comprueba que no tiene espacios. Las claves viven en
`~/.nexo/secrets.json` (0600), nunca en `config.json`.

### 404 / "modelo no encontrado"
El nombre del modelo no existe en ese proveedor. Lista los reales:

```text
/model list          # consulta real al proveedor
/model use <modelo>  # cambia el modelo del proveedor activo
```

En Ollama: `ollama pull <modelo>` en el servidor si no está descargado.

### 429 / "límite de peticiones"
Espera el tiempo indicado (NEXO reporta `retry-after` si el servicio lo
envía) o sube `retries` en `/provider edit <nombre> retries=4`.

### La respuesta llega cortada o vacía
- Sube `max_tokens` en los parámetros del proveedor
  (`/provider edit <nombre>` no cubre params: edita `~/.nexo/config.json`).
- En móviles con datos, el streaming puede cortarse: prueba `stream=false`
  en la configuración del proveedor.
- NEXO lanza `IncompleteResponseError` en lugar de fingir éxito: reintenta.

### Ollama dentro del propio teléfono
No hay soporte oficial de Ollama en Termux. Usa un Ollama en LAN o un
proveedor en la nube; la documentación de `/provider add ollama …` apunta a
`http://IP-LAN:11434`.

## 4. Comandos y procesos

### Un comando se queda colgado
Todo `/exec` y `run_command` tiene timeout (`/config set command_timeout 30`)
y mata al **grupo de procesos** completo (hijos incluidos). Si la interfaz
parece bloqueada, Ctrl+C interrumpe la espera y NEXO reporta el timeout.

### "Comando no autorizado (peligroso)"
El clasificador marcó el comando como destructivo (`rm -rf`, `sudo`,
`git push`, `curl|sh`…). Es intencionado:
- Revísalo y autorízalo en el diálogo (1 = una vez, 2 = sesión, 3 = denegar).
- O añade una allowlist explícita en `config.json`: `"allowed_commands": ["pytest"]`.

### La salida se ve truncada
Los límites de salida protegen la memoria del teléfono
(`agent_limits.max_output_chars`). El marcador `[salida truncada]` siempre
avisa; usa comandos más específicos (`| head`, `--stat`).

## 5. Edición de archivos

### "Conflicto: el bloque a reemplazar no se encontró"
El `old_block` no coincide **exactamente** (espacios, tabuladores, saltos).
NEXO muestra el fragmento similar encontrado: cópialo con `/edit` o deja que
el agente use `read_file` primero. Con contenido exacto, la edición aplica.

### "el bloque aparece N veces"
Añade más líneas de contexto al bloque para hacerlo único, o usa
`replace_all=true` (herramienta) cuando el cambio sea global.

### Quiero recuperar un archivo modificado
```text
/undo ruta/archivo.py     # restaura la última copia de seguridad
```
Las copias están en `~/.nexo/backups/files/` (versionadas por fecha) y los
borrados en `~/.nexo/backups/trash/`.

### "Verificación fallida tras escribir"
Significa que la relectura no coincidió con lo escrito (disco lleno,
permisos revocados…). El commit revirtió todo: no hay cambios parciales.
Revisa espacio (`df -h`) y permisos, y reintenta.

## 6. Git y GitHub

### "git no está instalado"
```bash
pkg install git
git config --global user.name "Tu Nombre"
git config --global user.email "tu@correo"
```

### `git push` falla por autenticación
NEXO no guarda credenciales de Git. Opciones:
1. `pkg install gh && gh auth login` (device flow; gh configura también el
   helper de credenciales de git).
2. HTTPS con un Personal Access Token a través del helper que prefieras
   (nunca commiteado al repo).

### `/github create` bloqueado por el escaneo
El escaneo previo encontró secretos (`.env`, `*.pem`, tokens en el
contenido…). Es una protección, no un bug: elimina/excluye los archivos
(añádelos a `.gitignore`) y vuelve a ejecutar `/github scan` hasta que salga
limpio.

### gh no existe en mi Termux
`pkg install gh` según disponibilidad de tu repo. Si no existe, usa git
directo (`/git push`) tras configurar credenciales; `/github status` lo
explica sin fingir capacidades.

## 7. Interfaz

### Se ven códigos raros tipo `ESC[32m` (sin color)
Tu terminal no negocia color correctamente. Fuerza salida limpia:

```text
/config set ui.color false
```

o exporta `NO_COLOR=1` / `NEXO_NO_COLOR=1`.

### Las líneas se parten mal en la pantalla del móvil
NEXO mide el ancho real y envuelve el texto; si tu terminal redimensiona
(con teclado virtual abierto), pulsa Ctrl+L o `/clear` para refrescar.
La UI evita tablas anchas a propósito; usa paneles clave-valor.

### La interfaz va lenta
Desactiva animaciones: `/config set ui.animate false`. El streaming ya está
optimizado (escritura por fragmentos, sin redraw completo).

## 8. Datos y recuperación

### Base de datos corrupta o configuración inválida
NEXO arranca con valores por defecto si `config.json` está corrupto, y
`nexo doctor` lo reporta. Para restablecer:

```bash
mv ~/.nexo/config.json ~/.nexo/config.json.roto
cp config.example.json ~/.nexo/config.json
```

La base de datos (`nexo.db`) puede regenerarse borrándola (perderás
historial, no tus archivos ni backups).

### Recuperar una tarea a medias
```text
/tasks            # lista con estados (interrumpida/en_curso)
/tasks resume 12  # continúa con plan y contexto guardados
```

---

¿Algo no está cubierto? Ejecuta `nexo doctor`, revisa `~/.nexo/logs/nexo.log`
(redactado, sin secretos) y abre un issue en
[Proyecto_Terminal](https://github.com/Promsjjdod/Proyecto_Terminal) con la
salida.
