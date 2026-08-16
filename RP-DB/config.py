"""Configuración editable de la aplicación.

Contiene valores iniciales, límites y personalizaciones. Las credenciales se
capturan desde la página Conexión; no coloques contraseñas directamente aquí.
"""

from __future__ import annotations

import os


DB_CONFIG = {
    # Motores disponibles: "sqlserver" o "postgresql".
    "provider": os.getenv("DATABASE_PROVIDER", "sqlserver"),
    # Ejemplo de servidor local: r"localhost\SQLEXPRESS"
    "server": os.getenv("DATABASE_HOST", os.getenv("SQLSERVER_HOST", r"localhost\SQLEXPRESS")),
    "database": os.getenv("DATABASE_NAME", os.getenv("SQLSERVER_DATABASE", "MiBaseDeDatos")),
    "port": int(os.getenv("DATABASE_PORT", "5432")),
    "sslmode": os.getenv("POSTGRES_SSLMODE", "prefer"),
    "driver": os.getenv("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server"),
    # Si el driver principal no está instalado, se prueba esta lista en orden.
    "driver_candidates": [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13.1 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "ODBC Driver 11 for SQL Server",
        "SQL Server Native Client 11.0",
    ],
    # True: autenticación de Windows. False: usuario/clave de SQL Server.
    "trusted_connection": os.getenv("SQLSERVER_TRUSTED", "true").lower()
    in {"1", "true", "yes", "si", "sí"},
    "username": os.getenv("DATABASE_USER", os.getenv("SQLSERVER_USER", "")),
    "password": os.getenv("DATABASE_PASSWORD", os.getenv("SQLSERVER_PASSWORD", "")),
    # Para certificados internos/locales. En producción configura el certificado
    # correctamente y cambia esta opción a False.
    "trust_server_certificate": os.getenv(
        "SQLSERVER_TRUST_CERTIFICATE", "true"
    ).lower()
    in {"1", "true", "yes", "si", "sí"},
    "connection_timeout": 8,
}


FORM_CONFIG = {
    "window_title": "Inserción manual en SQL Server",
    "schema": "dbo",
    "table": "Clientes",
    # Opcional. Si la tabla tiene un IDENTITY y quieres mostrar el ID generado,
    # escribe el nombre de la columna; si no, usa None.
    "identity_column": "ClienteID",
    "fields": [
        {
            "name": "Nombre",
            "label": "Nombre completo",
            "type": "str",
            "required": True,
            "max_length": 150,
            "placeholder": "Ej.: Ana Torres",
        },
        {
            "name": "Documento",
            "label": "Documento",
            "type": "str",
            "required": True,
            "max_length": 20,
        },
        {
            "name": "Edad",
            "label": "Edad",
            "type": "int",
            "required": False,
        },
        {
            "name": "Correo",
            "label": "Correo",
            "type": "str",
            "required": False,
            "max_length": 180,
        },
        {
            "name": "FechaRegistro",
            "label": "Fecha de registro",
            "type": "date",
            "required": True,
            "default": "today",
            "placeholder": "AAAA-MM-DD",
        },
        {
            "name": "Activo",
            "label": "Activo",
            "type": "bool",
            "required": True,
            "default": True,
            "widget": "checkbox",
        },
        {
            "name": "TipoCliente",
            "label": "Tipo de cliente",
            "type": "str",
            "required": True,
            "widget": "combobox",
            "options": ["Persona", "Empresa"],
        },
        {
            "name": "Observacion",
            "label": "Observación",
            "type": "str",
            "required": False,
            "max_length": 500,
            "widget": "multiline",
        },
    ],
}


# Tablas visibles y personalizaciones para la página Conexión.
TABLE_SELECTOR_CONFIG = {
    # Usa "*" para mostrar todas las tablas visibles, o limita por seguridad.
    "allowed_schemas": "*",
    "allowed_tables": "*",  # Ejemplo: ["dbo.Clientes", "dbo.Campania_Example"]
    "excluded_schemas": ["sys", "INFORMATION_SCHEMA"],
    "excluded_tables": [],
    # False permite que SQL Server complete las columnas con DEFAULT.
    "include_default_columns": False,
    # Para una tabla sin PK/UNIQUE, configura una combinación realmente única.
    "key_fields_by_table": {
        # "dbo.Campania_Example": ["campania", "publisher", "num_campania"],
    },
    # Personalizaciones opcionales sin perder la detección automática.
    "field_overrides": {
        # "dbo.Clientes": {
        #     "TipoCliente": {
        #         "widget": "combobox",
        #         "options": ["Persona", "Empresa"],
        #     },
        # },
    },
}


# Configuración de la pestaña Buscar / actualizar.
UPDATE_CONFIG = {
    "enabled": True,
    # Si no existe PK/UNIQUE, permite identificar grupos por todos sus valores
    # originales y elegir cuántas filas idénticas actualizar.
    "allow_non_unique_updates": True,
    # Límite de seguridad para una sola confirmación desde la interfaz.
    "max_rows_per_update": 100000,
    "max_rows_per_delete": 100000,
    # Columna(s) que identifican UN registro. Lo ideal es usar la PRIMARY KEY.
    # Puede ser una clave compuesta: ["EmpresaID", "CodigoProducto"].
    "key_fields": ["ClienteID"],
    # "*" carga todas las columnas reales de la tabla en el selector de búsqueda.
    # También puedes limitarlo: ["Nombre", "Documento", "Correo"].
    "searchable_fields": "*",
    # Columnas mostradas en la tabla de resultados. "*" muestra todas.
    "result_fields": "*",
    # Campos que se pueden modificar. "*" usa todos los campos de FORM_CONFIG.
    # La columna IDENTITY no está en FORM_CONFIG, por lo que no será editable.
    "editable_fields": "*",
    "default_search_mode": "contains",  # "contains" o "exact"
    "max_results": 200,
}


# Configuración de la pestaña Insertar desde Excel.
BULK_INSERT_CONFIG = {
    "enabled": True,
    # Formatos modernos de Excel compatibles con openpyxl.
    "allowed_extensions": [".xlsx", ".xlsm"],
    # None usa la hoja activa. También puedes indicar: "Hoja1".
    "sheet_name": None,
    "header_row": 1,
    # True exige que el Excel contenga todos los campos de FORM_CONFIG.
    # False exige solamente los campos marcados como required.
    "require_all_headers": True,
    # Las columnas adicionales del Excel se ignoran cuando es True.
    "ignore_extra_columns": True,
    # Opcional: permite nombres distintos en Excel.
    # Ejemplo: {"Campaña Excel": "campania", "Medio": "publisher"}
    "column_mapping": {},
    "preview_rows": 20,
    "max_rows": 100000,
    "batch_size": 500,
}


# Log visible en la aplicación y almacenado localmente.
LOG_CONFIG = {
    "enabled": True,
    "file_path": "logs/operations.log",
    "max_bytes": 2_000_000,
}


# Apariencia general. Puedes cambiar estos valores sin tocar gui.py.
UI_CONFIG = {
    "app_name": "SQL Record Manager",
    # Sin logotipo corporativo en la barra superior.
    "logo_path": "",
    "logo_opacity": 0.60,
    "logo_width": 142,
    # Icono pequeño de la ventana y logo grande de Windows/barra de tareas.
    "window_icon_path": "assets/app_window_icon.png",
    "window_icon_ico": "assets/app_window_icon.ico",
    "taskbar_icon_ico": "assets/app_window_icon.ico",
    "windows_app_id": "SQLRecordManager",
    "window_size": "1180x780",
    "min_width": 760,
    "min_height": 600,
    "sidebar_width": 224,
    "sidebar_collapsed_width": 68,
    "responsive_breakpoint": 900,
    # Rendimiento durante el redimensionamiento (milisegundos).
    "resize_debounce_ms": 110,
    "form_resize_debounce_ms": 90,
    "form_responsive_breakpoint": 600,
    "resize_width_tolerance": 8,
    "font_family": "Segoe UI",
    "colors": {
        "background": "#111827",
        "surface": "#1F2937",
        "surface_alt": "#273449",
        "topbar": "#0F172A",
        "topbar_dark": "#172033",
        "sidebar": "#0B1220",
        "sidebar_hover": "#1A2638",
        "sidebar_active": "#24344A",
        "primary": "#7C9CCB",
        "primary_hover": "#92AFD6",
        "text": "#E5E7EB",
        "muted": "#9CA9BA",
        "border": "#334155",
        "success": "#86C7A3",
        "danger": "#D98A97",
        "selection": "#31435A",
    },
}
