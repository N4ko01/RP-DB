"""Interfaz moderna, responsiva y minimalista para SQL Server."""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping, Sequence

from catalog import (
    UNSUPPORTED_KEY_TYPES,
    ColumnMetadata,
    SQLServerCatalog,
    TableReference,
)
from credential_store import CredentialProfileStore
from database import ConfigurationError, SQLServerRepository, ValidationError
from excel_import import ExcelImportData, ExcelImportService

try:
    from PIL import Image, ImageTk
except ModuleNotFoundError:
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]


def default_value(field: Mapping[str, Any]) -> Any:
    default = field.get("default", "")
    if default == "today":
        return date.today().isoformat()
    if default == "now":
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return default


def display_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return value


def field_type_display(field: Mapping[str, Any]) -> str:
    configured = str(field.get("sql_type_display", "")).strip()
    if configured:
        return configured
    return {
        "str": "TEXTO",
        "int": "ENTERO",
        "float": "DECIMAL",
        "decimal": "DECIMAL",
        "bool": "BIT",
        "date": "DATE",
        "datetime": "DATETIME",
        "time": "TIME",
    }.get(str(field.get("type", "str")).casefold(), "DATO")


class Card(ttk.Frame):
    """Superficie blanca reutilizable con borde tenue."""

    def __init__(self, parent: tk.Misc, **kwargs: Any) -> None:
        super().__init__(parent, style="Card.TFrame", padding=kwargs.pop("padding", 16), **kwargs)


class StatusBar(ttk.Frame):
    def __init__(self, parent: tk.Misc, initial: str) -> None:
        super().__init__(parent, style="StatusBar.TFrame", padding=(12, 7))
        self.variable = tk.StringVar(value=initial)
        self.dot = ttk.Label(self, text="●", style="StatusDot.TLabel")
        self.dot.pack(side="left")
        ttk.Label(self, textvariable=self.variable, style="StatusText.TLabel").pack(
            side="left", padx=(7, 0)
        )

    def set(self, text: str, state: str = "normal") -> None:
        self.variable.set(text)
        style = {
            "success": "SuccessDot.TLabel",
            "error": "DangerDot.TLabel",
        }.get(state, "StatusDot.TLabel")
        self.dot.configure(style=style)


class KeySelectionDialog(tk.Toplevel):
    """Solicita una combinación de columnas para identificar un registro."""

    def __init__(
        self,
        parent: tk.Misc,
        table_name: str,
        columns: Sequence[ColumnMetadata],
        colors: Mapping[str, str],
        font_family: str,
        selected: Sequence[str] = (),
    ) -> None:
        super().__init__(parent)
        self.result: list[str] | None = None
        self.title("Clave para Buscar / actualizar")
        self.geometry("520x500")
        self.minsize(440, 400)
        self.transient(parent.winfo_toplevel())
        self.configure(background=colors["background"])
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        container = tk.Frame(self, background=colors["surface"], padx=22, pady=20)
        container.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(
            container,
            text="Selecciona la clave del registro",
            background=colors["surface"],
            foreground=colors["text"],
            font=(font_family, 15, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            container,
            text=(
                f"{table_name} no tiene una PRIMARY KEY ni un índice UNIQUE. "
                "Elige una o varias columnas cuya combinación no se repita."
            ),
            background=colors["surface"],
            foreground=colors["muted"],
            font=(font_family, 9),
            justify="left",
            wraplength=450,
            anchor="w",
        ).pack(fill="x", pady=(5, 14))

        self.listbox = tk.Listbox(
            container,
            selectmode="extended",
            exportselection=False,
            background=colors["surface_alt"],
            foreground=colors["text"],
            selectbackground=colors["selection"],
            selectforeground=colors["text"],
            highlightbackground=colors["border"],
            highlightcolor=colors["primary"],
            highlightthickness=1,
            borderwidth=0,
            font=(font_family, 10),
        )
        self.listbox.pack(fill="both", expand=True)
        selected_names = {str(name).casefold() for name in selected}
        selectable_columns = [
            column
            for column in columns
            if column.sql_type.casefold() not in UNSUPPORTED_KEY_TYPES
        ]
        for index, column in enumerate(selectable_columns):
            suffix = " · permite NULL" if column.nullable else ""
            self.listbox.insert("end", f"{column.name}  ({column.sql_type}){suffix}")
            if column.name.casefold() in selected_names:
                self.listbox.selection_set(index)
        self.column_names = [column.name for column in selectable_columns]

        tk.Label(
            container,
            text="Se comprobarán los duplicados antes de habilitar el UPDATE.",
            background=colors["surface"],
            foreground=colors["muted"],
            font=(font_family, 8),
            anchor="w",
        ).pack(fill="x", pady=(10, 12))
        actions = tk.Frame(container, background=colors["surface"])
        actions.pack(fill="x")
        ttk.Button(
            actions, text="Cancelar", command=self._cancel, style="Ghost.TButton"
        ).pack(side="right")
        ttk.Button(
            actions,
            text="Comprobar y continuar",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._accept())
        self.grab_set()
        self.after_idle(self._focus)

    def _focus(self) -> None:
        self.listbox.focus_set()
        self.lift()

    def _accept(self) -> None:
        indexes = self.listbox.curselection()
        if not indexes:
            messagebox.showwarning(
                "Clave requerida", "Selecciona al menos una columna.", parent=self
            )
            return
        self.result = [self.column_names[index] for index in indexes]
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class ScrollableForm(ttk.Frame):
    """Formulario que se apila cuando dispone de poco ancho."""

    def __init__(
        self,
        parent: tk.Misc,
        fields: Sequence[Mapping[str, Any]],
        colors: Mapping[str, str],
        ui_config: Mapping[str, Any] | None = None,
        height: int = 330,
    ) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.fields = list(fields)
        self.colors = colors
        self.ui_config = dict(ui_config or {})
        self.variables: dict[str, tk.Variable] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self.labels: dict[str, ttk.Label] = {}
        self.hints: dict[str, ttk.Label] = {}
        self._compact: bool | None = None
        self._resize_job: str | None = None
        self._scrollregion_job: str | None = None
        self._pending_canvas_width = 0
        self._applied_canvas_width = 0
        self._resize_delay = int(
            self.ui_config.get("form_resize_debounce_ms", 90)
        )
        self._responsive_breakpoint = int(
            self.ui_config.get("form_responsive_breakpoint", 600)
        )
        self._width_tolerance = int(
            self.ui_config.get("resize_width_tolerance", 8)
        )

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            background=colors["surface"],
            height=height,
        )
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Card.TFrame", padding=(2, 2, 10, 2))
        self.inner.bind("<Configure>", self._schedule_scrollregion_update)
        window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda event: self._resize_inner(window_id, event.width),
        )
        self.canvas.configure(yscrollcommand=vertical.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vertical.pack(side="right", fill="y")

        for field in self.fields:
            self._create_field(field)
        self.after_idle(lambda: self._layout_fields(False))

    def _schedule_scrollregion_update(self, _event: tk.Event | None = None) -> None:
        """Agrupa varios cambios internos en una sola actualización del scroll."""
        if self._scrollregion_job is not None:
            self.after_cancel(self._scrollregion_job)
        self._scrollregion_job = self.after(40, self._update_scrollregion)

    def _update_scrollregion(self) -> None:
        self._scrollregion_job = None
        bounds = self.canvas.bbox("all")
        if bounds is not None:
            self.canvas.configure(scrollregion=bounds)

    def _resize_inner(self, window_id: int, width: int) -> None:
        """Pospone el redibujado costoso hasta que el usuario pause el arrastre."""
        if width <= 1:
            return
        target_compact = width < self._responsive_breakpoint
        width_changed = abs(width - self._pending_canvas_width) >= self._width_tolerance
        layout_changed = self._compact is None or target_compact != self._compact
        if not width_changed and not layout_changed:
            return

        self._pending_canvas_width = width
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(
            self._resize_delay,
            lambda: self._apply_canvas_resize(window_id),
        )

    def _apply_canvas_resize(self, window_id: int) -> None:
        self._resize_job = None
        width = self._pending_canvas_width
        if width <= 1:
            return
        if abs(width - self._applied_canvas_width) >= self._width_tolerance:
            self.canvas.itemconfigure(window_id, width=width)
            self._applied_canvas_width = width
        self._layout_fields(width < self._responsive_breakpoint)
        self._schedule_scrollregion_update()

    def _create_field(self, field: Mapping[str, Any]) -> None:
        name = str(field["name"])
        text = f"{field.get('label', name)} ({field_type_display(field)})"
        if field.get("required", False):
            text += "  *"
        self.labels[name] = ttk.Label(self.inner, text=text, style="FieldLabel.TLabel")

        widget_type = str(field.get("widget", "entry")).lower()
        initial = default_value(field)
        if widget_type == "checkbox":
            variable: tk.Variable = tk.BooleanVar(value=bool(initial))
            widget: tk.Widget = ttk.Checkbutton(
                self.inner, variable=variable, style="Modern.TCheckbutton"
            )
        elif widget_type == "combobox":
            variable = tk.StringVar(value=str(initial))
            widget = ttk.Combobox(
                self.inner,
                textvariable=variable,
                values=list(field.get("options", [])),
                state="readonly",
                style="Modern.TCombobox",
            )
        elif widget_type == "multiline":
            variable = tk.StringVar(value=str(initial))
            text_widget = tk.Text(
                self.inner,
                height=4,
                wrap="word",
                font=("Segoe UI", 10),
                relief="solid",
                borderwidth=1,
                highlightthickness=0,
                background=self.colors["surface"],
                foreground=self.colors["text"],
                insertbackground=self.colors["text"],
            )
            text_widget.insert("1.0", str(initial))
            widget = text_widget
        else:
            variable = tk.StringVar(value=str(initial))
            widget = ttk.Entry(self.inner, textvariable=variable, style="Modern.TEntry")

        self.variables[name] = variable
        self.widgets[name] = widget
        hint = str(field.get("placeholder", ""))
        self.hints[name] = ttk.Label(
            self.inner, text=hint, style="Hint.TLabel", wraplength=220
        )

    def _layout_fields(self, compact: bool) -> None:
        if self._compact == compact:
            return
        self._compact = compact
        for child in self.inner.winfo_children():
            child.grid_forget()

        if compact:
            self.inner.columnconfigure(0, weight=1)
            self.inner.columnconfigure(1, weight=0)
            self.inner.columnconfigure(2, weight=0)
            for index, field in enumerate(self.fields):
                name = str(field["name"])
                base = index * 3
                self.labels[name].grid(row=base, column=0, sticky="w", pady=(8, 4))
                self.widgets[name].grid(row=base + 1, column=0, sticky="ew")
                if self.hints[name].cget("text"):
                    self.hints[name].grid(row=base + 2, column=0, sticky="w", pady=(3, 1))
        else:
            self.inner.columnconfigure(0, weight=0, minsize=160)
            self.inner.columnconfigure(1, weight=1)
            self.inner.columnconfigure(2, weight=0, minsize=150)
            for index, field in enumerate(self.fields):
                name = str(field["name"])
                self.labels[name].grid(
                    row=index, column=0, sticky="nw", padx=(0, 16), pady=9
                )
                self.widgets[name].grid(row=index, column=1, sticky="ew", pady=7)
                if self.hints[name].cget("text"):
                    self.hints[name].grid(
                        row=index, column=2, sticky="w", padx=(12, 0), pady=9
                    )

    def collect(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field in self.fields:
            name = str(field["name"])
            widget = self.widgets[name]
            values[name] = (
                widget.get("1.0", "end-1c")
                if isinstance(widget, tk.Text)
                else self.variables[name].get()
            )
        return values

    def clear(self) -> None:
        for field in self.fields:
            self._set_one(str(field["name"]), default_value(field))

    def set_values(self, values: Mapping[str, Any]) -> None:
        by_lower = {str(name).lower(): value for name, value in values.items()}
        for field in self.fields:
            name = str(field["name"])
            self._set_one(name, by_lower.get(name.lower(), ""))

    def _set_one(self, name: str, value: Any) -> None:
        widget = self.widgets[name]
        shown = display_value(value)
        if isinstance(widget, tk.Text):
            widget.delete("1.0", "end")
            widget.insert("1.0", str(shown))
        elif isinstance(self.variables[name], tk.BooleanVar):
            self.variables[name].set(bool(value))
        else:
            self.variables[name].set(shown)


class PageHeader(ttk.Frame):
    def __init__(self, parent: tk.Misc, eyebrow: str, title: str, subtitle: str) -> None:
        super().__init__(parent, style="Page.TFrame")
        ttk.Label(self, text=eyebrow.upper(), style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(self, text=title, style="PageTitle.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Label(self, text=subtitle, style="PageSubtitle.TLabel", wraplength=760).pack(
            anchor="w"
        )


class ConnectionPage(ttk.Frame):
    """Conexión, credenciales y selección de tabla dentro de la aplicación."""

    AUTH_MODES = ("SQL Server (usuario y contraseña)", "Windows")

    def __init__(self, parent: tk.Misc, app: "InsertFormApp") -> None:
        super().__init__(parent, style="Page.TFrame", padding=(22, 18))
        self.app = app
        self.references: dict[str, TableReference] = {}
        self.catalog: SQLServerCatalog | None = None
        self.active_config: dict[str, Any] | None = None
        profile = dict(app.connection_profile)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        PageHeader(
            self,
            "Acceso",
            "Conexión a SQL Server",
            "Ingresa la conexión, carga las tablas y selecciona con cuál deseas trabajar.",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        card = Card(self, padding=16)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(2):
            card.columnconfigure(column, weight=1)

        self.server = tk.StringVar(value=str(profile.get("server", "")))
        self.database = tk.StringVar(value=str(profile.get("database", "")))
        self.driver = tk.StringVar(value=str(profile.get("driver", "")))
        self.username = tk.StringVar(value=str(profile.get("username", "")))
        self.password = tk.StringVar(value=str(profile.get("password", "")))
        trusted = bool(profile.get("trusted_connection", False))
        self.auth_mode = tk.StringVar(
            value="Windows" if trusted else self.AUTH_MODES[0]
        )
        self.trust_certificate = tk.BooleanVar(
            value=bool(profile.get("trust_server_certificate", True))
        )
        self.remember = tk.BooleanVar(value=True)
        self.show_password = tk.BooleanVar(value=False)

        self._field(card, "Servidor", self.server, 0, 0)
        self._field(card, "Base de datos", self.database, 0, 1)
        ttk.Label(card, text="Autenticación", style="FieldLabel.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 4)
        )
        auth_combo = ttk.Combobox(
            card,
            textvariable=self.auth_mode,
            values=self.AUTH_MODES,
            state="readonly",
            style="Modern.TCombobox",
        )
        auth_combo.grid(row=3, column=0, sticky="ew", padx=(0, 8))
        auth_combo.bind("<<ComboboxSelected>>", lambda _event: self._toggle_auth())

        ttk.Label(card, text="Controlador ODBC", style="FieldLabel.TLabel").grid(
            row=2, column=1, sticky="w", pady=(10, 4)
        )
        driver_values = list(
            dict.fromkeys(
                [
                    self.driver.get(),
                    *profile.get("driver_candidates", []),
                    "ODBC Driver 18 for SQL Server",
                    "ODBC Driver 17 for SQL Server",
                ]
            )
        )
        ttk.Combobox(
            card,
            textvariable=self.driver,
            values=[value for value in driver_values if value],
            state="normal",
            style="Modern.TCombobox",
        ).grid(row=3, column=1, sticky="ew", padx=(8, 0))

        self.username_label = ttk.Label(
            card, text="Usuario", style="FieldLabel.TLabel"
        )
        self.username_label.grid(row=4, column=0, sticky="w", pady=(10, 4))
        self.username_entry = ttk.Entry(
            card, textvariable=self.username, style="Modern.TEntry"
        )
        self.username_entry.grid(row=5, column=0, sticky="ew", padx=(0, 8))
        self.password_label = ttk.Label(
            card, text="Contraseña", style="FieldLabel.TLabel"
        )
        self.password_label.grid(row=4, column=1, sticky="w", pady=(10, 4))
        password_holder = ttk.Frame(card, style="Card.TFrame")
        password_holder.grid(row=5, column=1, sticky="ew", padx=(8, 0))
        password_holder.columnconfigure(0, weight=1)
        self.password_entry = ttk.Entry(
            password_holder,
            textvariable=self.password,
            show="●",
            style="Modern.TEntry",
        )
        self.password_entry.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(
            password_holder,
            text="Mostrar",
            variable=self.show_password,
            command=self._toggle_password,
            style="Modern.TCheckbutton",
        ).grid(row=0, column=1, padx=(8, 0))

        options = ttk.Frame(card, style="Card.TFrame")
        options.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(13, 0))
        ttk.Checkbutton(
            options,
            text="Confiar en el certificado del servidor",
            variable=self.trust_certificate,
            style="Modern.TCheckbutton",
        ).pack(side="left")
        ttk.Checkbutton(
            options,
            text="Recordar esta conexión",
            variable=self.remember,
            style="Modern.TCheckbutton",
        ).pack(side="left", padx=18)

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.connect_button = ttk.Button(
            actions,
            text="Conectar y cargar tablas",
            command=self._connect,
            style="Primary.TButton",
        )
        self.connect_button.pack(side="left")
        ttk.Button(
            actions,
            text="Olvidar datos guardados",
            command=self._forget,
            style="Ghost.TButton",
        ).pack(side="left", padx=8)
        ttk.Label(
            actions,
            text="La contraseña se guarda en el almacén seguro del sistema.",
            style="Hint.TLabel",
        ).pack(side="right")

        table_card = Card(self, padding=16)
        table_card.grid(row=2, column=0, sticky="nsew")
        table_card.columnconfigure(0, weight=1)
        ttk.Label(table_card, text="Tabla de trabajo", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            table_card,
            text="Después de conectarte, elige una tabla visible para generar las demás páginas.",
            style="CardSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))
        self.selected_table = tk.StringVar(value=str(profile.get("last_table", "")))
        self.table_combo = ttk.Combobox(
            table_card,
            textvariable=self.selected_table,
            state="disabled",
            style="Modern.TCombobox",
        )
        self.table_combo.grid(row=2, column=0, sticky="ew")
        self.use_button = ttk.Button(
            table_card,
            text="Usar tabla seleccionada",
            command=self._use_table,
            style="Secondary.TButton",
            state="disabled",
        )
        self.use_button.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.progress = ttk.Progressbar(table_card, mode="indeterminate")
        self.progress.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.progress.grid_remove()
        self.status = StatusBar(self, "Completa los datos y conecta.")
        self.status.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._toggle_auth()

    @staticmethod
    def _field(
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
        column: int,
    ) -> None:
        ttk.Label(parent, text=label, style="FieldLabel.TLabel").grid(
            row=row, column=column, sticky="w", padx=(0, 8) if column == 0 else (8, 0)
        )
        ttk.Entry(parent, textvariable=variable, style="Modern.TEntry").grid(
            row=row + 1,
            column=column,
            sticky="ew",
            padx=(0, 8) if column == 0 else (8, 0),
            pady=(4, 0),
        )

    def _toggle_auth(self) -> None:
        sql_auth = self.auth_mode.get() != "Windows"
        state = "normal" if sql_auth else "disabled"
        self.username_entry.configure(state=state)
        self.password_entry.configure(state=state)

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_password.get() else "●")

    def _collect_config(self) -> dict[str, Any]:
        trusted = self.auth_mode.get() == "Windows"
        candidates = list(
            dict.fromkeys(
                [
                    self.driver.get().strip(),
                    *self.app.connection_profile.get("driver_candidates", []),
                    "ODBC Driver 18 for SQL Server",
                    "ODBC Driver 17 for SQL Server",
                ]
            )
        )
        return {
            "server": self.server.get().strip(),
            "database": self.database.get().strip(),
            "driver": self.driver.get().strip(),
            "driver_candidates": [item for item in candidates if item],
            "trusted_connection": trusted,
            "username": "" if trusted else self.username.get().strip(),
            "password": "" if trusted else self.password.get(),
            "trust_server_certificate": self.trust_certificate.get(),
            "connection_timeout": int(
                self.app.connection_profile.get("connection_timeout", 8)
            ),
        }

    def _set_busy(self, busy: bool, message: str) -> None:
        self.connect_button.configure(state="disabled" if busy else "normal")
        self.use_button.configure(
            state="disabled" if busy or not self.references else "normal"
        )
        self.table_combo.configure(
            state="disabled" if busy or not self.references else "readonly"
        )
        if busy:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self.status.set(message)

    def _error(self, title: str, message: str) -> None:
        self._set_busy(False, "No se completó la conexión.")
        self.status.set("No se completó la conexión.", "error")
        messagebox.showerror(title, message, parent=self)

    def _connect(self) -> None:
        config = self._collect_config()
        self.references.clear()
        self.table_combo.configure(values=[])
        self._set_busy(True, "Conectando y consultando las tablas disponibles...")
        catalog = SQLServerCatalog(config, self.app.selector_config)

        def completed(tables: Sequence[TableReference]) -> None:
            self.catalog = catalog
            self.active_config = config
            self.references = {table.qualified_name: table for table in tables}
            names = list(self.references)
            self.table_combo.configure(values=names)
            preferred = self.selected_table.get()
            self.selected_table.set(preferred if preferred in self.references else (names[0] if names else ""))
            self._set_busy(False, f"Conexión correcta: {len(names)} tabla(s) disponible(s).")
            self.status.set(
                f"Conexión correcta: {len(names)} tabla(s) disponible(s).", "success"
            )
            if self.remember.get():
                self._save_profile(config, self.selected_table.get())

        self.app.run_background(catalog.list_tables, completed, self._error)

    def _use_table(self) -> None:
        reference = self.references.get(self.selected_table.get())
        if reference is None or self.catalog is None or self.active_config is None:
            self._error("Tabla", "Conecta y selecciona una tabla válida.")
            return
        self._set_busy(True, "Leyendo columnas, tipos y claves de la tabla...")
        remembered = self.app.update_keys_by_table.get(reference.qualified_name)

        def operation() -> tuple[dict[str, Any], dict[str, Any], Any]:
            return self.catalog.build_configs(
                reference,
                self.app.base_form_config,
                self.app.base_update_config,
                override_keys=remembered,
            )

        def completed(result: tuple[dict[str, Any], dict[str, Any], Any]) -> None:
            form_config, update_config, columns = result
            if not update_config.get("enabled", False):
                if not self.app.base_update_config.get("enabled", True):
                    self._activate_table(reference, form_config, update_config)
                    return
                self._error(
                    "Actualizar",
                    "No hay columnas comparables para identificar los registros de esta tabla.",
                )
                return
            if remembered or update_config.get("key_requires_validation", False):
                self._validate_and_activate(
                    reference,
                    form_config,
                    columns,
                    list(remembered or update_config.get("key_fields", [])),
                )
                return
            self._activate_table(reference, form_config, update_config)

        self.app.run_background(operation, completed, self._error)

    def _request_update_key(
        self,
        reference: TableReference,
        form_config: Mapping[str, Any],
        columns: Sequence[ColumnMetadata],
    ) -> None:
        dialog = KeySelectionDialog(
            self,
            reference.qualified_name,
            columns,
            self.app.colors,
            self.app.font_family,
            self.app.update_keys_by_table.get(reference.qualified_name, ()),
        )
        self.wait_window(dialog)
        if dialog.result is None:
            self.status.set(
                "No se activó la tabla: falta una clave segura para UPDATE.", "error"
            )
            return
        self._validate_and_activate(reference, form_config, columns, dialog.result)

    def _validate_and_activate(
        self,
        reference: TableReference,
        form_config: Mapping[str, Any],
        columns: Sequence[ColumnMetadata],
        key_fields: Sequence[str],
    ) -> None:
        catalog = self.catalog
        if catalog is None:
            self._error("Tabla", "La conexión ya no está disponible.")
            return
        self._set_busy(True, "Comprobando que la clave elegida no tenga duplicados...")

        def operation() -> tuple[bool, dict[str, Any]]:
            unique = catalog.validate_unique_key(reference, key_fields, columns)
            if not unique:
                return False, {}
            _form, update, _columns = catalog.build_configs(
                reference,
                self.app.base_form_config,
                self.app.base_update_config,
                override_keys=key_fields,
            )
            return True, update

        def completed(result: tuple[bool, dict[str, Any]]) -> None:
            unique, update_config = result
            self._set_busy(False, "Comprobación terminada.")
            if not unique:
                self.app.update_keys_by_table.pop(reference.qualified_name, None)

                def fallback_operation() -> tuple[dict[str, Any], dict[str, Any], Any]:
                    return catalog.build_configs(
                        reference,
                        self.app.base_form_config,
                        self.app.base_update_config,
                        override_keys=[],
                    )

                def fallback_completed(
                    fallback: tuple[dict[str, Any], dict[str, Any], Any]
                ) -> None:
                    fallback_form, fallback_update, _fallback_columns = fallback
                    self._activate_table(reference, fallback_form, fallback_update)
                    messagebox.showinfo(
                        "Actualización por cantidad habilitada",
                        "La clave recordada contiene duplicados. La tabla se abrió en "
                        "modo de coincidencias, donde podrás elegir cuántas filas "
                        "idénticas actualizar.",
                        parent=self,
                    )

                self._set_busy(True, "Preparando actualización por coincidencias...")
                self.app.run_background(
                    fallback_operation, fallback_completed, self._error
                )
                return
            self.app.update_keys_by_table[reference.qualified_name] = list(key_fields)
            self._activate_table(reference, form_config, update_config)

        self.app.run_background(operation, completed, self._error)

    def _activate_table(
        self,
        reference: TableReference,
        form_config: Mapping[str, Any],
        update_config: Mapping[str, Any],
    ) -> None:
        if self.remember.get():
            self._save_profile(self.active_config or {}, reference.qualified_name)
        self.app.activate_connection(
            self.active_config or {},
            form_config,
            update_config,
        )
        self._set_busy(False, f"Tabla activa: {reference.qualified_name}.")
        self.status.set(f"Tabla activa: {reference.qualified_name}.", "success")

    def _save_profile(self, config: Mapping[str, Any], last_table: str) -> None:
        try:
            saved = dict(config)
            saved["update_keys_by_table"] = dict(self.app.update_keys_by_table)
            self.app.profile_store.save(saved, last_table)
        except ConfigurationError as exc:
            messagebox.showwarning(
                "Guardar conexión",
                "La conexión funciona, pero no se pudo recordar.\n\n" + str(exc),
                parent=self,
            )

    def _forget(self) -> None:
        if not messagebox.askyesno(
            "Olvidar conexión",
            "¿Deseas borrar el perfil y la contraseña guardados?",
            parent=self,
        ):
            return
        try:
            self.app.profile_store.forget()
        except ConfigurationError as exc:
            self._error("Perfil", str(exc))
            return
        self.password.set("")
        self.username.set("")
        self.server.set("")
        self.database.set("")
        self.driver.set("ODBC Driver 18 for SQL Server")
        self.selected_table.set("")
        self.status.set("Datos guardados eliminados.", "success")


class InsertPage(ttk.Frame):
    def __init__(self, parent: tk.Misc, app: "InsertFormApp") -> None:
        super().__init__(parent, style="Page.TFrame", padding=(22, 18))
        self.app = app
        self.repository = app.repository
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        PageHeader(
            self,
            "Registros",
            "Nuevo registro",
            f"Completa los datos para insertar una fila en {self.repository.schema}.{self.repository.table}.",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))

        card = Card(self, padding=18)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)
        ttk.Label(card, text="Datos del registro", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text="Los campos marcados con * son obligatorios.",
            style="CardSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))
        self.form = ScrollableForm(
            card,
            self.repository.fields,
            app.colors,
            app.ui,
            height=390,
        )
        self.form.grid(row=2, column=0, sticky="nsew")

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        self.insert_button = ttk.Button(
            actions,
            text="Insertar registro",
            command=self._insert,
            style="Primary.TButton",
        )
        self.insert_button.pack(side="left")
        ttk.Button(
            actions, text="Limpiar", command=self._clear, style="Secondary.TButton"
        ).pack(side="left", padx=8)
        ttk.Button(
            actions,
            text="Probar conexión",
            command=self._test,
            style="Ghost.TButton",
        ).pack(side="left")

        self.status = StatusBar(self, "Listo para insertar un nuevo registro.")
        self.status.grid(row=2, column=0, sticky="ew", pady=(12, 0))

    def _set_busy(self, busy: bool, message: str) -> None:
        self.insert_button.configure(state="disabled" if busy else "normal")
        self.status.set(message)

    def _error(self, title: str, message: str) -> None:
        self._set_busy(False, "No se completó la operación.")
        self.status.set("No se completó la operación.", "error")
        messagebox.showerror(title, message, parent=self)

    def _insert(self) -> None:
        raw = self.form.collect()
        try:
            self.repository.prepare_values(raw)
        except (ValidationError, ConfigurationError) as exc:
            self._error("Validación", str(exc))
            return
        self._set_busy(True, "Insertando registro...")

        def completed(generated_id: Any) -> None:
            suffix = f" ID generado: {generated_id}." if generated_id is not None else ""
            self._set_busy(False, "Registro insertado correctamente." + suffix)
            self.status.set("Registro insertado correctamente." + suffix, "success")
            messagebox.showinfo(
                "Inserción correcta",
                "El registro fue guardado en SQL Server." + suffix,
                parent=self,
            )
            self.form.clear()

        self.app.run_background(lambda: self.repository.insert(raw), completed, self._error)

    def _test(self) -> None:
        self._set_busy(True, "Probando conexión y configuración...")

        def operation() -> None:
            self.repository.test_connection()
            self.repository.validate_table_structure()

        def completed(_result: Any) -> None:
            self._set_busy(False, "Conexión y estructura verificadas.")
            self.status.set("Conexión y estructura verificadas.", "success")
            messagebox.showinfo(
                "Conexión correcta",
                "SQL Server respondió y la configuración coincide con la tabla.",
                parent=self,
            )

        self.app.run_background(operation, completed, self._error)

    def _clear(self) -> None:
        self.form.clear()
        self.status.set("Formulario limpio.")


class UpdatePage(ttk.Frame):
    MODE_LABELS = {"Contiene": "contains", "Exacto": "exact"}

    def __init__(self, parent: tk.Misc, app: "InsertFormApp") -> None:
        super().__init__(parent, style="Page.TFrame", padding=(22, 18))
        self.app = app
        self.repository = app.repository
        self.rows: dict[str, dict[str, Any]] = {}
        self.original_row: dict[str, Any] | None = None
        self.match_total = 0
        self._metadata_loaded = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)
        self.rowconfigure(4, weight=2)

        PageHeader(
            self,
            "Administración",
            "Buscar y actualizar",
            "Filtra por cualquier columna, selecciona una fila y modifica sus valores.",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        search_card = Card(self, padding=14)
        search_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column, weight in enumerate((1, 1, 2)):
            search_card.columnconfigure(column, weight=weight)

        ttk.Label(search_card, text="Columna", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(search_card, text="Coincidencia", style="FieldLabel.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Label(search_card, text="Valor de búsqueda", style="FieldLabel.TLabel").grid(
            row=0, column=2, sticky="w", padx=(10, 0)
        )

        initial_columns = list(
            dict.fromkeys(
                [str(field["name"]) for field in self.repository.fields]
                + self.repository.key_fields
            )
        )
        self.search_column = tk.StringVar(value=initial_columns[0] if initial_columns else "")
        self.column_combo = ttk.Combobox(
            search_card,
            textvariable=self.search_column,
            values=initial_columns,
            state="readonly",
            style="Modern.TCombobox",
        )
        self.column_combo.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        default_mode = str(self.repository.update_config.get("default_search_mode", "contains"))
        self.search_mode = tk.StringVar(value="Exacto" if default_mode == "exact" else "Contiene")
        ttk.Combobox(
            search_card,
            textvariable=self.search_mode,
            values=list(self.MODE_LABELS),
            state="readonly",
            style="Modern.TCombobox",
        ).grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(5, 0))

        self.search_value = tk.StringVar()
        value_entry = ttk.Entry(
            search_card, textvariable=self.search_value, style="Modern.TEntry"
        )
        value_entry.grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(5, 0))
        value_entry.bind("<Return>", lambda _event: self._search())

        actions = ttk.Frame(search_card, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.search_button = ttk.Button(
            actions, text="Buscar", command=self._search, style="Primary.TButton"
        )
        self.search_button.pack(side="left")
        self.all_button = ttk.Button(
            actions, text="Mostrar todos", command=self._show_all, style="Secondary.TButton"
        )
        self.all_button.pack(side="left", padx=8)
        self.columns_button = ttk.Button(
            actions,
            text="Actualizar columnas",
            command=lambda: self._load_columns(force=True),
            style="Ghost.TButton",
        )
        self.columns_button.pack(side="left")

        results_card = Card(self, padding=12)
        results_card.grid(row=2, column=0, sticky="nsew")
        results_card.columnconfigure(0, weight=1)
        results_card.rowconfigure(1, weight=1)
        title_row = ttk.Frame(results_card, style="Card.TFrame")
        title_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(title_row, text="Resultados", style="CardTitle.TLabel").pack(side="left")
        self.result_count = tk.StringVar(value="Sin búsqueda")
        ttk.Label(title_row, textvariable=self.result_count, style="Badge.TLabel").pack(
            side="right"
        )

        tree_holder = ttk.Frame(results_card, style="Card.TFrame")
        tree_holder.grid(row=1, column=0, sticky="nsew")
        tree_holder.columnconfigure(0, weight=1)
        tree_holder.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            tree_holder, show="headings", selectmode="browse", style="Modern.Treeview"
        )
        vertical = ttk.Scrollbar(tree_holder, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(tree_holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("even", background=app.colors["surface"])
        self.tree.tag_configure("odd", background=app.colors["surface_alt"])
        self.tree.bind("<Double-1>", lambda _event: self._load_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._selection_changed())

        result_actions = ttk.Frame(results_card, style="Card.TFrame")
        result_actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.edit_button = ttk.Button(
            result_actions,
            text="Editar seleccionado",
            command=self._load_selected,
            style="Secondary.TButton",
            state="disabled",
        )
        self.edit_button.pack(side="left")
        ttk.Label(
            result_actions,
            text="También puedes hacer doble clic sobre una fila.",
            style="Hint.TLabel",
        ).pack(side="left", padx=10)

        ttk.Separator(self, orient="horizontal").grid(
            row=3, column=0, sticky="ew", pady=10
        )

        editor_card = Card(self, padding=12)
        editor_card.grid(row=4, column=0, sticky="nsew")
        editor_card.columnconfigure(0, weight=1)
        editor_card.rowconfigure(1, weight=1)
        editor_header = ttk.Frame(editor_card, style="Card.TFrame")
        editor_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            editor_header, text="Editar registro seleccionado", style="CardTitle.TLabel"
        ).pack(side="left")
        self.match_summary = tk.StringVar(value="Selecciona un registro para editar.")
        self.update_quantity = tk.StringVar(value="1")
        self.edit_form = ScrollableForm(
            editor_card,
            self.repository.editable_fields(),
            app.colors,
            app.ui,
            height=170,
        )
        self.edit_form.grid(row=1, column=0, sticky="nsew")

        editor_actions = ttk.Frame(editor_card, style="Card.TFrame")
        editor_actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            editor_actions, textvariable=self.match_summary, style="Hint.TLabel"
        ).pack(side="left")
        self.quantity_label = ttk.Label(
            editor_actions, text="Cantidad:", style="FieldLabel.TLabel"
        )
        self.quantity_label.pack(side="left", padx=(18, 5))
        self.quantity_spin = ttk.Spinbox(
            editor_actions,
            textvariable=self.update_quantity,
            from_=1,
            to=1,
            width=8,
            justify="center",
            style="Modern.TSpinbox",
            state="disabled",
        )
        self.quantity_spin.pack(side="left")
        self.update_button = ttk.Button(
            editor_actions,
            text="Actualizar registro",
            command=self._update,
            style="Primary.TButton",
            state="disabled",
        )
        self.update_button.pack(side="right")
        ttk.Button(
            editor_actions,
            text="Cancelar",
            command=self._cancel_edit,
            style="Ghost.TButton",
        ).pack(side="right", padx=8)

        self.status = StatusBar(self, "Las columnas se cargarán automáticamente.")
        self.status.grid(row=5, column=0, sticky="ew", pady=(10, 0))

    def on_show(self) -> None:
        if not self._metadata_loaded:
            self._load_columns()

    def _set_busy(self, busy: bool, message: str) -> None:
        state = "disabled" if busy else "normal"
        self.search_button.configure(state=state)
        self.all_button.configure(state=state)
        self.columns_button.configure(state=state)
        self.edit_button.configure(
            state="disabled" if busy or not self.tree.selection() else "normal"
        )
        self.update_button.configure(
            state=(
                "disabled"
                if busy
                or self.original_row is None
                or (self.repository.non_unique_mode and self.match_total < 1)
                else "normal"
            )
        )
        self.quantity_spin.configure(
            state=(
                "normal"
                if not busy
                and self.repository.non_unique_mode
                and self.original_row is not None
                and self.match_total > 0
                else "disabled"
            )
        )
        self.status.set(message)

    def _error(self, title: str, message: str) -> None:
        self._set_busy(False, "No se completó la operación.")
        self.status.set("No se completó la operación.", "error")
        messagebox.showerror(title, message, parent=self)

    def _load_columns(self, force: bool = False) -> None:
        if self._metadata_loaded and not force:
            return
        self._set_busy(True, "Leyendo las columnas disponibles...")

        def completed(metadata: Mapping[str, Sequence[str]]) -> None:
            columns = list(metadata["searchable"])
            self.column_combo.configure(values=columns)
            if columns and self.search_column.get() not in columns:
                self.search_column.set(columns[0])
            self._metadata_loaded = True
            self._set_busy(False, f"{len(columns)} columnas disponibles para buscar.")
            self.status.set(f"{len(columns)} columnas disponibles para buscar.", "success")

        self.app.run_background(self.repository.get_update_metadata, completed, self._error)

    def _search(self) -> None:
        column = self.search_column.get().strip()
        if not column:
            self._error("Validación", "Selecciona una columna para buscar.")
            return
        mode = self.MODE_LABELS[self.search_mode.get()]
        self._execute_search(column, self.search_value.get(), mode)

    def _show_all(self) -> None:
        self._execute_search(None, "", "exact")

    def _execute_search(self, column: str | None, value: str, mode: str) -> None:
        self._set_busy(True, "Buscando registros...")

        def completed(result: tuple[list[str], list[dict[str, Any]]]) -> None:
            columns, rows = result
            self._show_results(columns, rows)
            self._set_busy(False, f"Búsqueda terminada: {len(rows)} resultado(s).")
            self.status.set(f"Búsqueda terminada: {len(rows)} resultado(s).", "success")

        self.app.run_background(
            lambda: self.repository.search(column, value, mode), completed, self._error
        )

    def _show_results(
        self, columns: Sequence[str], rows: Sequence[dict[str, Any]]
    ) -> None:
        self.tree.delete(*self.tree.get_children())
        visible_columns = ["__row_number__", *columns]
        self.tree.configure(columns=visible_columns)
        self.tree.heading("__row_number__", text="N°")
        self.tree.column("__row_number__", width=58, minwidth=48, stretch=False)
        for column in columns:
            sql_type = self.repository.column_types.get(column.casefold(), "")
            heading = f"{column} ({sql_type})" if sql_type else column
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=185, minwidth=100, stretch=True)
        self.rows.clear()
        for index, row in enumerate(rows):
            iid = str(index)
            self.rows[iid] = dict(row)
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=[index + 1, *[display_value(row.get(name)) for name in columns]],
                tags=("even" if index % 2 == 0 else "odd",),
            )
        self.result_count.set(f"{len(rows)} resultado(s)")
        self._cancel_edit()

    def _selection_changed(self) -> None:
        self.edit_button.configure(state="normal" if self.tree.selection() else "disabled")

    def _load_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self._error("Selección", "Selecciona un registro de la tabla de resultados.")
            return
        self.original_row = dict(self.rows[selection[0]])
        self.edit_form.set_values(self.original_row)
        self.match_total = 0
        self.update_quantity.set("1")
        if self.repository.non_unique_mode:
            self.match_summary.set("Contando registros con los mismos valores...")
            self.update_button.configure(state="disabled")
            self.quantity_spin.configure(state="disabled")
            self._set_busy(True, "Comprobando coincidencias idénticas...")

            def completed(total: int) -> None:
                self.match_total = total
                self._set_busy(False, f"Se encontraron {total:,} coincidencia(s).")
                if total < 1:
                    self._cancel_edit()
                    self._error(
                        "Registro no disponible",
                        "El registro cambió o fue eliminado después de la búsqueda.",
                    )
                    return
                self.quantity_spin.configure(from_=1, to=total, state="normal")
                self.update_button.configure(text="Actualizar cantidad", state="normal")
                self.match_summary.set(f"Coincidencias idénticas: {total:,}")
                self.status.set(
                    f"Hay {total:,} registro(s) con estos valores. "
                    "Indica cuántos deseas actualizar.",
                    "success",
                )

            self.app.run_background(
                lambda: self.repository.count_matching_rows(self.original_row or {}),
                completed,
                self._error,
            )
            return

        self.match_total = 1
        self.match_summary.set("Registro identificado por clave única.")
        self.quantity_spin.configure(from_=1, to=1, state="disabled")
        self.update_button.configure(text="Actualizar registro", state="normal")
        key_text = ", ".join(
            f"{key}={self._value_case_insensitive(self.original_row, key)!r}"
            for key in self.repository.key_fields
        )
        self.status.set("Registro listo para editar: " + key_text, "success")

    @staticmethod
    def _value_case_insensitive(values: Mapping[str, Any], wanted: str) -> Any:
        for name, value in values.items():
            if str(name).lower() == wanted.lower():
                return value
        return None

    def _update(self) -> None:
        if self.original_row is None:
            self._error("Selección", "Primero selecciona un registro para editar.")
            return
        requested = 1
        if self.repository.non_unique_mode:
            try:
                requested = int(self.update_quantity.get())
            except ValueError:
                self._error("Cantidad", "Escribe una cantidad entera.")
                return
            if not 1 <= requested <= self.match_total:
                self._error(
                    "Cantidad",
                    f"La cantidad debe estar entre 1 y {self.match_total:,}.",
                )
                return
        confirmation = (
            f"Se encontraron {self.match_total:,} registros idénticos.\n\n"
            f"Se actualizarán exactamente {requested:,}. ¿Deseas continuar?"
            if self.repository.non_unique_mode
            else "¿Deseas guardar los cambios en el registro seleccionado?"
        )
        if not messagebox.askyesno(
            "Confirmar actualización",
            confirmation,
            parent=self,
        ):
            return
        raw = self.edit_form.collect()
        original = dict(self.original_row)
        self._set_busy(True, "Actualizando el registro...")

        def completed(result: Any) -> None:
            affected = int(getattr(result, "affected", result))
            matched = int(getattr(result, "matched", 1))
            requested_result = int(getattr(result, "requested", 1))
            self._set_busy(False, f"Actualización correcta: {affected:,} registro(s).")
            self.status.set(
                f"Actualización correcta: {affected:,} registro(s).", "success"
            )
            messagebox.showinfo(
                "Actualización correcta · Log generado",
                f"Coincidencias originales: {matched:,}\n"
                f"Cantidad solicitada: {requested_result:,}\n"
                f"Filas actualizadas: {affected:,}\n"
                "Transacción: COMMIT\n\n"
                "El SQL parametrizado y el detalle quedaron disponibles en SQL / Logs.",
                parent=self,
            )
            self._cancel_edit()
            if self.search_value.get().strip():
                self._search()
            else:
                self._show_all()
            if self.app.log_enabled:
                self.app.show_page("logs")

        if self.repository.non_unique_mode:
            operation = lambda: self.repository.update_matching_rows(
                raw, original, requested
            )
        else:
            operation = lambda: self.repository.update(raw, original)
        self.app.run_background(operation, completed, self._error)

    def _cancel_edit(self) -> None:
        self.original_row = None
        self.match_total = 0
        self.match_summary.set("Selecciona un registro para editar.")
        self.update_quantity.set("1")
        self.edit_form.clear()
        self.quantity_spin.configure(state="disabled")
        self.update_button.configure(text="Actualizar registro", state="disabled")


class BulkInsertPage(ttk.Frame):
    """Selección, validación, vista previa e inserción masiva desde Excel."""

    def __init__(self, parent: tk.Misc, app: "InsertFormApp") -> None:
        super().__init__(parent, style="Page.TFrame", padding=(22, 18))
        self.app = app
        self.repository = app.repository
        self.config = app.bulk_config
        self.service = ExcelImportService(self.repository.fields, self.config)
        self.field_by_name = {
            str(field["name"]).casefold(): field for field in self.repository.fields
        }
        expected_headers = "\n".join(
            f"• {field['name']} ({field_type_display(field)}) — "
            + ("obligatoria" if field.get("required", False) else "opcional / permite vacío")
            for field in self.repository.fields
        )
        self.expected_headers_message = (
            "Cabeceras exactas que debe tener el Excel:\n" + expected_headers
        )
        self.import_data: ExcelImportData | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        PageHeader(
            self,
            "Importación",
            "Insertar desde Excel",
            "Valida las cabeceras y tipos antes de insertar todas las filas en una sola transacción.",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        file_card = Card(self, padding=16)
        file_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        file_card.columnconfigure(0, weight=1)
        ttk.Label(file_card, text="Archivo de origen", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            file_card,
            text="Las cabeceras deben coincidir con las columnas detectadas para esta tabla.",
            style="CardSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))

        selector = ttk.Frame(file_card, style="Card.TFrame")
        selector.grid(row=2, column=0, sticky="ew")
        selector.columnconfigure(0, weight=1)
        self.file_path = tk.StringVar(value="Ningún archivo seleccionado")
        ttk.Label(
            selector,
            textvariable=self.file_path,
            style="FieldLabel.TLabel",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.select_button = ttk.Button(
            selector,
            text="Seleccionar Excel",
            command=self._select_file,
            style="Secondary.TButton",
        )
        self.select_button.grid(row=0, column=1)
        self.clear_button = ttk.Button(
            selector,
            text="Limpiar",
            command=self._clear,
            style="Ghost.TButton",
        )
        self.clear_button.grid(row=0, column=2, padx=(8, 0))

        self.file_info = tk.StringVar(
            value="Los nombres del Excel deben coincidir exactamente con esta lista."
        )
        ttk.Label(
            file_card,
            textvariable=self.file_info,
            style="Hint.TLabel",
            justify="left",
            wraplength=900,
        ).grid(
            row=3, column=0, sticky="w", pady=(9, 0)
        )
        schema_holder = ttk.Frame(file_card, style="Card.TFrame")
        schema_holder.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        schema_holder.columnconfigure(0, weight=1)
        self.schema_text = tk.Text(
            schema_holder,
            height=min(max(len(self.repository.fields) + 1, 3), 6),
            wrap="word",
            font=("Consolas", 9),
            relief="flat",
            background=app.colors["surface_alt"],
            foreground=app.colors["text"],
            padx=10,
            pady=8,
        )
        schema_scroll = ttk.Scrollbar(
            schema_holder, orient="vertical", command=self.schema_text.yview
        )
        self.schema_text.configure(yscrollcommand=schema_scroll.set)
        self.schema_text.grid(row=0, column=0, sticky="ew")
        schema_scroll.grid(row=0, column=1, sticky="ns")
        self.schema_text.insert("1.0", self.expected_headers_message)
        self.schema_text.configure(state="disabled")
        self.progress = ttk.Progressbar(file_card, mode="indeterminate")
        self.progress.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.progress.grid_remove()

        preview_card = Card(self, padding=12)
        preview_card.grid(row=2, column=0, sticky="nsew")
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(1, weight=1)
        preview_header = ttk.Frame(preview_card, style="Card.TFrame")
        preview_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(preview_header, text="Vista previa", style="CardTitle.TLabel").pack(
            side="left"
        )
        self.row_badge = tk.StringVar(value="Sin archivo")
        ttk.Label(
            preview_header, textvariable=self.row_badge, style="Badge.TLabel"
        ).pack(side="right")

        tree_holder = ttk.Frame(preview_card, style="Card.TFrame")
        tree_holder.grid(row=1, column=0, sticky="nsew")
        tree_holder.columnconfigure(0, weight=1)
        tree_holder.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            tree_holder,
            show="headings",
            selectmode="browse",
            style="Modern.Treeview",
        )
        vertical = ttk.Scrollbar(tree_holder, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(
            tree_holder, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("even", background=app.colors["surface"])
        self.tree.tag_configure("odd", background=app.colors["surface_alt"])

        actions = ttk.Frame(preview_card, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.insert_button = ttk.Button(
            actions,
            text="Insertar filas validadas",
            command=self._insert_all,
            style="Primary.TButton",
            state="disabled",
        )
        self.insert_button.pack(side="left")
        ttk.Label(
            actions,
            text="Si alguna inserción falla, se revierte toda la operación.",
            style="Hint.TLabel",
        ).pack(side="left", padx=12)

        self.status = StatusBar(self, "Esperando un archivo Excel.")
        self.status.grid(row=3, column=0, sticky="ew", pady=(10, 0))

    def _set_busy(self, busy: bool, message: str) -> None:
        state = "disabled" if busy else "normal"
        self.select_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.insert_button.configure(
            state="disabled" if busy or self.import_data is None else "normal"
        )
        if busy:
            self.progress.grid()
            if str(self.progress.cget("mode")) == "indeterminate":
                self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self.status.set(message)

    def _error(self, title: str, message: str) -> None:
        self._set_busy(False, "No se completó la operación.")
        self.status.set("No se completó la operación.", "error")
        messagebox.showerror(title, message, parent=self)

    def _select_file(self) -> None:
        extensions = [
            str(extension)
            for extension in self.config.get("allowed_extensions", [".xlsx", ".xlsm"])
        ]
        patterns = " ".join(f"*{extension}" for extension in extensions)
        selected = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar archivo Excel",
            filetypes=[("Archivos Excel", patterns), ("Todos los archivos", "*.*")],
        )
        if selected:
            self._load_file(selected)

    def _load_file(self, selected: str) -> None:
        self.import_data = None
        self.insert_button.configure(state="disabled")
        self.file_path.set(str(Path(selected).name))
        self.file_info.set("Validando cabeceras, tipos y filas...")
        self.progress.configure(mode="indeterminate", value=0)
        self._clear_preview()
        self._set_busy(True, "Leyendo y validando el archivo Excel...")

        def completed(data: ExcelImportData) -> None:
            self.import_data = data
            self._show_preview(data)
            self.file_info.set(
                f"Hoja: {data.sheet_name}  •  {data.row_count:,} filas válidas  •  "
                f"{len(data.columns)} columnas"
            )
            self._set_busy(False, "Archivo validado y listo para insertar.")
            self.status.set("Archivo validado y listo para insertar.", "success")

        self.app.run_background(lambda: self.service.load(selected), completed, self._error)

    def _show_preview(self, data: ExcelImportData) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=data.columns)
        for column in data.columns:
            field = self.field_by_name.get(str(column).casefold(), {})
            sql_type = field_type_display(field) if field else ""
            heading = f"{column} ({sql_type})" if sql_type else str(column)
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=175, minwidth=100, stretch=True)
        for index, row in enumerate(data.preview_rows):
            self.tree.insert(
                "",
                "end",
                values=[display_value(row.get(column)) for column in data.columns],
                tags=("even" if index % 2 == 0 else "odd",),
            )
        self.row_badge.set(f"{len(data.preview_rows)} de {data.row_count:,} filas")

    def _clear_preview(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=())
        self.row_badge.set("Sin archivo")

    def _insert_all(self) -> None:
        data = self.import_data
        if data is None:
            self._error("Validación", "Primero selecciona y valida un archivo Excel.")
            return
        if not messagebox.askyesno(
            "Confirmar inserción masiva",
            f"¿Deseas insertar {data.row_count:,} filas en "
            f"{self.repository.schema}.{self.repository.table}?",
            parent=self,
        ):
            return
        batch_size = int(self.config.get("batch_size", 500))
        total_batches = (data.row_count + batch_size - 1) // batch_size
        self.progress.configure(mode="determinate", maximum=data.row_count, value=0)
        self._set_busy(True, f"Insertando {data.row_count:,} filas...")

        def operation() -> int:
            self.repository.validate_insert_structure()

            def report(inserted: int, total: int, batch: int) -> None:
                self.app.after(
                    0,
                    lambda: self._show_progress(inserted, total, batch, total_batches),
                )

            return self.repository.bulk_insert(
                data.prepared_rows,
                batch_size,
                progress_callback=report,
                source_file=data.file_path,
            )

        def completed(inserted: int) -> None:
            self._set_busy(False, f"Se insertaron {inserted:,} filas correctamente.")
            self.status.set(
                f"Se insertaron {inserted:,} filas correctamente.", "success"
            )
            messagebox.showinfo(
                "Inserción masiva correcta",
                f"Se guardaron {inserted:,} filas en SQL Server.",
                parent=self,
            )
            self._clear()

        self.app.run_background(operation, completed, self._error)

    def _show_progress(
        self,
        inserted: int,
        total: int,
        batch: int,
        total_batches: int,
    ) -> None:
        self.progress.configure(value=inserted)
        self.status.set(
            f"Lote {batch:,} de {total_batches:,}: {inserted:,} de {total:,} filas enviadas."
        )

    def _clear(self) -> None:
        self.import_data = None
        self.file_path.set("Ningún archivo seleccionado")
        self.file_info.set(
            "Los nombres del Excel deben coincidir exactamente con esta lista."
        )
        self._clear_preview()
        self.insert_button.configure(state="disabled")
        self.status.set("Esperando un archivo Excel.")


class LogPage(ttk.Frame):
    """Muestra el SQL parametrizado y el historial local de operaciones."""

    def __init__(self, parent: tk.Misc, app: "InsertFormApp") -> None:
        super().__init__(parent, style="Page.TFrame", padding=(22, 18))
        self.app = app
        self.repository = app.repository
        self.logger = app.operation_logger
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        PageHeader(
            self,
            "Auditoría",
            "SQL y registro de operaciones",
            "Muestra la estructura parametrizada; nunca guarda contraseñas ni valores de las filas.",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        sql_card = Card(self, padding=14)
        sql_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        sql_card.columnconfigure(0, weight=1)
        header = ttk.Frame(sql_card, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(header, text="SQL generado", style="CardTitle.TLabel").pack(
            side="left"
        )
        ttk.Button(
            header,
            text="Copiar SQL",
            command=self._copy_sql,
            style="Secondary.TButton",
        ).pack(side="right")
        self.sql_text = tk.Text(
            sql_card,
            height=6,
            wrap="word",
            font=("Consolas", 10),
            relief="flat",
            background=app.colors["surface_alt"],
            foreground=app.colors["text"],
            padx=12,
            pady=10,
        )
        self.sql_text.grid(row=1, column=0, sticky="ew")
        self.sql_text.insert("1.0", self._sql_preview())
        self.sql_text.configure(state="disabled")

        log_card = Card(self, padding=14)
        log_card.grid(row=2, column=0, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        log_header = ttk.Frame(log_card, style="Card.TFrame")
        log_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(log_header, text="Historial", style="CardTitle.TLabel").pack(
            side="left"
        )
        ttk.Button(
            log_header,
            text="Actualizar",
            command=self.refresh,
            style="Ghost.TButton",
        ).pack(side="right")
        if self.logger is not None:
            ttk.Label(
                log_header,
                text=f"Archivo: {self.logger.path.name}",
                style="Hint.TLabel",
            ).pack(side="right", padx=12)

        holder = ttk.Frame(log_card, style="Card.TFrame")
        holder.grid(row=1, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            holder,
            wrap="none",
            font=("Consolas", 9),
            relief="flat",
            background=app.colors["surface_alt"],
            foreground=app.colors["text"],
            padx=12,
            pady=10,
        )
        vertical = ttk.Scrollbar(holder, orient="vertical", command=self.log_text.yview)
        horizontal = ttk.Scrollbar(
            holder, orient="horizontal", command=self.log_text.xview
        )
        self.log_text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.refresh()

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        content = (
            self.logger.read_latest()
            if self.logger is not None
            else "El registro de operaciones está deshabilitado."
        )
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", content)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _copy_sql(self) -> None:
        sql = self._sql_preview()
        self.clipboard_clear()
        self.clipboard_append(sql)
        messagebox.showinfo("SQL copiado", "El SQL generado fue copiado.", parent=self)

    def _sql_preview(self) -> str:
        manual = self.repository.build_insert_statement(include_identity_output=True)
        bulk = self.repository.build_insert_statement(include_identity_output=False)
        sections: list[str] = []
        if manual == bulk:
            sections.append("INSERT manual y masivo:\n" + bulk)
        else:
            sections.extend(
                ("INSERT manual:\n" + manual, "INSERT masivo:\n" + bulk)
            )
        if self.repository.update_enabled:
            editable = [
                str(field["name"]) for field in self.repository.editable_fields()
            ]
            if self.repository.non_unique_mode:
                sections.append(
                    "UPDATE por cantidad (ejemplo para 1 fila; TOP cambia según la GUI):\n"
                    + self.repository.build_match_count_statement(lock_rows=True)
                    + "\n"
                    + self.repository.build_limited_update_statement(editable, 1)
                )
            else:
                sections.append(
                    "UPDATE por clave única:\n"
                    + self.repository.build_update_statement(editable)
                )
        return "\n\n".join(sections)


class InsertFormApp(tk.Tk):
    def __init__(
        self,
        repository: SQLServerRepository,
        form_config: Mapping[str, Any],
        ui_config: Mapping[str, Any] | None = None,
        bulk_config: Mapping[str, Any] | None = None,
        connection_profile: Mapping[str, Any] | None = None,
        profile_store: CredentialProfileStore | None = None,
        selector_config: Mapping[str, Any] | None = None,
        base_update_config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.form_config = form_config
        self.base_form_config = dict(form_config)
        self.base_update_config = dict(base_update_config or repository.update_config)
        self.connection_profile = dict(connection_profile or repository.db_config)
        stored_update_keys = self.connection_profile.get("update_keys_by_table", {})
        self.update_keys_by_table: dict[str, list[str]] = (
            {
                str(table): [str(column) for column in columns]
                for table, columns in stored_update_keys.items()
                if isinstance(columns, (list, tuple))
            }
            if isinstance(stored_update_keys, Mapping)
            else {}
        )
        self.profile_store = profile_store or CredentialProfileStore()
        self.selector_config = dict(selector_config or {})
        self.ui = dict(ui_config or {})
        self.bulk_config = dict(bulk_config or {"enabled": False})
        self.bulk_enabled = bool(self.bulk_config.get("enabled", False))
        self.operation_logger = repository.operation_logger
        self.log_enabled = bool(
            self.operation_logger is not None and self.operation_logger.enabled
        )
        self.sidebar_hint_text = "SQL SERVER\nSin conexión activa"
        self.colors = {
            "background": "#0E0E10",
            "surface": "#171719",
            "surface_alt": "#202024",
            "topbar": "#050505",
            "topbar_dark": "#111113",
            "sidebar": "#0A0A0B",
            "sidebar_hover": "#1D1D20",
            "sidebar_active": "#303035",
            "primary": "#45454C",
            "primary_hover": "#5A5A63",
            "text": "#F4F4F5",
            "muted": "#A1A1AA",
            "border": "#34343A",
            "success": "#6EE7B7",
            "danger": "#FB7185",
            "selection": "#3A3A41",
            **dict(self.ui.get("colors", {})),
        }
        self.font_family = str(self.ui.get("font_family", "Segoe UI"))
        self.sidebar_width = int(self.ui.get("sidebar_width", 224))
        self.sidebar_collapsed_width = int(self.ui.get("sidebar_collapsed_width", 68))
        self.breakpoint = int(self.ui.get("responsive_breakpoint", 900))
        self._resize_delay = int(self.ui.get("resize_debounce_ms", 110))
        self.sidebar_collapsed = False
        self._automatic_collapse = False
        self._resize_job: str | None = None
        self._pending_auto_collapse = False
        self._pending_window_width = 1
        self._pending_window_height = 1
        self._applied_window_width = 0
        self._applied_window_height = 0
        self._window_width_tolerance = int(
            self.ui.get("resize_width_tolerance", 8)
        )
        self.current_page = "connection"
        self.pages: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.brand_logo: Any | None = None
        self.window_icon_photo: tk.PhotoImage | None = None
        self.native_icon_handles: list[int] = []

        self.title(str(self.ui.get("app_name", "SQL Record Manager")))
        self._configure_window_icon()
        window_size = str(self.ui.get("window_size", "1180x780"))
        self._initial_width, self._initial_height = self._parse_window_size(window_size)
        self.geometry(window_size)
        self.minsize(
            int(self.ui.get("min_width", 760)), int(self.ui.get("min_height", 600))
        )
        self.configure(background=self.colors["background"])
        self._configure_style()
        self._build_shell()
        self.bind("<Configure>", self._responsive_shell)
        self.after_idle(self._finish_initial_layout)
        self.after_idle(self._configure_windows_taskbar_icon)

    def _configured_asset_path(self, setting: str) -> Path | None:
        configured = str(self.ui.get(setting, "")).strip()
        if not configured:
            return None
        path = Path(configured)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        return path if path.exists() else None

    def _configure_window_icon(self) -> None:
        path = self._configured_asset_path("window_icon_path")
        if path is None:
            return
        try:
            self.window_icon_photo = tk.PhotoImage(file=str(path))
            self.iconphoto(True, self.window_icon_photo)
        except tk.TclError:
            self.window_icon_photo = None

    def _configure_windows_taskbar_icon(self) -> None:
        """Asigna iconos pequeño/grande distintos mediante Win32 cuando es posible."""
        import os

        if os.name != "nt":
            return
        small_path = self._configured_asset_path("window_icon_ico")
        large_path = self._configured_asset_path("taskbar_icon_ico")
        if small_path is None or large_path is None:
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            load_from_file = 0x0010
            image_icon = 1
            small_icon = user32.LoadImageW(
                None, str(small_path), image_icon, 16, 16, load_from_file
            )
            large_icon = user32.LoadImageW(
                None, str(large_path), image_icon, 32, 32, load_from_file
            )
            if not small_icon or not large_icon:
                return
            client_handle = int(self.winfo_id())
            window_handle = int(user32.GetParent(client_handle)) or client_handle
            wm_seticon = 0x0080
            user32.SendMessageW(window_handle, wm_seticon, 0, small_icon)
            user32.SendMessageW(window_handle, wm_seticon, 1, large_icon)
            self.native_icon_handles.extend((int(small_icon), int(large_icon)))
        except (AttributeError, OSError, TypeError, ValueError):
            # iconphoto ya evita que reaparezca el icono predeterminado de Tk.
            return

    @staticmethod
    def _parse_window_size(value: str) -> tuple[int, int]:
        try:
            size = value.split("+", 1)[0].lower()
            width_text, height_text = size.split("x", 1)
            return max(int(width_text), 1), max(int(height_text), 1)
        except (TypeError, ValueError):
            return 1180, 780

    def _finish_initial_layout(self) -> None:
        current_width = self.winfo_width()
        current_height = self.winfo_height()
        width = current_width if current_width > 1 else self._initial_width
        height = current_height if current_height > 1 else self._initial_height
        self._pending_window_width = width
        self._pending_window_height = height
        self._pending_auto_collapse = width < self.breakpoint
        if self._pending_auto_collapse:
            self._automatic_collapse = True
            self._set_sidebar_collapsed(True, update_geometry=False)
        self._apply_shell_geometry(width, height)
        self.show_page("connection")

    def _configure_style(self) -> None:
        c = self.colors
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=(self.font_family, 10))
        style.configure("Page.TFrame", background=c["background"])
        style.configure("Card.TFrame", background=c["surface"])
        style.configure("StatusBar.TFrame", background=c["surface_alt"])
        style.configure("TSeparator", background=c["border"])

        style.configure(
            "PageTitle.TLabel",
            background=c["background"],
            foreground=c["text"],
            font=(self.font_family, 22, "bold"),
        )
        style.configure(
            "PageSubtitle.TLabel", background=c["background"], foreground=c["muted"]
        )
        style.configure(
            "Eyebrow.TLabel",
            background=c["background"],
            foreground=c["primary"],
            font=(self.font_family, 8, "bold"),
        )
        style.configure(
            "CardTitle.TLabel",
            background=c["surface"],
            foreground=c["text"],
            font=(self.font_family, 12, "bold"),
        )
        style.configure(
            "CardSubtitle.TLabel", background=c["surface"], foreground=c["muted"]
        )
        style.configure(
            "FieldLabel.TLabel",
            background=c["surface"],
            foreground=c["text"],
            font=(self.font_family, 9, "bold"),
        )
        style.configure("Hint.TLabel", background=c["surface"], foreground=c["muted"])
        style.configure(
            "Badge.TLabel",
            background=c["selection"],
            foreground=c["primary"],
            padding=(9, 3),
            font=(self.font_family, 9, "bold"),
        )
        style.configure("StatusText.TLabel", background=c["surface_alt"], foreground=c["muted"])
        style.configure("StatusDot.TLabel", background=c["surface_alt"], foreground=c["primary"])
        style.configure("SuccessDot.TLabel", background=c["surface_alt"], foreground=c["success"])
        style.configure("DangerDot.TLabel", background=c["surface_alt"], foreground=c["danger"])

        style.configure(
            "Modern.TEntry",
            fieldbackground=c["surface"],
            foreground=c["text"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=(10, 8),
        )
        style.map("Modern.TEntry", bordercolor=[("focus", c["primary"])])
        style.configure(
            "Modern.TCombobox",
            fieldbackground=c["surface"],
            background=c["surface"],
            foreground=c["text"],
            arrowcolor=c["muted"],
            bordercolor=c["border"],
            padding=(9, 7),
        )
        style.map(
            "Modern.TCombobox",
            bordercolor=[("focus", c["primary"])],
            fieldbackground=[("readonly", c["surface"])],
            foreground=[("readonly", c["text"])],
        )
        style.configure(
            "Modern.TSpinbox",
            fieldbackground=c["surface"],
            background=c["surface_alt"],
            foreground=c["text"],
            arrowcolor=c["muted"],
            bordercolor=c["border"],
            padding=(7, 5),
        )
        style.map("Modern.TSpinbox", bordercolor=[("focus", c["primary"])])
        style.configure(
            "Modern.TCheckbutton", background=c["surface"], foreground=c["text"]
        )

        for name, background, foreground in (
            ("Primary.TButton", c["primary"], "#FFFFFF"),
            ("Secondary.TButton", c["surface_alt"], c["text"]),
            ("Ghost.TButton", c["surface"], c["muted"]),
        ):
            style.configure(
                name,
                background=background,
                foreground=foreground,
                bordercolor=c["border"] if name != "Primary.TButton" else c["primary"],
                padding=(14, 8),
                font=(self.font_family, 9, "bold"),
            )
        style.map(
            "Primary.TButton",
            background=[("active", c["primary_hover"]), ("disabled", c["surface_alt"])],
        )
        style.map("Secondary.TButton", background=[("active", c["selection"])])
        style.map("Ghost.TButton", background=[("active", c["surface_alt"])])

        style.configure(
            "Modern.Treeview",
            background=c["surface"],
            fieldbackground=c["surface"],
            foreground=c["text"],
            rowheight=30,
            borderwidth=0,
        )
        style.configure(
            "Modern.Treeview.Heading",
            background=c["surface_alt"],
            foreground=c["text"],
            relief="flat",
            padding=(8, 8),
            font=(self.font_family, 9, "bold"),
        )
        style.map(
            "Modern.Treeview",
            background=[("selected", c["selection"])],
            foreground=[("selected", c["text"])],
        )

    def _build_shell(self) -> None:
        c = self.colors
        self.topbar = tk.Frame(self, background=c["topbar"], height=58)
        self.topbar.place(x=0, y=0, width=self._initial_width, height=58)
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(1, weight=1)
        self.menu_button = tk.Button(
            self.topbar,
            text="☰",
            command=self.toggle_sidebar,
            background=c["topbar"],
            foreground=c["text"],
            activebackground=c["topbar_dark"],
            activeforeground=c["text"],
            relief="flat",
            borderwidth=0,
            font=(self.font_family, 16),
            cursor="hand2",
            width=3,
        )
        self.menu_button.grid(row=0, column=0, sticky="ns", padx=(8, 4))
        brand = str(self.ui.get("app_name", "SQL Record Manager"))
        tk.Label(
            self.topbar,
            text=brand,
            background=c["topbar"],
            foreground=c["text"],
            font=(self.font_family, 13, "bold"),
        ).grid(row=0, column=1, sticky="w")
        self.active_table = tk.StringVar(value="Sin conexión")
        tk.Label(
            self.topbar,
            textvariable=self.active_table,
            background=c["topbar_dark"],
            foreground=c["text"],
            font=(self.font_family, 9),
            padx=12,
            pady=6,
        ).grid(row=0, column=2, padx=(14, 8))
        self.brand_logo = self._load_brand_logo()
        if self.brand_logo is not None:
            tk.Label(
                self.topbar,
                image=self.brand_logo,
                background=c["topbar"],
                borderwidth=0,
            ).grid(row=0, column=3, padx=(4, 14))

        self.sidebar = tk.Frame(
            self, background=c["sidebar"], width=self.sidebar_width
        )
        self.sidebar.place(
            x=0,
            y=58,
            width=self.sidebar_width,
            height=max(self._initial_height - 58, 1),
        )
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(9, weight=1)

        self.sidebar_title = tk.Label(
            self.sidebar,
            text="GESTIÓN DE DATOS",
            background=c["sidebar"],
            foreground=c["muted"],
            font=(self.font_family, 8, "bold"),
            anchor="w",
        )
        self.sidebar_title.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 10))
        self._add_nav_button("connection", "⚙", "Conexión", 1)

        separator = tk.Frame(self.sidebar, background=c["border"], height=1)
        separator.grid(row=7, column=0, sticky="ew", padx=14, pady=16)
        self.sidebar_hint = tk.Label(
            self.sidebar,
            text=self.sidebar_hint_text,
            justify="left",
            anchor="w",
            background=c["sidebar"],
            foreground=c["muted"],
            font=(self.font_family, 8),
        )
        self.sidebar_hint.grid(row=8, column=0, sticky="ew", padx=18)

        self.content = ttk.Frame(self, style="Page.TFrame")
        self.content.place(
            x=self.sidebar_width,
            y=58,
            width=max(self._initial_width - self.sidebar_width, 1),
            height=max(self._initial_height - 58, 1),
        )
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.pages["connection"] = ConnectionPage(self.content, self)
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_remove()

    def _load_brand_logo(self) -> Any | None:
        configured = str(self.ui.get("logo_path", "")).strip()
        if not configured:
            return None
        path = Path(configured)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        if not path.exists():
            return None
        try:
            if Image is None or ImageTk is None:
                fallback = tk.PhotoImage(file=str(path))
                return fallback.subsample(3, 3)
            source = Image.open(path).convert("RGBA")
            original_alpha = source.getchannel("A")
            source = Image.new("RGBA", source.size, (255, 255, 255, 0))
            source.putalpha(original_alpha)
            opacity = min(max(float(self.ui.get("logo_opacity", 0.60)), 0.0), 1.0)
            alpha = source.getchannel("A").point(lambda value: round(value * opacity))
            source.putalpha(alpha)
            width = max(int(self.ui.get("logo_width", 142)), 1)
            height = max(round(source.height * width / source.width), 1)
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            source = source.resize((width, height), resampling)
            return ImageTk.PhotoImage(source)
        except (OSError, TypeError, ValueError):
            return None

    def activate_connection(
        self,
        db_config: Mapping[str, Any],
        form_config: Mapping[str, Any],
        update_config: Mapping[str, Any],
    ) -> None:
        """Cambia la conexión activa y regenera las páginas dependientes de la tabla."""
        for key in ("insert", "update", "bulk", "logs"):
            page = self.pages.pop(key, None)
            if page is not None:
                page.destroy()
            button = self.nav_buttons.pop(key, None)
            if button is not None:
                button.destroy()

        self.repository = SQLServerRepository(
            db_config,
            form_config,
            update_config,
            operation_logger=self.operation_logger,
        )
        self.form_config = dict(form_config)
        self.connection_profile = dict(db_config)
        self.sidebar_hint_text = (
            "SQL SERVER\nConectado"
            if self.repository.update_enabled
            else "SQL SERVER\nConectado · sin clave para UPDATE"
        )
        self.sidebar_hint.configure(
            text="" if self.sidebar_collapsed else self.sidebar_hint_text
        )
        self.active_table.set(f"{self.repository.schema}.{self.repository.table}")
        self.title(str(form_config.get("window_title", "Gestión SQL Server")))

        self._add_nav_button("insert", "＋", "Insertar registro", 2)
        if self.repository.update_enabled:
            self._add_nav_button("update", "⌕", "Buscar / actualizar", 3)
        if self.bulk_enabled:
            self._add_nav_button("bulk", "⇧", "Insertar desde Excel", 4)
        if self.log_enabled:
            self._add_nav_button("logs", "≡", "SQL / Logs", 5)

        self.pages["insert"] = InsertPage(self.content, self)
        if self.repository.update_enabled:
            self.pages["update"] = UpdatePage(self.content, self)
        if self.bulk_enabled:
            self.pages["bulk"] = BulkInsertPage(self.content, self)
        if self.log_enabled:
            self.pages["logs"] = LogPage(self.content, self)
        for key, page in self.pages.items():
            if key == "connection":
                continue
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_remove()
        self.show_page("insert")

    def _add_nav_button(
        self, key: str, icon: str, label: str, row: int
    ) -> None:
        c = self.colors
        button = tk.Button(
            self.sidebar,
            text=f"  {icon}    {label}",
            command=lambda page=key: self.show_page(page),
            anchor="w",
            background=c["sidebar"],
            foreground="#D4D4D8",
            activebackground=c["sidebar_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            borderwidth=0,
            font=(self.font_family, 10),
            cursor="hand2",
            padx=10,
            pady=11,
        )
        button.grid(row=row, column=0, sticky="ew", padx=8, pady=2)
        button.full_text = f"  {icon}    {label}"  # type: ignore[attr-defined]
        button.compact_text = icon  # type: ignore[attr-defined]
        if self.sidebar_collapsed:
            button.configure(text=icon, anchor="center")
        self.nav_buttons[key] = button

    def show_page(self, name: str) -> None:
        if name not in self.pages:
            return
        self.current_page = name
        for key, page in self.pages.items():
            if key == name:
                page.grid()
                page.tkraise()
            else:
                page.grid_remove()
        for key, button in self.nav_buttons.items():
            button.configure(
                background=self.colors["sidebar_active"]
                if key == name
                else self.colors["sidebar"],
                foreground="#FFFFFF" if key == name else "#D4D4D8",
            )
        page = self.pages[name]
        on_show = getattr(page, "on_show", None)
        if callable(on_show):
            on_show()

    def toggle_sidebar(self) -> None:
        self._automatic_collapse = False
        self._set_sidebar_collapsed(not self.sidebar_collapsed)

    def _set_sidebar_collapsed(
        self, collapsed: bool, update_geometry: bool = True
    ) -> None:
        if self.sidebar_collapsed == collapsed:
            return
        self.sidebar_collapsed = collapsed
        self.sidebar_title.configure(text="" if collapsed else "GESTIÓN DE DATOS")
        self.sidebar_hint.configure(text="" if collapsed else self.sidebar_hint_text)
        for button in self.nav_buttons.values():
            text = (
                button.compact_text if collapsed else button.full_text  # type: ignore[attr-defined]
            )
            button.configure(text=text, anchor="center" if collapsed else "w")
        if update_geometry:
            self._apply_shell_geometry(self.winfo_width(), self.winfo_height())

    def _apply_shell_geometry(self, width: int, height: int) -> None:
        """Aplica la geometría completa una sola vez después del arrastre."""
        width = max(int(width), 1)
        height = max(int(height), 59)
        sidebar_width = (
            self.sidebar_collapsed_width
            if self.sidebar_collapsed
            else self.sidebar_width
        )
        body_height = max(height - 58, 1)
        content_width = max(width - sidebar_width, 1)
        self.topbar.place_configure(x=0, y=0, width=width, height=58)
        self.sidebar.place_configure(
            x=0, y=58, width=sidebar_width, height=body_height
        )
        self.content.place_configure(
            x=sidebar_width,
            y=58,
            width=content_width,
            height=body_height,
        )
        self._applied_window_width = width
        self._applied_window_height = height

    def _responsive_shell(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        should_collapse = event.width < self.breakpoint
        dimensions_changed = (
            abs(event.width - self._applied_window_width)
            >= self._window_width_tolerance
            or abs(event.height - self._applied_window_height)
            >= self._window_width_tolerance
        )
        collapse_changed = should_collapse != self._automatic_collapse
        if not dimensions_changed and not collapse_changed:
            return

        self._pending_window_width = event.width
        self._pending_window_height = event.height
        self._pending_auto_collapse = should_collapse
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(
            self._resize_delay,
            self._apply_responsive_shell,
        )

    def _apply_responsive_shell(self) -> None:
        self._resize_job = None
        should_collapse = self._pending_auto_collapse
        if should_collapse != self._automatic_collapse:
            self._automatic_collapse = should_collapse
            self._set_sidebar_collapsed(should_collapse, update_geometry=False)
        self._apply_shell_geometry(
            self._pending_window_width,
            self._pending_window_height,
        )

    def run_background(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[str, str], None],
    ) -> None:
        def worker() -> None:
            try:
                result = operation()
            except (ValidationError, ConfigurationError) as exc:
                message = str(exc)
                self.after(0, lambda: on_error("Validación", message))
            except Exception as exc:
                message = str(exc)
                self.after(
                    0,
                    lambda: on_error(
                        "SQL Server", "No se pudo completar la operación.\n\n" + message
                    ),
                )
            else:
                self.after(0, lambda: on_success(result))

        threading.Thread(target=worker, daemon=True).start()
