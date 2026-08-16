"""Perfil de conexión persistente con contraseña fuera de archivos de texto."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from database import ConfigurationError

try:
    import keyring
    from keyring.errors import KeyringError
except ModuleNotFoundError:
    keyring = None  # type: ignore[assignment]

    class KeyringError(Exception):
        pass


class CredentialProfileStore:
    """Guarda metadatos en JSON y la clave en el almacén seguro del sistema."""

    SERVICE_NAME = "SQL Record Manager"
    PASSWORD_KEY = "active-sqlserver-password"
    ALLOWED_KEYS = {
        "provider",
        "server",
        "database",
        "port",
        "sslmode",
        "driver",
        "driver_candidates",
        "trusted_connection",
        "username",
        "trust_server_certificate",
        "connection_timeout",
        "last_table",
        "update_keys_by_table",
    }

    def __init__(self, path: Path | None = None, backend: Any | None = None) -> None:
        self.path = path or self.default_path()
        self.backend = backend if backend is not None else keyring

    @staticmethod
    def default_path() -> Path:
        if os.name == "nt" and os.getenv("APPDATA"):
            base = Path(os.environ["APPDATA"])
        else:
            base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / "SQLRecordManager" / "connection_profile.json"

    def _secure_backend(self) -> Any:
        if self.backend is None:
            raise ConfigurationError(
                "Falta keyring. Ejecuta: python -m pip install -r requirements.txt"
            )
        return self.backend

    def load(self, defaults: Mapping[str, Any]) -> dict[str, Any]:
        profile = {key: value for key, value in defaults.items() if key != "password"}
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigurationError(
                    "No se pudo leer el perfil de conexión guardado."
                ) from exc
            if not isinstance(stored, dict):
                raise ConfigurationError("El perfil de conexión guardado no es válido.")
            profile.update(
                {key: value for key, value in stored.items() if key in self.ALLOWED_KEYS}
            )

        password = ""
        try:
            backend = self._secure_backend()
            password = backend.get_password(self.SERVICE_NAME, self.PASSWORD_KEY) or ""
        except (KeyringError, ConfigurationError):
            # El resto del perfil sigue siendo útil aunque el almacén no esté disponible.
            password = ""
        profile["password"] = password
        return profile

    def save(self, config: Mapping[str, Any], last_table: str = "") -> None:
        metadata = {
            key: value
            for key, value in config.items()
            if key in self.ALLOWED_KEYS and key != "last_table"
        }
        metadata["last_table"] = str(last_table)
        metadata.pop("password", None)

        backend = self._secure_backend()
        try:
            if config.get("trusted_connection", False):
                try:
                    backend.delete_password(self.SERVICE_NAME, self.PASSWORD_KEY)
                except KeyringError:
                    pass
            else:
                password = str(config.get("password", ""))
                if not password:
                    raise ConfigurationError(
                        "Escribe la contraseña antes de guardar la conexión."
                    )
                backend.set_password(self.SERVICE_NAME, self.PASSWORD_KEY, password)
        except KeyringError as exc:
            raise ConfigurationError(
                "No se pudo guardar la contraseña en el almacén seguro del sistema."
            ) from exc

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            raise ConfigurationError("No se pudo guardar el perfil de conexión.") from exc

    def forget(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
            backend = self._secure_backend()
            try:
                backend.delete_password(self.SERVICE_NAME, self.PASSWORD_KEY)
            except KeyringError:
                pass
        except (OSError, KeyringError) as exc:
            raise ConfigurationError("No se pudo eliminar el perfil guardado.") from exc
