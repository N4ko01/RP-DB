import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, call

from database import (
    ConfigurationError,
    SQLServerRepository,
    ValidationError,
    build_connection_string,
    convert_value,
    escape_like,
    quote_identifier,
    resolve_sql_server_driver,
)


class DatabaseLogicTests(unittest.TestCase):
    @staticmethod
    def make_update_repository():
        return SQLServerRepository(
            {"driver": "x", "server": "x", "database": "x"},
            {
                "schema": "dbo",
                "table": "Clientes",
                "identity_column": "ClienteID",
                "fields": [
                    {"name": "Nombre", "type": "str", "required": True},
                    {"name": "Edad", "type": "int", "required": False},
                ],
            },
            {
                "enabled": True,
                "key_fields": ["ClienteID"],
                "searchable_fields": "*",
                "result_fields": "*",
                "editable_fields": "*",
                "default_search_mode": "contains",
                "max_results": 200,
            },
        )

    @staticmethod
    def make_non_unique_repository():
        return SQLServerRepository(
            {"driver": "x", "server": "x", "database": "x"},
            {
                "schema": "dbo",
                "table": "Campania_Example",
                "identity_column": None,
                "fields": [
                    {"name": "campania", "type": "str", "required": True},
                    {"name": "publisher", "type": "str", "required": True},
                    {"name": "num_campania", "type": "int", "required": False},
                ],
            },
            {
                "enabled": True,
                "key_fields": [],
                "match_fields": ["campania", "publisher", "num_campania"],
                "non_unique_mode": True,
                "searchable_fields": "*",
                "result_fields": "*",
                "editable_fields": "*",
                "default_search_mode": "contains",
                "max_results": 200,
                "max_rows_per_update": 100000,
            },
        )

    def test_identifier_is_delimited(self):
        self.assertEqual(quote_identifier("Nombre_1"), "[Nombre_1]")

    def test_identifier_closing_bracket_is_escaped(self):
        self.assertEqual(
            quote_identifier("Clientes]; DROP TABLE Clientes--"),
            "[Clientes]]; DROP TABLE Clientes--]",
        )

    def test_empty_identifier_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            quote_identifier("")

    def test_value_conversions(self):
        self.assertEqual(convert_value("42", {"name": "Edad", "type": "int"}), 42)
        self.assertEqual(
            convert_value("12,50", {"name": "Monto", "type": "decimal"}),
            Decimal("12.50"),
        )
        self.assertEqual(
            convert_value("2026-08-13", {"name": "Fecha", "type": "date"}),
            date(2026, 8, 13),
        )
        self.assertEqual(
            convert_value(
                "2026-08-13 14:30:00", {"name": "Fecha", "type": "datetime"}
            ),
            datetime(2026, 8, 13, 14, 30),
        )

    def test_required_field(self):
        with self.assertRaises(ValidationError):
            convert_value("", {"name": "Nombre", "type": "str", "required": True})

    def test_insert_is_parameterized(self):
        repo = SQLServerRepository(
            {"driver": "x", "server": "x", "database": "x"},
            {
                "schema": "dbo",
                "table": "Clientes",
                "identity_column": "ClienteID",
                "fields": [
                    {"name": "Nombre", "type": "str"},
                    {"name": "Edad", "type": "int"},
                ],
            },
        )
        self.assertEqual(
            repo.build_insert_statement(),
            "INSERT INTO [dbo].[Clientes] ([Nombre], [Edad]) "
            "OUTPUT INSERTED.[ClienteID] VALUES (?, ?);",
        )

    def test_bulk_insert_does_not_request_identity_output(self):
        repo = self.make_update_repository()
        self.assertEqual(
            repo.build_insert_statement(include_identity_output=False),
            "INSERT INTO [dbo].[Clientes] ([Nombre], [Edad]) VALUES (?, ?);",
        )

    def test_bulk_insert_uses_batches_and_one_commit(self):
        repo = self.make_update_repository()
        cursor = MagicMock()
        cursor.fast_executemany = False
        connection = MagicMock()
        connection.cursor.return_value = cursor
        repo._connect = MagicMock(return_value=connection)

        inserted = repo.bulk_insert(
            [["Ana", 20], ["Luis", 30], ["Eva", None]],
            batch_size=2,
        )

        self.assertEqual(inserted, 3)
        self.assertTrue(cursor.fast_executemany)
        self.assertEqual(cursor.executemany.call_count, 2)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_bulk_insert_rolls_back_on_error(self):
        repo = self.make_update_repository()
        cursor = MagicMock()
        cursor.fast_executemany = False
        cursor.executemany.side_effect = RuntimeError("fallo simulado")
        connection = MagicMock()
        connection.cursor.return_value = cursor
        repo._connect = MagicMock(return_value=connection)

        with self.assertRaises(RuntimeError):
            repo.bulk_insert([["Ana", 20]], batch_size=100)

        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()
        connection.close.assert_called_once_with()

    def test_bulk_insert_reports_batches_and_writes_summary_log(self):
        repo = self.make_update_repository()
        cursor = MagicMock()
        cursor.fast_executemany = False
        connection = MagicMock()
        connection.cursor.return_value = cursor
        repo._connect = MagicMock(return_value=connection)
        repo.operation_logger = MagicMock()
        progress = MagicMock()

        repo.bulk_insert(
            [["Ana", 20], ["Luis", 30], ["Eva", 40]],
            batch_size=2,
            progress_callback=progress,
            source_file="clientes.xlsx",
        )

        self.assertEqual(
            progress.call_args_list,
            [
                call(2, 3, 1),
                call(3, 3, 2),
            ],
        )
        logged = repo.operation_logger.record.call_args.kwargs
        self.assertEqual(logged["operation"], "INSERT MASIVO")
        self.assertEqual(logged["rows"], 3)
        self.assertEqual(logged["batches"], 2)
        self.assertEqual(logged["source_file"], "clientes.xlsx")

    def test_trusted_connection_string(self):
        result = build_connection_string(
            {
                "driver": "ODBC Driver 18 for SQL Server",
                "server": r"localhost\SQLEXPRESS",
                "database": "Demo",
                "trusted_connection": True,
            }
        )
        self.assertIn("Trusted_Connection=yes", result)
        self.assertNotIn("PWD=", result)

    def test_driver_falls_back_from_18_to_installed_17(self):
        selected = resolve_sql_server_driver(
            {
                "driver": "ODBC Driver 18 for SQL Server",
                "driver_candidates": [
                    "ODBC Driver 18 for SQL Server",
                    "ODBC Driver 17 for SQL Server",
                ],
            },
            installed_drivers=["ODBC Driver 17 for SQL Server"],
        )
        self.assertEqual(selected, "ODBC Driver 17 for SQL Server")

    def test_missing_sql_server_driver_has_clear_error(self):
        with self.assertRaisesRegex(ConfigurationError, "Drivers instalados"):
            resolve_sql_server_driver(
                {"driver": "ODBC Driver 18 for SQL Server"},
                installed_drivers=["PostgreSQL Unicode"],
            )

    def test_like_wildcards_are_escaped(self):
        self.assertEqual(escape_like(r"50%_A\B"), r"50\%\_A\\B")

    def test_contains_search_is_parameterized(self):
        repo = self.make_update_repository()
        sql = repo.build_search_statement(
            "Nombre", "contains", ["ClienteID", "Nombre"], ["Nombre", "Edad"]
        )
        self.assertEqual(
            sql,
            "SELECT TOP (200) [ClienteID], [Nombre] FROM [dbo].[Clientes] "
            "WHERE CONVERT(NVARCHAR(MAX), [Nombre]) LIKE ? ESCAPE '\\';",
        )

    def test_unknown_search_column_is_rejected(self):
        repo = self.make_update_repository()
        with self.assertRaises(ValidationError):
            repo.build_search_statement(
                "NoPermitida", "exact", ["Nombre"], ["Nombre", "Edad"]
            )

    def test_update_uses_original_key_as_parameter(self):
        repo = self.make_update_repository()
        self.assertEqual(
            repo.build_update_statement(["Nombre", "Edad"]),
            "SET NOCOUNT ON; UPDATE [dbo].[Clientes] SET [Nombre] = ?, [Edad] = ? "
            "WHERE ([ClienteID] = ? OR ([ClienteID] IS NULL AND ? IS NULL)); "
            "SELECT @@ROWCOUNT;",
        )

    def test_update_requires_key_fields(self):
        with self.assertRaises(ConfigurationError):
            SQLServerRepository(
                {"driver": "x", "server": "x", "database": "x"},
                {
                    "schema": "dbo",
                    "table": "Clientes",
                    "fields": [{"name": "Nombre", "type": "str"}],
                },
                {"enabled": True, "key_fields": []},
            )

    def test_limited_update_uses_original_values_and_validated_top(self):
        repo = self.make_non_unique_repository()
        sql = repo.build_limited_update_statement(
            ["campania", "publisher", "num_campania"], 3
        )
        self.assertIn("UPDATE TOP (3) [dbo].[Campania_Example]", sql)
        self.assertIn("([num_campania] IS NULL AND ? IS NULL)", sql)
        self.assertNotIn("TOP (?)", sql)

    def test_non_unique_update_changes_exact_requested_quantity_and_logs(self):
        repo = self.make_non_unique_repository()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(5,), (3,)]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        repo._connect = MagicMock(return_value=connection)
        repo.operation_logger = MagicMock()

        result = repo.update_matching_rows(
            {"campania": "Nueva", "publisher": "Meta", "num_campania": 9},
            {"campania": "Anterior", "publisher": "Meta", "num_campania": None},
            3,
        )

        self.assertEqual((result.affected, result.matched, result.requested), (3, 5, 3))
        self.assertEqual(cursor.execute.call_count, 2)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        logged = repo.operation_logger.record.call_args.kwargs
        self.assertEqual(logged["operation"], "UPDATE POR CANTIDAD")
        self.assertEqual(logged["matched_rows"], 5)
        self.assertEqual(logged["requested_rows"], 3)
        self.assertEqual(logged["rows"], 3)
        self.assertEqual(logged["transaction"], "COMMIT")

    def test_non_unique_update_rolls_back_if_requested_exceeds_matches(self):
        repo = self.make_non_unique_repository()
        cursor = MagicMock()
        cursor.fetchone.return_value = (2,)
        connection = MagicMock()
        connection.cursor.return_value = cursor
        repo._connect = MagicMock(return_value=connection)
        repo.operation_logger = MagicMock()

        with self.assertRaisesRegex(ValidationError, "entre 1 y las 2"):
            repo.update_matching_rows(
                {"campania": "Nueva", "publisher": "Meta", "num_campania": 9},
                {"campania": "Anterior", "publisher": "Meta", "num_campania": None},
                3,
            )

        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()
        logged = repo.operation_logger.record.call_args.kwargs
        self.assertEqual(logged["transaction"], "ROLLBACK")

    def test_delete_uses_key_and_commits_exactly_one_row(self):
        repo = self.make_update_repository()
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        connection = MagicMock()
        connection.cursor.return_value = cursor
        repo._connect = MagicMock(return_value=connection)

        affected = repo.delete({"ClienteID": 7, "Nombre": "Ana"})

        self.assertEqual(affected, 1)
        sql, *parameters = cursor.execute.call_args.args
        self.assertIn("DELETE FROM [dbo].[Clientes]", sql)
        self.assertEqual(parameters, [7, 7])
        connection.commit.assert_called_once_with()

    def test_limited_delete_uses_validated_top(self):
        repo = self.make_non_unique_repository()
        sql = repo.build_limited_delete_statement(3)
        self.assertIn("DELETE TOP (3) FROM [dbo].[Campania_Example]", sql)
        self.assertNotIn("TOP (?)", sql)


if __name__ == "__main__":
    unittest.main()
