"""Catálogo de tablas y generación automática de la configuración del formulario."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from database import (
    ConfigurationError,
    build_connection_string,
    quote_identifier,
    resolve_sql_server_driver,
)

try:
    import pyodbc
except ModuleNotFoundError:
    pyodbc = None  # type: ignore[assignment]


@dataclass(frozen=True)
class TableReference:
    schema: str
    table: str

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.table}"


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    sql_type: str
    max_length: int | None
    precision: int | None
    scale: int | None
    nullable: bool
    identity: bool
    computed: bool
    has_default: bool


STRING_TYPES = {
    "char",
    "nchar",
    "varchar",
    "nvarchar",
    "text",
    "ntext",
    "uniqueidentifier",
    "xml",
}
INTEGER_TYPES = {"tinyint", "smallint", "int", "bigint"}
FLOAT_TYPES = {"real", "float"}
DECIMAL_TYPES = {"decimal", "numeric", "money", "smallmoney"}
DATETIME_TYPES = {"datetime", "datetime2", "smalldatetime", "datetimeoffset"}
AUTOMATIC_TYPES = {"timestamp", "rowversion"}
UNSUPPORTED_KEY_TYPES = {
    "text",
    "ntext",
    "image",
    "xml",
    "timestamp",
    "rowversion",
    "geography",
    "geometry",
    "hierarchyid",
}
NON_EQUALITY_TYPES = {
    "text",
    "ntext",
    "image",
    "xml",
    "geography",
    "geometry",
    "hierarchyid",
}


def sql_display_type(column: ColumnMetadata) -> str:
    """Devuelve el tipo SQL como debe mostrarse en la interfaz."""
    sql_type = column.sql_type.casefold()
    name = column.sql_type.upper()
    if sql_type in {"char", "varchar", "binary", "varbinary"}:
        length = "MAX" if column.max_length == -1 else column.max_length
        return f"{name}({length})" if length is not None else name
    if sql_type in {"nchar", "nvarchar"}:
        length: int | str | None
        if column.max_length == -1:
            length = "MAX"
        elif column.max_length is None:
            length = None
        else:
            length = int(column.max_length) // 2
        return f"{name}({length})" if length is not None else name
    if sql_type in {"decimal", "numeric"}:
        if column.precision is not None and column.scale is not None:
            return f"{name}({column.precision},{column.scale})"
    if sql_type in {"datetime2", "datetimeoffset", "time"} and column.scale is not None:
        return f"{name}({column.scale})"
    if sql_type == "float" and column.precision is not None:
        return f"{name}({column.precision})"
    return name


def sql_column_to_field(column: ColumnMetadata) -> dict[str, Any] | None:
    """Traduce una columna escribible de SQL Server a un campo de la GUI."""
    sql_type = column.sql_type.lower()
    if column.identity or column.computed or sql_type in AUTOMATIC_TYPES:
        return None

    field: dict[str, Any] = {
        "name": column.name,
        "label": column.name.replace("_", " ").strip().capitalize(),
        "required": not column.nullable,
        "sql_type_display": sql_display_type(column),
        "sql_nullable": column.nullable,
    }
    if sql_type in STRING_TYPES:
        field["type"] = "str"
        if sql_type == "uniqueidentifier":
            field["max_length"] = 36
        elif column.max_length not in (None, -1) and sql_type not in {"text", "ntext", "xml"}:
            length = int(column.max_length)
            if sql_type in {"nchar", "nvarchar"}:
                length //= 2
            field["max_length"] = length
        if sql_type in {"text", "ntext", "xml"} or (column.max_length or 0) > 500:
            field["widget"] = "multiline"
    elif sql_type in INTEGER_TYPES:
        field["type"] = "int"
    elif sql_type in FLOAT_TYPES:
        field["type"] = "float"
    elif sql_type in DECIMAL_TYPES:
        field["type"] = "decimal"
    elif sql_type == "bit":
        field.update({"type": "bool", "widget": "checkbox", "default": False})
    elif sql_type == "date":
        field.update({"type": "date", "placeholder": "AAAA-MM-DD"})
    elif sql_type in DATETIME_TYPES:
        field.update(
            {"type": "datetime", "placeholder": "AAAA-MM-DD HH:MM:SS"}
        )
    elif sql_type == "time":
        field.update({"type": "time", "placeholder": "HH:MM:SS"})
    else:
        return None
    return field


def build_dynamic_configs(
    table: TableReference,
    columns: Sequence[ColumnMetadata],
    discovered_keys: Sequence[str],
    base_form: Mapping[str, Any],
    base_update: Mapping[str, Any],
    selector_config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Crea FORM_CONFIG y UPDATE_CONFIG para una tabla elegida."""
    include_defaults = bool(selector_config.get("include_default_columns", False))
    overrides_by_table = selector_config.get("field_overrides", {})
    if not isinstance(overrides_by_table, Mapping):
        raise ConfigurationError("field_overrides debe ser un diccionario.")
    table_overrides = overrides_by_table.get(table.qualified_name, {})
    if not isinstance(table_overrides, Mapping):
        raise ConfigurationError(
            f"field_overrides[{table.qualified_name!r}] debe ser un diccionario."
        )

    fields: list[dict[str, Any]] = []
    unsupported_required: list[str] = []
    for column in columns:
        if column.has_default and not include_defaults:
            continue
        field = sql_column_to_field(column)
        if field is None:
            is_automatic = (
                column.identity
                or column.computed
                or column.sql_type.lower() in AUTOMATIC_TYPES
                or column.has_default
            )
            if not column.nullable and not is_automatic:
                unsupported_required.append(
                    f"{column.name} ({column.sql_type})"
                )
            continue
        override = table_overrides.get(column.name, {})
        if override:
            if not isinstance(override, Mapping):
                raise ConfigurationError(
                    f"La personalización de {column.name!r} debe ser un diccionario."
                )
            field.update(dict(override))
        fields.append(field)

    if unsupported_required:
        raise ConfigurationError(
            "La tabla contiene columnas obligatorias con tipos no compatibles: "
            + ", ".join(unsupported_required)
        )
    if not fields:
        raise ConfigurationError("La tabla no tiene columnas disponibles para insertar.")

    identity = next((column.name for column in columns if column.identity), None)
    form_config = dict(base_form)
    form_config.update(
        {
            "window_title": f"Gestión SQL Server - {table.qualified_name}",
            "schema": table.schema,
            "table": table.table,
            "identity_column": identity,
            "fields": fields,
        }
    )

    configured_keys = selector_config.get("key_fields_by_table", {})
    if not isinstance(configured_keys, Mapping):
        raise ConfigurationError("key_fields_by_table debe ser un diccionario.")
    configured_for_table = table.qualified_name in configured_keys
    keys = list(configured_keys.get(table.qualified_name, discovered_keys))
    actual_names = {column.name.lower(): column.name for column in columns}
    invalid_keys = [str(key) for key in keys if str(key).lower() not in actual_names]
    if invalid_keys:
        raise ConfigurationError(
            "Las columnas configuradas como clave no existen: " + ", ".join(invalid_keys)
        )
    keys = [actual_names[str(key).lower()] for key in keys]

    match_fields = [
        column.name
        for column in columns
        if column.sql_type.casefold() not in NON_EQUALITY_TYPES
    ]

    update_config = dict(base_update)
    update_config["key_fields"] = keys
    update_config["match_fields"] = match_fields
    update_config["column_types"] = {
        column.name: sql_display_type(column) for column in columns
    }
    update_config["non_unique_mode"] = not bool(keys)
    update_config["key_requires_validation"] = bool(
        keys
        and configured_for_table
        and [name.casefold() for name in keys]
        != [str(name).casefold() for name in discovered_keys]
    )
    allow_non_unique = bool(base_update.get("allow_non_unique_updates", False))
    update_config["enabled"] = bool(
        base_update.get("enabled", True)
        and (keys or (allow_non_unique and match_fields))
    )
    return form_config, update_config


class SQLServerCatalog:
    """Consulta tablas, columnas y claves visibles para el usuario conectado."""

    def __init__(
        self,
        db_config: Mapping[str, Any],
        selector_config: Mapping[str, Any],
    ) -> None:
        self.db_config = dict(db_config)
        self.selector_config = dict(selector_config)

    def _connect(self) -> Any:
        if pyodbc is None:
            raise ConfigurationError(
                "Falta pyodbc. Ejecuta: python -m pip install -r requirements.txt"
            )
        connection_config = dict(self.db_config)
        connection_config["driver"] = resolve_sql_server_driver(connection_config)
        return pyodbc.connect(build_connection_string(connection_config))

    @staticmethod
    def _allowed(value: str, configured: Any) -> bool:
        if configured == "*":
            return True
        if not isinstance(configured, (list, tuple, set)):
            raise ConfigurationError("Los filtros del catálogo deben ser '*' o una lista.")
        return value.casefold() in {str(item).casefold() for item in configured}

    def list_tables(self) -> list[TableReference]:
        sql = """
            SELECT s.name, t.name
            FROM sys.tables AS t
            INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
            WHERE t.is_ms_shipped = 0
            ORDER BY s.name, t.name;
        """
        with self._connect() as connection:
            rows = connection.cursor().execute(sql).fetchall()

        allowed_schemas = self.selector_config.get("allowed_schemas", "*")
        allowed_tables = self.selector_config.get("allowed_tables", "*")
        excluded_schemas = {
            str(value).casefold()
            for value in self.selector_config.get(
                "excluded_schemas", ["sys", "INFORMATION_SCHEMA"]
            )
        }
        excluded_tables = {
            str(value).casefold()
            for value in self.selector_config.get("excluded_tables", [])
        }
        result: list[TableReference] = []
        for schema, table in rows:
            reference = TableReference(str(schema), str(table))
            if reference.schema.casefold() in excluded_schemas:
                continue
            if reference.qualified_name.casefold() in excluded_tables:
                continue
            if not self._allowed(reference.schema, allowed_schemas):
                continue
            table_allowed = self._allowed(reference.qualified_name, allowed_tables)
            table_allowed = table_allowed or self._allowed(reference.table, allowed_tables)
            if table_allowed:
                result.append(reference)
        return result

    def get_columns(self, table: TableReference) -> list[ColumnMetadata]:
        sql = """
            SELECT
                c.name,
                TYPE_NAME(c.system_type_id),
                c.max_length,
                c.precision,
                c.scale,
                c.is_nullable,
                c.is_identity,
                c.is_computed,
                CASE WHEN c.default_object_id = 0 THEN 0 ELSE 1 END
            FROM sys.columns AS c
            INNER JOIN sys.tables AS t ON t.object_id = c.object_id
            INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
            WHERE s.name = ? AND t.name = ?
            ORDER BY c.column_id;
        """
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, table.schema, table.table)
            rows = cursor.fetchall()
        if not rows:
            raise ConfigurationError(
                f"No se encontró la tabla [{table.schema}].[{table.table}]."
            )
        return [
            ColumnMetadata(
                name=str(row[0]),
                sql_type=str(row[1]),
                max_length=int(row[2]) if row[2] is not None else None,
                precision=int(row[3]) if row[3] is not None else None,
                scale=int(row[4]) if row[4] is not None else None,
                nullable=bool(row[5]),
                identity=bool(row[6]),
                computed=bool(row[7]),
                has_default=bool(row[8]),
            )
            for row in rows
        ]

    def get_key_fields(self, table: TableReference) -> list[str]:
        """Devuelve la PK o, si no existe, el primer índice UNIQUE utilizable."""
        sql = """
            SELECT i.index_id, i.is_primary_key, ic.key_ordinal, c.name
            FROM sys.indexes AS i
            INNER JOIN sys.tables AS t ON t.object_id = i.object_id
            INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
            INNER JOIN sys.index_columns AS ic
                ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            INNER JOIN sys.columns AS c
                ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE s.name = ? AND t.name = ?
              AND i.is_unique = 1 AND i.is_disabled = 0
              AND i.has_filter = 0 AND ic.is_included_column = 0
            ORDER BY i.is_primary_key DESC, i.index_id, ic.key_ordinal;
        """
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, table.schema, table.table)
            rows = cursor.fetchall()
        if not rows:
            return []
        chosen_index = int(rows[0][0])
        return [str(row[3]) for row in rows if int(row[0]) == chosen_index]

    def validate_unique_key(
        self,
        table: TableReference,
        key_fields: Sequence[str],
        columns: Sequence[ColumnMetadata] | None = None,
    ) -> bool:
        """Comprueba que una combinación de columnas identifica como máximo una fila."""
        if not key_fields:
            raise ConfigurationError("Selecciona al menos una columna para el UPDATE.")

        metadata = list(columns) if columns is not None else self.get_columns(table)
        actual_names = {column.name.casefold(): column.name for column in metadata}
        key_types = {column.name.casefold(): column.sql_type.casefold() for column in metadata}
        normalized: list[str] = []
        for key in key_fields:
            actual = actual_names.get(str(key).casefold())
            if actual is None:
                raise ConfigurationError(
                    f"La columna seleccionada {key!r} no existe en la tabla."
                )
            if key_types[actual.casefold()] in UNSUPPORTED_KEY_TYPES:
                raise ConfigurationError(
                    f"La columna {actual!r} tiene un tipo que no puede usarse como clave."
                )
            if actual not in normalized:
                normalized.append(actual)

        qualified_table = (
            f"{quote_identifier(table.schema)}.{quote_identifier(table.table)}"
        )
        grouped_columns = ", ".join(quote_identifier(name) for name in normalized)
        sql = (
            "SELECT TOP (1) 1 "
            f"FROM {qualified_table} "
            f"GROUP BY {grouped_columns} "
            "HAVING COUNT_BIG(*) > 1;"
        )
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql)
            duplicate = cursor.fetchone()
        return duplicate is None

    def build_configs(
        self,
        table: TableReference,
        base_form: Mapping[str, Any],
        base_update: Mapping[str, Any],
        override_keys: Sequence[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[ColumnMetadata]]:
        columns = self.get_columns(table)
        keys = self.get_key_fields(table)
        selector_config = dict(self.selector_config)
        if override_keys is not None:
            configured = dict(selector_config.get("key_fields_by_table", {}))
            configured[table.qualified_name] = list(override_keys)
            selector_config["key_fields_by_table"] = configured
        form, update = build_dynamic_configs(
            table,
            columns,
            keys,
            base_form,
            base_update,
            selector_config,
        )
        return form, update, columns
