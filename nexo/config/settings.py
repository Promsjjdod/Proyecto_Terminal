"""Configuración persistente de NEXO (JSON, sin secretos).

Estructura en disco (directorio `.nexo` por defecto en $HOME):

    config.json    -> configuración visible (proveedores SIN claves, límites, UI)
    secrets.json   -> claves API (permisos 0600, gestionado por SecretStore)
    nexo.db        -> SQLite: conversaciones, tareas, historial de operaciones
    backups/       -> copias de seguridad de archivos editados
    logs/          -> nexo.log (redactado)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

CONFIG_FILENAME = "config.json"
SECRETS_FILENAME = "secrets.json"
DB_FILENAME = "nexo.db"

VALID_PERMISSION_MODES = ("seguro", "autonomo", "estricto")


def default_config_dir() -> str:
    """Directorio de datos de NEXO. Respeta $NEXO_HOME si está definido."""
    return os.environ.get("NEXO_HOME") or os.path.join(os.path.expanduser("~"), ".nexo")


@dataclass
class ProviderConfig:
    """Configuración de un proveedor de modelos (la clave va en SecretStore)."""

    name: str
    type: str = "openai"          # openai | ollama | anthropic | custom
    base_url: str = ""
    model: str = ""
    timeout: float = 120.0
    stream: bool = True
    retries: int = 2
    params: Dict[str, Any] = field(default_factory=dict)   # temperature, max_tokens...
    headers: Dict[str, str] = field(default_factory=dict)   # solo custom: cabeceras sin secretos
    # Capacidades informadas POR LA API del proveedor (metadatos de /models).
    # Si la API no las devuelve, queda vacío: NEXO no inventa capacidades.
    capabilities: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderConfig":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in allowed}
        kwargs.setdefault("name", "sin-nombre")
        return cls(**kwargs)

    def masked_summary(self, has_key: bool) -> str:
        clave = "clave: sí" if has_key else "clave: no"
        return f"{self.name} [{self.type}] {self.base_url or '(sin url)'} modelo={self.model or '?'} {clave}"


@dataclass
class AgentLimits:
    """Límites del ciclo del agente (iteraciones, tiempo, recursos)."""

    max_iterations: int = 12
    max_seconds: float = 600.0
    max_output_chars: int = 20_000      # por resultado de herramienta
    max_file_read_chars: int = 100_000  # por lectura de archivo enviada al modelo

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentLimits":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class UIConfig:
    color: bool = True            # False fuerza salida sin color
    width: int = 0                # 0 = autodetectar
    animate: bool = True          # spinners/animaciones discretas
    small_screen: bool = True     # adaptación automática a pantallas estrechas
    diff_style: str = "signs"     # "signs" (+/- clásico) o "blocks" (fondos tipo Codex)


@dataclass
class Config:
    """Configuración global de NEXO."""

    config_dir: str = field(default_factory=default_config_dir)
    workspace: str = ""                                   # directorio de trabajo autorizado
    active_provider: str = ""                             # nombre del proveedor seleccionado
    providers: List[ProviderConfig] = field(default_factory=list)
    permission_mode: str = "seguro"                       # seguro | autonomo | estricto
    agent_limits: AgentLimits = field(default_factory=AgentLimits)
    ui: UIConfig = field(default_factory=UIConfig)
    backups_enabled: bool = True
    command_timeout: float = 60.0                         # timeout por defecto de /exec
    use_native_tools: bool = True                         # tool calling nativo si el proveedor lo soporta
    allowed_commands: List[str] = field(default_factory=list)   # allowlist del usuario
    denied_commands: List[str] = field(default_factory=list)    # blocklist del usuario
    history_limit: int = 200                              # mensajes de contexto por conversación

    # ------------------------------------------------------------------ rutas
    @property
    def config_path(self) -> str:
        return os.path.join(self.config_dir, CONFIG_FILENAME)

    @property
    def secrets_path(self) -> str:
        return os.path.join(self.config_dir, SECRETS_FILENAME)

    @property
    def db_path(self) -> str:
        return os.path.join(self.config_dir, DB_FILENAME)

    @property
    def backups_dir(self) -> str:
        return os.path.join(self.config_dir, "backups")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.config_dir, "logs")

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.backups_dir, self.logs_dir):
            os.makedirs(d, exist_ok=True)

    # ------------------------------------------------------------ proveedores
    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def set_provider(self, provider: ProviderConfig) -> None:
        self.providers = [p for p in self.providers if p.name != provider.name]
        self.providers.append(provider)

    def delete_provider(self, name: str) -> bool:
        before = len(self.providers)
        self.providers = [p for p in self.providers if p.name != name]
        changed = len(self.providers) != before
        if changed and self.active_provider == name:
            self.active_provider = self.providers[0].name if self.providers else ""
        return changed

    def provider_names(self) -> List[str]:
        return [p.name for p in self.providers]

    # ----------------------------------------------------------------- varios
    def validate(self) -> List[str]:
        """Devuelve una lista de problemas detectados (vacía si todo es válido)."""
        problems: List[str] = []
        if self.permission_mode not in VALID_PERMISSION_MODES:
            problems.append(
                f"permission_mode inválido: '{self.permission_mode}' "
                f"(esperado: {', '.join(VALID_PERMISSION_MODES)})"
            )
        names = [p.name for p in self.providers]
        if len(names) != len(set(names)):
            problems.append("Hay proveedores con nombres duplicados.")
        if self.active_provider and self.active_provider not in names:
            problems.append(
                f"El proveedor activo '{self.active_provider}' no existe en la configuración."
            )
        if self.agent_limits.max_iterations < 1:
            problems.append("agent_limits.max_iterations debe ser >= 1.")
        if self.agent_limits.max_seconds <= 0:
            problems.append("agent_limits.max_seconds debe ser > 0.")
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace": self.workspace,
            "active_provider": self.active_provider,
            "providers": [p.to_dict() for p in self.providers],
            "permission_mode": self.permission_mode,
            "use_native_tools": self.use_native_tools,
            "agent_limits": self.agent_limits.to_dict(),
            "ui": asdict(self.ui),
            "backups_enabled": self.backups_enabled,
            "command_timeout": self.command_timeout,
            "allowed_commands": self.allowed_commands,
            "denied_commands": self.denied_commands,
            "history_limit": self.history_limit,
        }


def save_config(config: Config) -> str:
    """Guarda la configuración de forma atómica y devuelve la ruta."""
    config.ensure_dirs()
    tmp = config.config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(config.to_dict(), fh, indent=2, ensure_ascii=False)
    os.replace(tmp, config.config_path)
    return config.config_path


def load_config(config_dir: Optional[str] = None) -> Config:
    """Carga la configuración desde disco; si no existe, devuelve valores por defecto."""
    cfg = Config(config_dir=config_dir or default_config_dir())
    cfg.ensure_dirs()
    if not os.path.exists(cfg.config_path):
        return cfg
    try:
        with open(cfg.config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return cfg  # archivo corrupto: arrancar con defectos, /doctor informará
    if not isinstance(data, dict):
        return cfg

    cfg.workspace = str(data.get("workspace") or "")
    cfg.active_provider = str(data.get("active_provider") or "")
    cfg.permission_mode = str(data.get("permission_mode") or "seguro")
    cfg.backups_enabled = bool(data.get("backups_enabled", True))
    cfg.use_native_tools = bool(data.get("use_native_tools", True))
    cfg.command_timeout = float(data.get("command_timeout", 60.0))
    cfg.allowed_commands = list(data.get("allowed_commands") or [])
    cfg.denied_commands = list(data.get("denied_commands") or [])
    cfg.history_limit = int(data.get("history_limit", 200))
    for raw in data.get("providers") or []:
        if isinstance(raw, dict):
            cfg.providers.append(ProviderConfig.from_dict(raw))
    if isinstance(data.get("agent_limits"), dict):
        cfg.agent_limits = AgentLimits.from_dict(data["agent_limits"])
    if isinstance(data.get("ui"), dict):
        ui = data["ui"]
        cfg.ui = UIConfig(
            color=bool(ui.get("color", True)),
            width=int(ui.get("width", 0)),
            animate=bool(ui.get("animate", True)),
            small_screen=bool(ui.get("small_screen", True)),
            diff_style=str(ui.get("diff_style", "signs")),
        )
    return cfg


def write_example_config(path: str | os.PathLike) -> str:
    """Escribe un archivo de configuración de ejemplo SIN secretos."""
    example = {
        "_comentario": "Ejemplo de configuración de NEXO. Copia a ~/.nexo/config.json y adapta.",
        "workspace": "~/mis-proyectos",
        "active_provider": "ollama-local",
        "permission_mode": "seguro",
        "backups_enabled": True,
        "command_timeout": 60,
        "allowed_commands": [],
        "denied_commands": [],
        "providers": [
            {
                "name": "ollama-local",
                "type": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model": "llama3.2",
                "timeout": 180,
                "stream": True,
                "retries": 1,
                "params": {"temperature": 0.2},
            },
            {
                "name": "openai-ejemplo",
                "type": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "timeout": 120,
                "stream": True,
                "retries": 2,
                "params": {"temperature": 0.3},
                "_nota": "La API key se guarda aparte con `/provider add` (archivo secrets.json, 0600).",
            },
        ],
        "agent_limits": {
            "max_iterations": 12,
            "max_seconds": 600,
            "max_output_chars": 20000,
        },
        "ui": {"color": True, "width": 0, "animate": True, "small_screen": True},
    }
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(example, fh, indent=2, ensure_ascii=False)
    return str(path)
