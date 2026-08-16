"""Punto de entrada de la aplicación."""

from __future__ import annotations

import ctypes
import os
import tkinter as tk
from tkinter import messagebox

from config import (
    BULK_INSERT_CONFIG,
    DB_CONFIG,
    FORM_CONFIG,
    LOG_CONFIG,
    TABLE_SELECTOR_CONFIG,
    UI_CONFIG,
    UPDATE_CONFIG,
)
from credential_store import CredentialProfileStore
from database import ConfigurationError, SQLServerRepository
from gui import InsertFormApp
from operation_log import OperationLogger


def show_startup_error(title: str, message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror(title, message, parent=root)
    finally:
        root.destroy()


def main() -> None:
    try:
        if os.name == "nt":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    str(UI_CONFIG.get("windows_app_id", "SQLRecordManager"))
                )
            except (AttributeError, OSError):
                pass
        profile_store = CredentialProfileStore()
        connection_profile = profile_store.load(DB_CONFIG)
        logger = OperationLogger(LOG_CONFIG)
        repository = SQLServerRepository(
            connection_profile,
            FORM_CONFIG,
            {"enabled": False},
            operation_logger=logger,
        )
        app = InsertFormApp(
            repository,
            FORM_CONFIG,
            UI_CONFIG,
            BULK_INSERT_CONFIG,
            connection_profile=connection_profile,
            profile_store=profile_store,
            selector_config=TABLE_SELECTOR_CONFIG,
            base_update_config=UPDATE_CONFIG,
        )
        app.mainloop()
    except ConfigurationError as exc:
        show_startup_error("Configuración no válida", str(exc))


if __name__ == "__main__":
    main()
