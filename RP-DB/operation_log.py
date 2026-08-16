"""Registro legible de las operaciones SQL sin almacenar los valores enviados."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


class OperationLogger:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)
        self.enabled = bool(self.config.get("enabled", True))
        configured_path = Path(str(self.config.get("file_path", "logs/operations.log")))
        if not configured_path.is_absolute():
            configured_path = Path(__file__).resolve().parent / configured_path
        self.path = configured_path
        self.max_bytes = max(int(self.config.get("max_bytes", 2_000_000)), 10_000)
        self._lock = threading.Lock()

    def _rotate_if_needed(self) -> None:
        if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
            backup = self.path.with_suffix(self.path.suffix + ".1")
            if backup.exists():
                backup.unlink()
            self.path.replace(backup)

    def record(
        self,
        *,
        operation: str,
        schema: str,
        table: str,
        sql: str,
        status: str,
        rows: int = 0,
        matched_rows: int | None = None,
        requested_rows: int | None = None,
        transaction: str | None = None,
        batch_size: int = 1,
        batches: int = 1,
        duration_seconds: float = 0.0,
        source_file: str | None = None,
        error: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        safe_error = " ".join(str(error).splitlines()) if error else ""
        lines = [
            "=" * 72,
            f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Operación: {operation}",
            f"Tabla: {schema}.{table}",
            f"Estado: {status}",
            f"Filas: {rows}",
            f"Tamaño de lote: {batch_size}",
            f"Cantidad de lotes: {batches}",
            f"Duración: {duration_seconds:.3f} segundos",
        ]
        if matched_rows is not None:
            lines.append(f"Coincidencias originales: {matched_rows}")
        if requested_rows is not None:
            lines.append(f"Cantidad solicitada: {requested_rows}")
        if transaction:
            lines.append(f"Transacción: {transaction}")
        if source_file:
            lines.append(f"Archivo: {Path(source_file).name}")
        lines.extend(("SQL parametrizado:", sql.strip()))
        if safe_error:
            lines.append(f"Error: {safe_error}")
        lines.append("")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(lines))

    def read_latest(self, maximum_characters: int = 80_000) -> str:
        if not self.path.exists():
            return "Todavía no se han registrado operaciones."
        with self._lock:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        return text[-max(int(maximum_characters), 1000) :]
