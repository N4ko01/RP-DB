"""Implementaciones específicas para PostgreSQL usando el conector psycopg."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from catalog import (
    ColumnMetadata,
    SQLServerCatalog,
    TableReference,
    build_dynamic_configs,
)
from database import ConfigurationError, SQLServerRepository, ValidationError

try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None  # type: ignore[assignment]


def quote_postgres_identifier(identifier: str) -> str:
    if (
        not isinstance(identifier, str)
        or not identifier.strip()
        or len(identifier) > 63
        or any(ord(character) < 32 for character in identifier)
    ):
        raise ConfigurationError(f"Identificador PostgreSQL no válido: {identifier!r}.")
    return '"' + identifier.replace('"', '""') + '"'


def build_postgres_connection_parameters(config: Mapping[str, Any]) -> dict[str, Any]:
    required = ("server", "database", "username")
    missing = [name for name in required if not str(config.get(name, "")).strip()]
    if missing:
        raise ConfigurationError(
            "Faltan valores de conexión PostgreSQL: " + ", ".join(missing)
        )
    parameters: dict[str, Any] = {
        "host": str(config["server"]).strip(),
        "dbname": str(config["database"]).strip(),
        "user": str(config["username"]).strip(),
        "password": str(config.get("password", "")),
        "port": int(config.get("port", 5432)),
        "connect_timeout": int(config.get("connection_timeout", 8)),
    }
    sslmode = str(config.get("sslmode", "prefer")).strip()
    if sslmode:
        parameters["sslmode"] = sslmode
    return parameters


class _PsycopgCursorAdapter:
    """Adapta psycopg a la forma de llamada usada por el repositorio común."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def execute(self, statement: str, *parameters: Any) -> "_PsycopgCursorAdapter":
        self._cursor.execute(statement, parameters or None)
        return self

    def executemany(self, statement: str, rows: Sequence[Sequence[Any]]) -> None:
        self._cursor.executemany(statement, rows)

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> Any:
        return self._cursor.fetchall()


class _PsycopgConnectionAdapter:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def cursor(self) -> _PsycopgCursorAdapter:
        return _PsycopgCursorAdapter(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "_PsycopgConnectionAdapter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is not None:
            self.rollback()
        self.close()


class PostgreSQLRepository(SQLServerRepository):
    """Repositorio PostgreSQL con la misma API que el repositorio SQL Server."""

    provider_name = "PostgreSQL"

    @property
    def table_name(self) -> str:
        return (
            f"{quote_postgres_identifier(self.schema)}."
            f"{quote_postgres_identifier(self.table)}"
        )

    def _connect(self) -> Any:
        if psycopg is None:
            raise ConfigurationError(
                "Falta psycopg. Ejecuta: python -m pip install -r requirements.txt"
            )
        connection = psycopg.connect(**build_postgres_connection_parameters(self.db_config))
        return _PsycopgConnectionAdapter(connection)

    def build_insert_statement(self, include_identity_output: bool = True) -> str:
        columns = ", ".join(
            quote_postgres_identifier(str(field["name"])) for field in self.fields
        )
        placeholders = ", ".join("%s" for _ in self.fields)
        returning = ""
        if self.identity_column and include_identity_output:
            returning = f" RETURNING {quote_postgres_identifier(str(self.identity_column))}"
        return f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders}){returning};"

    def build_search_statement(
        self, search_column: str | None, mode: str,
        result_columns: Sequence[str], allowed_columns: Sequence[str],
    ) -> str:
        allowed = {name.casefold(): name for name in allowed_columns}
        if search_column is not None and search_column.casefold() not in allowed:
            raise ValidationError(f"La columna {search_column!r} no está habilitada para buscar.")
        if mode not in {"contains", "exact"}:
            raise ValidationError("El modo de búsqueda no es válido.")
        selected = ", ".join(quote_postgres_identifier(name) for name in result_columns)
        sql = f"SELECT {selected} FROM {self.table_name}"
        if search_column is not None:
            column = quote_postgres_identifier(allowed[search_column.casefold()])
            if mode == "contains":
                sql += f" WHERE CAST({column} AS TEXT) LIKE %s ESCAPE '\\'"
            else:
                sql += f" WHERE {column} = %s"
        limit = int(self.update_config.get("max_results", 200))
        return sql + f" LIMIT {limit};"

    @staticmethod
    def _null_safe_predicate(columns: Sequence[str]) -> str:
        if not columns:
            raise ConfigurationError("No hay columnas disponibles para comparar filas.")
        return " AND ".join(
            f"({quote_postgres_identifier(name)} = %s OR "
            f"({quote_postgres_identifier(name)} IS NULL AND %s IS NULL))"
            for name in columns
        )

    def build_update_statement(
        self, editable_columns: Sequence[str], key_columns: Sequence[str] | None = None,
    ) -> str:
        keys = list(key_columns or self.key_fields)
        if not editable_columns or not keys:
            raise ConfigurationError("Faltan campos editables o una clave para actualizar.")
        assignments = ", ".join(
            f"{quote_postgres_identifier(name)} = %s" for name in editable_columns
        )
        predicate = self._null_safe_predicate(keys)
        return (
            "WITH changed AS ("
            f"UPDATE {self.table_name} SET {assignments} WHERE {predicate} RETURNING 1"
            ") SELECT COUNT(*) FROM changed;"
        )

    def build_match_count_statement(self, lock_rows: bool = False) -> str:
        predicate = self._null_safe_predicate(self.match_fields)
        return f"SELECT COUNT(*) FROM {self.table_name} WHERE {predicate};"

    def build_limited_update_statement(
        self, editable_columns: Sequence[str], requested_rows: int,
    ) -> str:
        maximum = int(self.update_config.get("max_rows_per_update", 100000))
        if not 1 <= int(requested_rows) <= maximum:
            raise ValidationError(f"La cantidad debe estar entre 1 y {maximum:,}.")
        assignments = ", ".join(
            f"{quote_postgres_identifier(name)} = %s" for name in editable_columns
        )
        predicate = self._null_safe_predicate(self.match_fields)
        return (
            "WITH changed AS ("
            f"UPDATE {self.table_name} SET {assignments} WHERE ctid IN ("
            f"SELECT ctid FROM {self.table_name} WHERE {predicate} "
            f"LIMIT {int(requested_rows)} FOR UPDATE) RETURNING 1"
            ") SELECT COUNT(*) FROM changed;"
        )

    def build_delete_statement(self) -> str:
        predicate = self._null_safe_predicate(self.key_fields)
        return (
            "WITH deleted AS ("
            f"DELETE FROM {self.table_name} WHERE {predicate} RETURNING 1"
            ") SELECT COUNT(*) FROM deleted;"
        )

    def build_limited_delete_statement(self, requested_rows: int) -> str:
        maximum = int(self.update_config.get("max_rows_per_delete", 100000))
        if not 1 <= int(requested_rows) <= maximum:
            raise ValidationError(f"La cantidad debe estar entre 1 y {maximum:,}.")
        predicate = self._null_safe_predicate(self.match_fields)
        return (
            "WITH targets AS ("
            f"SELECT ctid FROM {self.table_name} WHERE {predicate} "
            f"LIMIT {int(requested_rows)} FOR UPDATE), deleted AS ("
            f"DELETE FROM {self.table_name} WHERE ctid IN (SELECT ctid FROM targets) "
            "RETURNING 1) SELECT COUNT(*) FROM deleted;"
        )

    def get_table_columns(self) -> list[str]:
        sql = """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """
        with self._connect() as connection:
            rows = connection.cursor().execute(sql, self.schema, self.table).fetchall()
        return [str(row[0]) for row in rows]


class PostgreSQLCatalog(SQLServerCatalog):
    """Catálogo de tablas, columnas y claves de PostgreSQL."""

    def _connect(self) -> Any:
        if psycopg is None:
            raise ConfigurationError(
                "Falta psycopg. Ejecuta: python -m pip install -r requirements.txt"
            )
        return _PsycopgConnectionAdapter(
            psycopg.connect(**build_postgres_connection_parameters(self.db_config))
        )

    def list_tables(self) -> list[TableReference]:
        sql = """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name;
        """
        with self._connect() as connection:
            rows = connection.cursor().execute(sql).fetchall()
        return [
            TableReference(str(schema), str(table))
            for schema, table in rows
            if self._allowed(str(schema), self.selector_config.get("allowed_schemas", "*"))
            and (
                self._allowed(f"{schema}.{table}", self.selector_config.get("allowed_tables", "*"))
                or self._allowed(str(table), self.selector_config.get("allowed_tables", "*"))
            )
        ]

    def get_columns(self, table: TableReference) -> list[ColumnMetadata]:
        sql = """
            SELECT column_name, data_type, character_maximum_length,
                   numeric_precision, numeric_scale, is_nullable,
                   is_identity, is_generated, column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """
        with self._connect() as connection:
            rows = connection.cursor().execute(sql, table.schema, table.table).fetchall()
        if not rows:
            raise ConfigurationError(f"No se encontró la tabla {table.qualified_name}.")
        return [
            ColumnMetadata(
                name=str(row[0]), sql_type=str(row[1]),
                max_length=int(row[2]) if row[2] is not None else None,
                precision=int(row[3]) if row[3] is not None else None,
                scale=int(row[4]) if row[4] is not None else None,
                nullable=str(row[5]).upper() == "YES",
                identity=str(row[6]).upper() == "YES" or str(row[8] or "").startswith("nextval("),
                computed=str(row[7]).upper() not in {"NEVER", ""},
                has_default=row[8] is not None,
            )
            for row in rows
        ]

    def get_key_fields(self, table: TableReference) -> list[str]:
        sql = """
            SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            WHERE tc.table_schema = %s AND tc.table_name = %s
              AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
            ORDER BY CASE tc.constraint_type WHEN 'PRIMARY KEY' THEN 0 ELSE 1 END,
                     tc.constraint_name, kcu.ordinal_position;
        """
        with self._connect() as connection:
            rows = connection.cursor().execute(sql, table.schema, table.table).fetchall()
        if not rows:
            return []
        selected_constraint = str(rows[0][0])
        return [str(row[2]) for row in rows if str(row[0]) == selected_constraint]

    def validate_unique_key(
        self, table: TableReference, key_fields: Sequence[str],
        columns: Sequence[ColumnMetadata] | None = None,
    ) -> bool:
        if not key_fields:
            raise ConfigurationError("Selecciona al menos una columna.")
        grouped = ", ".join(quote_postgres_identifier(name) for name in key_fields)
        qualified = (
            f"{quote_postgres_identifier(table.schema)}."
            f"{quote_postgres_identifier(table.table)}"
        )
        sql = (
            f"SELECT 1 FROM {qualified} GROUP BY {grouped} "
            "HAVING COUNT(*) > 1 LIMIT 1;"
        )
        with self._connect() as connection:
            duplicate = connection.cursor().execute(sql).fetchone()
        return duplicate is None

    def build_configs(self, table: TableReference, base_form: Mapping[str, Any],
                      base_update: Mapping[str, Any],
                      override_keys: Sequence[str] | None = None):
        columns = self.get_columns(table)
        keys = self.get_key_fields(table)
        selector = dict(self.selector_config)
        if override_keys is not None:
            configured = dict(selector.get("key_fields_by_table", {}))
            configured[table.qualified_name] = list(override_keys)
            selector["key_fields_by_table"] = configured
        form, update = build_dynamic_configs(
            table, columns, keys, base_form, base_update, selector
        )
        form["window_title"] = f"Gestión PostgreSQL - {table.qualified_name}"
        return form, update, columns
