"""Lógica de conexión, validación, búsqueda, inserción y actualización."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as time_value
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

try:
    import pyodbc
except ModuleNotFoundError:  # Permite probar la lógica sin instalar dependencias.
    pyodbc = None  # type: ignore[assignment]


class ConfigurationError(ValueError):
    """La configuración de la tabla o de los campos no es válida."""


class ValidationError(ValueError):
    """Un valor capturado en el formulario no es válido."""


@dataclass(frozen=True)
class UpdateResult:
    affected: int
    matched: int
    requested: int


def quote_identifier(identifier: str) -> str:
    """Valida, escapa y delimita un identificador configurado para SQL Server."""
    if (
        not isinstance(identifier, str)
        or not identifier.strip()
        or len(identifier) > 128
        or any(ord(character) < 32 for character in identifier)
    ):
        raise ConfigurationError(f"Identificador SQL no válido: {identifier!r}.")
    return "[" + identifier.replace("]", "]]") + "]"


def escape_like(value: str) -> str:
    """Escapa comodines para buscar el texto escrito como una cadena literal."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _odbc_value(value: Any) -> str:
    """Protege valores que pueden contener punto y coma en la cadena ODBC."""
    return "{" + str(value).replace("}", "}}") + "}"


def build_connection_string(config: Mapping[str, Any]) -> str:
    required = ("driver", "server", "database")
    missing = [key for key in required if not str(config.get(key, "")).strip()]
    if missing:
        raise ConfigurationError("Faltan valores de conexión: " + ", ".join(missing))

    parts = [
        f"DRIVER={_odbc_value(config['driver'])}",
        f"SERVER={_odbc_value(config['server'])}",
        f"DATABASE={_odbc_value(config['database'])}",
        "Encrypt=yes",
        "TrustServerCertificate="
        + ("yes" if config.get("trust_server_certificate", False) else "no"),
        f"Connection Timeout={int(config.get('connection_timeout', 8))}",
    ]

    if config.get("trusted_connection", True):
        parts.append("Trusted_Connection=yes")
    else:
        username = str(config.get("username", "")).strip()
        password = str(config.get("password", ""))
        if not username or not password:
            raise ConfigurationError(
                "Para autenticación SQL define SQLSERVER_USER y SQLSERVER_PASSWORD."
            )
        parts.extend((f"UID={_odbc_value(username)}", f"PWD={_odbc_value(password)}"))

    return ";".join(parts) + ";"


def resolve_sql_server_driver(
    config: Mapping[str, Any],
    installed_drivers: Sequence[str] | None = None,
) -> str:
    """Elige el driver configurado o el primer candidato realmente instalado."""
    if installed_drivers is None:
        if pyodbc is None:
            raise ConfigurationError(
                "Falta pyodbc. Ejecuta: python -m pip install -r requirements.txt"
            )
        installed_drivers = list(pyodbc.drivers())

    installed_by_name = {
        str(driver).strip().casefold(): str(driver).strip()
        for driver in installed_drivers
        if str(driver).strip()
    }
    requested = str(config.get("driver", "")).strip()
    configured_candidates = config.get("driver_candidates", [])
    if not isinstance(configured_candidates, (list, tuple)):
        raise ConfigurationError("driver_candidates debe ser una lista.")
    configured = [
        str(driver).strip()
        for driver in configured_candidates
        if str(driver).strip()
    ]
    detected_sql_server = [
        actual
        for actual in installed_by_name.values()
        if "sql server" in actual.casefold()
    ]
    candidates = list(
        dict.fromkeys(
            [
                requested,
                *configured,
                "ODBC Driver 18 for SQL Server",
                "ODBC Driver 17 for SQL Server",
                "ODBC Driver 13.1 for SQL Server",
                "ODBC Driver 13 for SQL Server",
                "ODBC Driver 11 for SQL Server",
                "SQL Server Native Client 11.0",
                *detected_sql_server,
            ]
        )
    )
    for candidate in candidates:
        actual = installed_by_name.get(candidate.casefold())
        if actual:
            return actual

    installed_text = ", ".join(installed_by_name.values()) or "ninguno"
    expected_text = ", ".join(candidate for candidate in candidates if candidate)
    raise ConfigurationError(
        "No se encontró un controlador ODBC compatible con SQL Server. "
        f"Se buscaron: {expected_text}. Drivers instalados: {installed_text}. "
        "Instala un driver ODBC de SQL Server (11 o posterior) o corrige "
        "DB_CONFIG['driver']."
    )


def _empty_to_none(raw_value: Any) -> Any:
    if raw_value is None:
        return None
    if isinstance(raw_value, str) and not raw_value.strip():
        return None
    return raw_value


def convert_value(raw_value: Any, field: Mapping[str, Any]) -> Any:
    """Convierte el texto de la GUI a un valor compatible con pyodbc."""
    value = _empty_to_none(raw_value)
    label = field.get("label", field.get("name", "Campo"))
    required = bool(field.get("required", False))

    if value is None:
        if required:
            raise ValidationError(f"'{label}' es obligatorio.")
        return None

    value_type = str(field.get("type", "str")).lower()
    try:
        if value_type == "str":
            result = str(value).strip()
            max_length = field.get("max_length")
            if max_length is not None and len(result) > int(max_length):
                raise ValidationError(
                    f"'{label}' permite como máximo {max_length} caracteres."
                )
            return result
        if value_type == "int":
            if isinstance(value, float):
                if not value.is_integer():
                    raise ValueError
                return int(value)
            return int(str(value).strip())
        if value_type == "float":
            return float(str(value).strip().replace(",", "."))
        if value_type == "decimal":
            return Decimal(str(value).strip().replace(",", "."))
        if value_type == "bool":
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in {"1", "true", "si", "sí", "yes"}:
                return True
            if normalized in {"0", "false", "no"}:
                return False
            raise ValidationError(f"'{label}' debe ser Sí/No o True/False.")
        if value_type == "date":
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
        if value_type == "datetime":
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if value_type == "time":
            if isinstance(value, time_value):
                return value
            return time_value.fromisoformat(str(value).strip())
        raise ConfigurationError(f"Tipo no soportado para '{label}': {value_type!r}.")
    except ValidationError:
        raise
    except (ValueError, TypeError, InvalidOperation) as exc:
        expected = {
            "int": "un número entero",
            "float": "un número",
            "decimal": "un decimal",
            "date": "una fecha AAAA-MM-DD",
            "datetime": "una fecha y hora AAAA-MM-DD HH:MM:SS",
            "time": "una hora HH:MM:SS",
        }.get(value_type, value_type)
        raise ValidationError(f"'{label}' debe ser {expected}.") from exc


class SQLServerRepository:
    """Repositorio genérico para insertar, buscar y actualizar una tabla."""

    def __init__(
        self,
        db_config: Mapping[str, Any],
        form_config: Mapping[str, Any],
        update_config: Mapping[str, Any] | None = None,
        operation_logger: Any | None = None,
    ) -> None:
        self.db_config = db_config
        self.form_config = form_config
        self.update_config = update_config or {"enabled": False}
        self.operation_logger = operation_logger
        self.schema = str(form_config.get("schema", "dbo"))
        self.table = str(form_config.get("table", ""))
        self.fields: Sequence[Mapping[str, Any]] = form_config.get("fields", [])
        self.identity_column = form_config.get("identity_column")
        self.update_enabled = bool(self.update_config.get("enabled", False))
        self.key_fields = [str(name) for name in self.update_config.get("key_fields", [])]
        self.match_fields = [
            str(name) for name in self.update_config.get("match_fields", [])
        ]
        self.non_unique_mode = bool(
            self.update_config.get("non_unique_mode", False) and not self.key_fields
        )
        configured_column_types = self.update_config.get("column_types", {})
        self.column_types = (
            {str(name).casefold(): str(value) for name, value in configured_column_types.items()}
            if isinstance(configured_column_types, Mapping)
            else {}
        )
        self.field_by_name = {str(field["name"]).lower(): field for field in self.fields}
        self._validate_configuration()

    @property
    def table_name(self) -> str:
        return f"{quote_identifier(self.schema)}.{quote_identifier(self.table)}"

    def _validate_name_setting(self, setting_name: str) -> None:
        value = self.update_config.get(setting_name, "*")
        if value == "*":
            return
        if not isinstance(value, (list, tuple)) or not value:
            raise ConfigurationError(
                f"UPDATE_CONFIG['{setting_name}'] debe ser '*' o una lista no vacía."
            )
        for name in value:
            quote_identifier(str(name))

    def _validate_configuration(self) -> None:
        quote_identifier(self.schema)
        quote_identifier(self.table)
        if not self.fields:
            raise ConfigurationError("FORM_CONFIG debe contener al menos un campo.")

        names: list[str] = []
        allowed_types = {
            "str", "int", "float", "decimal", "bool", "date", "datetime", "time"
        }
        allowed_widgets = {"entry", "multiline", "checkbox", "combobox"}
        for field in self.fields:
            name = str(field.get("name", ""))
            quote_identifier(name)
            if name.lower() in names:
                raise ConfigurationError(f"El campo {name!r} está repetido.")
            names.append(name.lower())
            if str(field.get("type", "str")).lower() not in allowed_types:
                raise ConfigurationError(f"Tipo no soportado en el campo {name!r}.")
            if str(field.get("widget", "entry")).lower() not in allowed_widgets:
                raise ConfigurationError(f"Widget no soportado en el campo {name!r}.")

        if self.identity_column:
            quote_identifier(str(self.identity_column))

        if self.update_enabled:
            if not self.key_fields and not (self.non_unique_mode and self.match_fields):
                raise ConfigurationError(
                    "Para actualizar se necesita una clave única o columnas para "
                    "comparar los valores originales."
                )
            for name in self.key_fields:
                quote_identifier(name)
            for name in self.match_fields:
                quote_identifier(name)
            for setting in ("searchable_fields", "result_fields", "editable_fields"):
                self._validate_name_setting(setting)
            editable = self.update_config.get("editable_fields", "*")
            if editable != "*":
                invalid = [
                    str(name)
                    for name in editable
                    if str(name).lower() not in self.field_by_name
                ]
                if invalid:
                    raise ConfigurationError(
                        "Los campos editables deben existir en FORM_CONFIG['fields']: "
                        + ", ".join(invalid)
                    )
            mode = str(self.update_config.get("default_search_mode", "contains"))
            if mode not in {"contains", "exact"}:
                raise ConfigurationError("default_search_mode debe ser 'contains' o 'exact'.")
            maximum = int(self.update_config.get("max_results", 200))
            if not 1 <= maximum <= 5000:
                raise ConfigurationError("max_results debe estar entre 1 y 5000.")

    def _connect(self) -> Any:
        if pyodbc is None:
            raise ConfigurationError(
                "Falta pyodbc. Ejecuta: python -m pip install -r requirements.txt"
            )
        connection_config = dict(self.db_config)
        connection_config["driver"] = resolve_sql_server_driver(connection_config)
        return pyodbc.connect(build_connection_string(connection_config))

    def _log_operation(self, **details: Any) -> None:
        if self.operation_logger is None:
            return
        try:
            self.operation_logger.record(
                schema=self.schema,
                table=self.table,
                **details,
            )
        except Exception:
            # Un problema escribiendo el log nunca debe alterar la transacción SQL.
            pass

    def build_insert_statement(self, include_identity_output: bool = True) -> str:
        columns = ", ".join(quote_identifier(str(field["name"])) for field in self.fields)
        placeholders = ", ".join("?" for _ in self.fields)
        output = ""
        if self.identity_column and include_identity_output:
            output = f" OUTPUT INSERTED.{quote_identifier(str(self.identity_column))}"
        return f"INSERT INTO {self.table_name} ({columns}){output} VALUES ({placeholders});"

    def build_search_statement(
        self,
        search_column: str | None,
        mode: str,
        result_columns: Sequence[str],
        allowed_columns: Sequence[str],
    ) -> str:
        allowed = {name.lower(): name for name in allowed_columns}
        if search_column is not None and search_column.lower() not in allowed:
            raise ValidationError(f"La columna {search_column!r} no está habilitada para buscar.")
        if mode not in {"contains", "exact"}:
            raise ValidationError("El modo de búsqueda no es válido.")

        selected = ", ".join(quote_identifier(name) for name in result_columns)
        limit = int(self.update_config.get("max_results", 200))
        sql = f"SELECT TOP ({limit}) {selected} FROM {self.table_name}"
        if search_column is None:
            return sql + ";"
        actual_name = allowed[search_column.lower()]
        column = quote_identifier(actual_name)
        if mode == "contains":
            return sql + f" WHERE CONVERT(NVARCHAR(MAX), {column}) LIKE ? ESCAPE '\\';"
        return sql + f" WHERE {column} = ?;"

    def build_update_statement(
        self,
        editable_columns: Sequence[str],
        key_columns: Sequence[str] | None = None,
    ) -> str:
        keys = list(key_columns or self.key_fields)
        if not editable_columns:
            raise ConfigurationError("No hay campos configurados para actualizar.")
        if not keys:
            raise ConfigurationError("No hay una clave configurada para actualizar.")
        assignments = ", ".join(f"{quote_identifier(name)} = ?" for name in editable_columns)
        predicates = " AND ".join(
            f"({quote_identifier(name)} = ? OR "
            f"({quote_identifier(name)} IS NULL AND ? IS NULL))"
            for name in keys
        )
        return (
            f"SET NOCOUNT ON; UPDATE {self.table_name} SET {assignments} "
            f"WHERE {predicates}; SELECT @@ROWCOUNT;"
        )

    @staticmethod
    def _null_safe_predicate(columns: Sequence[str]) -> str:
        if not columns:
            raise ConfigurationError("No hay columnas disponibles para comparar filas.")
        return " AND ".join(
            f"({quote_identifier(name)} = ? OR "
            f"({quote_identifier(name)} IS NULL AND ? IS NULL))"
            for name in columns
        )

    def build_match_count_statement(self, lock_rows: bool = False) -> str:
        hint = " WITH (UPDLOCK, HOLDLOCK)" if lock_rows else ""
        predicate = self._null_safe_predicate(self.match_fields)
        return f"SELECT COUNT_BIG(*) FROM {self.table_name}{hint} WHERE {predicate};"

    def build_limited_update_statement(
        self, editable_columns: Sequence[str], requested_rows: int
    ) -> str:
        maximum = int(self.update_config.get("max_rows_per_update", 100000))
        if not 1 <= int(requested_rows) <= maximum:
            raise ValidationError(
                f"La cantidad debe estar entre 1 y {maximum:,}."
            )
        if not editable_columns:
            raise ConfigurationError("No hay campos configurados para actualizar.")
        assignments = ", ".join(
            f"{quote_identifier(name)} = ?" for name in editable_columns
        )
        predicate = self._null_safe_predicate(self.match_fields)
        # requested_rows se convierte y valida como entero antes de formar el SQL.
        return (
            f"SET NOCOUNT ON; UPDATE TOP ({int(requested_rows)}) {self.table_name} "
            f"SET {assignments} WHERE {predicate}; SELECT @@ROWCOUNT;"
        )

    def build_delete_statement(self) -> str:
        if not self.key_fields:
            raise ConfigurationError("No hay una clave configurada para eliminar.")
        predicates = " AND ".join(
            f"({quote_identifier(name)} = ? OR "
            f"({quote_identifier(name)} IS NULL AND ? IS NULL))"
            for name in self.key_fields
        )
        return (
            f"SET NOCOUNT ON; DELETE FROM {self.table_name} WHERE {predicates}; "
            "SELECT @@ROWCOUNT;"
        )

    def build_limited_delete_statement(self, requested_rows: int) -> str:
        maximum = int(self.update_config.get("max_rows_per_delete", 100000))
        if not 1 <= int(requested_rows) <= maximum:
            raise ValidationError(f"La cantidad debe estar entre 1 y {maximum:,}.")
        predicate = self._null_safe_predicate(self.match_fields)
        return (
            f"SET NOCOUNT ON; DELETE TOP ({int(requested_rows)}) FROM {self.table_name} "
            f"WHERE {predicate}; SELECT @@ROWCOUNT;"
        )

    def prepare_values(self, raw_values: Mapping[str, Any]) -> list[Any]:
        return [
            convert_value(raw_values.get(str(field["name"])), field)
            for field in self.fields
        ]

    def editable_fields(self) -> list[Mapping[str, Any]]:
        configured = self.update_config.get("editable_fields", "*")
        if configured == "*":
            return list(self.fields)
        wanted = {str(name).lower() for name in configured}
        return [field for field in self.fields if str(field["name"]).lower() in wanted]

    @staticmethod
    def _resolve_columns(configured: Any, actual_columns: Sequence[str]) -> list[str]:
        if configured == "*":
            return list(actual_columns)
        actual = {name.lower(): name for name in actual_columns}
        missing = [str(name) for name in configured if str(name).lower() not in actual]
        if missing:
            raise ConfigurationError(
                "Estas columnas configuradas no existen en la tabla: " + ", ".join(missing)
            )
        return [actual[str(name).lower()] for name in configured]

    def get_table_columns(self) -> list[str]:
        sql = """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION;
        """
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, self.schema, self.table)
            return [str(row[0]) for row in cursor.fetchall()]

    def get_update_metadata(self) -> dict[str, list[str]]:
        actual = self.get_table_columns()
        if not actual:
            raise ConfigurationError(f"No se encontró la tabla [{self.schema}].[{self.table}].")
        searchable = self._resolve_columns(
            self.update_config.get("searchable_fields", "*"), actual
        )
        results = self._resolve_columns(self.update_config.get("result_fields", "*"), actual)
        actual_map = {name.lower(): name for name in actual}
        required_in_result = self.key_fields + [
            str(field["name"]) for field in self.editable_fields()
        ]
        if self.non_unique_mode:
            required_in_result.extend(self.match_fields)
        for name in required_in_result:
            if name.lower() not in actual_map:
                raise ConfigurationError(
                    f"La columna necesaria para actualizar {name!r} no existe en la tabla."
                )
            actual_name = actual_map[name.lower()]
            if actual_name.lower() not in {column.lower() for column in results}:
                results.append(actual_name)
        return {"actual": actual, "searchable": searchable, "results": results}

    def test_connection(self) -> None:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()

    def validate_insert_structure(self) -> None:
        """Comprueba únicamente lo necesario para INSERT manual o masivo."""
        actual = self.get_table_columns()
        if not actual:
            raise ConfigurationError(f"No se encontró la tabla [{self.schema}].[{self.table}].")
        actual_names = {name.lower() for name in actual}
        configured = {str(field["name"]).lower() for field in self.fields}
        missing = sorted(configured - actual_names)
        if missing:
            raise ConfigurationError(
                "Estas columnas configuradas no existen en la tabla: " + ", ".join(missing)
            )
        if self.identity_column and str(self.identity_column).lower() not in actual_names:
            raise ConfigurationError(
                f"La columna identity_column {self.identity_column!r} no existe."
            )

    def validate_table_structure(self) -> None:
        self.validate_insert_structure()
        if self.update_enabled:
            self.get_update_metadata()

    def insert(self, raw_values: Mapping[str, Any]) -> Any | None:
        values = self.prepare_values(raw_values)
        sql = self.build_insert_statement()
        started = perf_counter()
        connection = None
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(sql, *values)
            generated_id = cursor.fetchone()[0] if self.identity_column else None
            connection.commit()
            self._log_operation(
                operation="INSERT MANUAL",
                sql=sql,
                status="CORRECTO",
                rows=1,
                duration_seconds=perf_counter() - started,
            )
            return generated_id
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            self._log_operation(
                operation="INSERT MANUAL",
                sql=sql,
                status="ERROR",
                rows=0,
                duration_seconds=perf_counter() - started,
                error=str(exc),
            )
            raise
        finally:
            if connection is not None:
                connection.close()

    def bulk_insert(
        self,
        prepared_rows: Sequence[Sequence[Any]],
        batch_size: int = 500,
        progress_callback: Callable[[int, int, int], None] | None = None,
        source_file: str | None = None,
    ) -> int:
        """Inserta filas validadas en una única transacción."""
        rows = prepared_rows
        if not rows:
            raise ValidationError("No hay filas validadas para insertar.")
        if not 1 <= int(batch_size) <= 5000:
            raise ConfigurationError("batch_size debe estar entre 1 y 5000.")
        expected_length = len(self.fields)
        invalid_index = next(
            (index for index, row in enumerate(rows, start=1) if len(row) != expected_length),
            None,
        )
        if invalid_index is not None:
            raise ValidationError(
                f"La fila preparada {invalid_index} no tiene {expected_length} valores."
            )

        sql = self.build_insert_statement(include_identity_output=False)
        total_batches = (len(rows) + int(batch_size) - 1) // int(batch_size)
        started = perf_counter()
        connection = None
        try:
            connection = self._connect()
            cursor = connection.cursor()
            if hasattr(cursor, "fast_executemany"):
                cursor.fast_executemany = True
            size = int(batch_size)
            for batch_number, start in enumerate(range(0, len(rows), size), start=1):
                cursor.executemany(sql, rows[start : start + size])
                if progress_callback is not None:
                    progress_callback(
                        min(start + size, len(rows)),
                        len(rows),
                        batch_number,
                    )
            connection.commit()
            self._log_operation(
                operation="INSERT MASIVO",
                sql=sql,
                status="CORRECTO",
                rows=len(rows),
                batch_size=size,
                batches=total_batches,
                duration_seconds=perf_counter() - started,
                source_file=source_file,
            )
            return len(rows)
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            self._log_operation(
                operation="INSERT MASIVO",
                sql=sql,
                status="ERROR",
                rows=0,
                batch_size=int(batch_size),
                batches=total_batches,
                duration_seconds=perf_counter() - started,
                source_file=source_file,
                error=str(exc),
            )
            raise
        finally:
            if connection is not None:
                connection.close()

    def search(
        self,
        search_column: str | None,
        search_value: str = "",
        mode: str = "contains",
    ) -> tuple[list[str], list[dict[str, Any]]]:
        if not self.update_enabled:
            raise ConfigurationError("La actualización está deshabilitada.")
        metadata = self.get_update_metadata()
        sql = self.build_search_statement(
            search_column,
            mode,
            metadata["results"],
            metadata["searchable"],
        )
        parameters: list[Any] = []
        if search_column is not None:
            if not str(search_value).strip():
                raise ValidationError("Escribe un valor para buscar.")
            if mode == "contains":
                parameters.append("%" + escape_like(str(search_value).strip()) + "%")
            else:
                field = self.field_by_name.get(search_column.lower())
                parameters.append(
                    convert_value(search_value, {**field, "required": True})
                    if field
                    else str(search_value).strip()
                )

        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, *parameters)
            rows = cursor.fetchall()
        columns = metadata["results"]
        return columns, [dict(zip(columns, row)) for row in rows]

    def update(self, raw_values: Mapping[str, Any], original_row: Mapping[str, Any]) -> int:
        if not self.update_enabled:
            raise ConfigurationError("La actualización está deshabilitada.")
        editable = self.editable_fields()
        editable_names = [str(field["name"]) for field in editable]
        new_values = [
            convert_value(raw_values.get(name), field)
            for name, field in zip(editable_names, editable)
        ]

        original_lower = {str(name).lower(): value for name, value in original_row.items()}
        missing_keys = [name for name in self.key_fields if name.lower() not in original_lower]
        if missing_keys:
            raise ValidationError(
                "El resultado seleccionado no contiene la clave: " + ", ".join(missing_keys)
            )
        key_values = [original_lower[name.lower()] for name in self.key_fields]
        parameters = new_values + [value for value in key_values for _ in (0, 1)]
        sql = self.build_update_statement(editable_names)

        started = perf_counter()
        connection = None
        affected = 0
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(sql, *parameters)
            row = cursor.fetchone()
            affected = int(row[0]) if row else 0
            if affected != 1:
                raise ValidationError(
                    "La actualización fue cancelada porque habría afectado "
                    f"{affected} registros. Revisa UPDATE_CONFIG['key_fields']; "
                    "debe identificar una sola fila."
                )
            connection.commit()
            self._log_operation(
                operation="UPDATE",
                sql=sql,
                status="CORRECTO",
                rows=affected,
                matched_rows=1,
                requested_rows=1,
                transaction="COMMIT",
                duration_seconds=perf_counter() - started,
            )
            return affected
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            self._log_operation(
                operation="UPDATE",
                sql=sql,
                status="ERROR / ROLLBACK",
                rows=0,
                matched_rows=affected,
                requested_rows=1,
                transaction="ROLLBACK",
                duration_seconds=perf_counter() - started,
                error=str(exc),
            )
            raise
        finally:
            if connection is not None:
                connection.close()

    def _match_parameters(self, original_row: Mapping[str, Any]) -> list[Any]:
        original_lower = {
            str(name).casefold(): value for name, value in original_row.items()
        }
        missing = [
            name for name in self.match_fields if name.casefold() not in original_lower
        ]
        if missing:
            raise ValidationError(
                "El resultado no contiene las columnas necesarias para compararlo: "
                + ", ".join(missing)
            )
        values = [original_lower[name.casefold()] for name in self.match_fields]
        return [value for value in values for _ in (0, 1)]

    def count_matching_rows(self, original_row: Mapping[str, Any]) -> int:
        if not self.non_unique_mode:
            return 1
        sql = self.build_match_count_statement()
        parameters = self._match_parameters(original_row)
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(sql, *parameters)
            row = cursor.fetchone()
        return int(row[0]) if row else 0

    def update_matching_rows(
        self,
        raw_values: Mapping[str, Any],
        original_row: Mapping[str, Any],
        requested_rows: int,
    ) -> UpdateResult:
        """Actualiza una cantidad exacta de filas con los mismos valores originales."""
        if not self.update_enabled or not self.non_unique_mode:
            raise ConfigurationError(
                "La actualización por cantidad no está habilitada para esta tabla."
            )
        try:
            requested = int(requested_rows)
        except (TypeError, ValueError) as exc:
            raise ValidationError("La cantidad a actualizar debe ser un entero.") from exc

        editable = self.editable_fields()
        editable_names = [str(field["name"]) for field in editable]
        new_values = [
            convert_value(raw_values.get(name), field)
            for name, field in zip(editable_names, editable)
        ]
        match_parameters = self._match_parameters(original_row)
        count_sql = self.build_match_count_statement(lock_rows=True)
        update_sql = self.build_limited_update_statement(editable_names, requested)
        logged_sql = (
            "-- Coincidencias bloqueadas dentro de la transacción\n"
            + count_sql
            + "\n\n-- Actualización solicitada\n"
            + update_sql
        )

        started = perf_counter()
        connection = None
        matched = 0
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(count_sql, *match_parameters)
            row = cursor.fetchone()
            matched = int(row[0]) if row else 0
            if not 1 <= requested <= matched:
                raise ValidationError(
                    f"La cantidad debe estar entre 1 y las {matched:,} "
                    "coincidencias disponibles."
                )

            cursor.execute(update_sql, *(new_values + match_parameters))
            affected_row = cursor.fetchone()
            affected = int(affected_row[0]) if affected_row else 0
            if affected != requested:
                raise ValidationError(
                    "La operación fue cancelada: se solicitaron "
                    f"{requested:,} filas pero SQL Server reportó {affected:,}."
                )
            connection.commit()
            self._log_operation(
                operation="UPDATE POR CANTIDAD",
                sql=logged_sql,
                status="CORRECTO",
                rows=affected,
                matched_rows=matched,
                requested_rows=requested,
                transaction="COMMIT",
                duration_seconds=perf_counter() - started,
            )
            return UpdateResult(affected, matched, requested)
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            self._log_operation(
                operation="UPDATE POR CANTIDAD",
                sql=logged_sql,
                status="ERROR / ROLLBACK",
                rows=0,
                matched_rows=matched,
                requested_rows=requested,
                transaction="ROLLBACK",
                duration_seconds=perf_counter() - started,
                error=str(exc),
            )
            raise
        finally:
            if connection is not None:
                connection.close()

    def delete(self, original_row: Mapping[str, Any]) -> int:
        """Elimina exactamente un registro identificado por su clave única."""
        original_lower = {
            str(name).casefold(): value for name, value in original_row.items()
        }
        missing = [name for name in self.key_fields if name.casefold() not in original_lower]
        if missing:
            raise ValidationError(
                "El resultado seleccionado no contiene la clave: " + ", ".join(missing)
            )
        values = [original_lower[name.casefold()] for name in self.key_fields]
        parameters = [value for value in values for _ in (0, 1)]
        sql = self.build_delete_statement()
        return self._execute_delete(sql, parameters, 1, 1, "DELETE")

    def delete_matching_rows(
        self, original_row: Mapping[str, Any], requested_rows: int
    ) -> UpdateResult:
        """Elimina una cantidad exacta de filas que tienen los mismos valores."""
        if not self.non_unique_mode:
            raise ConfigurationError("La eliminación por cantidad no está habilitada.")
        try:
            requested = int(requested_rows)
        except (TypeError, ValueError) as exc:
            raise ValidationError("La cantidad a eliminar debe ser un entero.") from exc
        parameters = self._match_parameters(original_row)
        count_sql = self.build_match_count_statement(lock_rows=True)
        delete_sql = self.build_limited_delete_statement(requested)
        connection = None
        matched = 0
        started = perf_counter()
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(count_sql, *parameters)
            row = cursor.fetchone()
            matched = int(row[0]) if row else 0
            if not 1 <= requested <= matched:
                raise ValidationError(
                    f"La cantidad debe estar entre 1 y las {matched:,} coincidencias disponibles."
                )
            cursor.execute(delete_sql, *parameters)
            affected_row = cursor.fetchone()
            affected = int(affected_row[0]) if affected_row else 0
            if affected != requested:
                raise ValidationError(
                    f"Se solicitaron {requested:,} filas, pero el motor reportó {affected:,}."
                )
            connection.commit()
            self._log_operation(
                operation="DELETE POR CANTIDAD", sql=count_sql + "\n" + delete_sql,
                status="CORRECTO", rows=affected, matched_rows=matched,
                requested_rows=requested, transaction="COMMIT",
                duration_seconds=perf_counter() - started,
            )
            return UpdateResult(affected, matched, requested)
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            self._log_operation(
                operation="DELETE POR CANTIDAD", sql=count_sql + "\n" + delete_sql,
                status="ERROR / ROLLBACK", rows=0, matched_rows=matched,
                requested_rows=requested, transaction="ROLLBACK",
                duration_seconds=perf_counter() - started, error=str(exc),
            )
            raise
        finally:
            if connection is not None:
                connection.close()

    def _execute_delete(
        self, sql: str, parameters: Sequence[Any], requested: int,
        matched: int, operation: str,
    ) -> int:
        connection = None
        started = perf_counter()
        affected = 0
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(sql, *parameters)
            row = cursor.fetchone()
            affected = int(row[0]) if row else 0
            if affected != requested:
                raise ValidationError(
                    f"La eliminación se canceló porque habría afectado {affected} registros."
                )
            connection.commit()
            self._log_operation(
                operation=operation, sql=sql, status="CORRECTO", rows=affected,
                matched_rows=matched, requested_rows=requested,
                transaction="COMMIT", duration_seconds=perf_counter() - started,
            )
            return affected
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            self._log_operation(
                operation=operation, sql=sql, status="ERROR / ROLLBACK", rows=0,
                matched_rows=matched, requested_rows=requested,
                transaction="ROLLBACK", duration_seconds=perf_counter() - started,
                error=str(exc),
            )
            raise
        finally:
            if connection is not None:
                connection.close()
