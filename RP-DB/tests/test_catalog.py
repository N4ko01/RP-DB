import unittest
from unittest.mock import MagicMock

from catalog import (
    ColumnMetadata,
    SQLServerCatalog,
    TableReference,
    build_dynamic_configs,
    sql_column_to_field,
    sql_display_type,
)


class CatalogTests(unittest.TestCase):
    @staticmethod
    def column(
        name,
        sql_type,
        *,
        max_length=None,
        precision=None,
        scale=None,
        nullable=False,
        identity=False,
        computed=False,
        has_default=False,
    ):
        return ColumnMetadata(
            name=name,
            sql_type=sql_type,
            max_length=max_length,
            precision=precision,
            scale=scale,
            nullable=nullable,
            identity=identity,
            computed=computed,
            has_default=has_default,
        )

    def test_sql_types_are_mapped_to_form_fields(self):
        text = sql_column_to_field(
            self.column("campania", "nvarchar", max_length=300)
        )
        number = sql_column_to_field(self.column("num_campania", "int", nullable=True))
        unique_id = sql_column_to_field(
            self.column("RegistroID", "uniqueidentifier", max_length=16)
        )
        self.assertEqual(text["type"], "str")
        self.assertEqual(text["max_length"], 150)
        self.assertEqual(number["type"], "int")
        self.assertFalse(number["required"])
        self.assertEqual(unique_id["max_length"], 36)
        self.assertEqual(text["sql_type_display"], "NVARCHAR(150)")

    def test_sql_display_type_includes_length_precision_and_scale(self):
        self.assertEqual(
            sql_display_type(self.column("Nombre", "varchar", max_length=-1)),
            "VARCHAR(MAX)",
        )
        self.assertEqual(
            sql_display_type(
                self.column("Precio", "decimal", precision=12, scale=2)
            ),
            "DECIMAL(12,2)",
        )
        self.assertEqual(
            sql_display_type(self.column("Fecha", "datetime2", scale=7)),
            "DATETIME2(7)",
        )

    def test_identity_computed_and_rowversion_are_not_editable(self):
        self.assertIsNone(
            sql_column_to_field(self.column("ID", "int", identity=True))
        )
        self.assertIsNone(
            sql_column_to_field(self.column("Total", "decimal", computed=True))
        )
        self.assertIsNone(sql_column_to_field(self.column("RV", "rowversion")))

    def test_dynamic_config_uses_detected_identity_and_key(self):
        table = TableReference("dbo", "Campania_Example")
        columns = [
            self.column("ID", "int", identity=True),
            self.column("campania", "nvarchar", max_length=300),
            self.column("publisher", "nvarchar", max_length=40),
            self.column("num_campania", "int", nullable=True),
        ]
        form, update = build_dynamic_configs(
            table,
            columns,
            ["ID"],
            {},
            {"enabled": True},
            {"key_fields_by_table": {}, "field_overrides": {}},
        )
        self.assertEqual(form["identity_column"], "ID")
        self.assertEqual(
            [field["name"] for field in form["fields"]],
            ["campania", "publisher", "num_campania"],
        )
        self.assertTrue(update["enabled"])
        self.assertEqual(update["key_fields"], ["ID"])

    def test_update_is_disabled_without_a_unique_key(self):
        form, update = build_dynamic_configs(
            TableReference("dbo", "SinClave"),
            [self.column("Nombre", "nvarchar", max_length=100)],
            [],
            {},
            {"enabled": True},
            {"key_fields_by_table": {}, "field_overrides": {}},
        )
        self.assertEqual(form["table"], "SinClave")
        self.assertFalse(update["enabled"])

    def test_non_unique_mode_is_enabled_when_configured(self):
        _form, update = build_dynamic_configs(
            TableReference("dbo", "Campanias"),
            [
                self.column("campania", "nvarchar", max_length=200),
                self.column("publisher", "nvarchar", max_length=40),
                self.column("num_campania", "int", nullable=True),
            ],
            [],
            {},
            {"enabled": True, "allow_non_unique_updates": True},
            {"key_fields_by_table": {}, "field_overrides": {}},
        )

        self.assertTrue(update["enabled"])
        self.assertTrue(update["non_unique_mode"])
        self.assertEqual(update["key_fields"], [])
        self.assertEqual(
            update["match_fields"], ["campania", "publisher", "num_campania"]
        )

    def test_default_columns_are_omitted_by_default(self):
        form, _update = build_dynamic_configs(
            TableReference("dbo", "Eventos"),
            [
                self.column("Nombre", "nvarchar", max_length=100),
                self.column("Creado", "datetime2", has_default=True),
            ],
            [],
            {},
            {"enabled": False},
            {
                "include_default_columns": False,
                "key_fields_by_table": {},
                "field_overrides": {},
            },
        )
        self.assertEqual([field["name"] for field in form["fields"]], ["Nombre"])

    def test_manual_key_enables_update_configuration(self):
        catalog = SQLServerCatalog({}, {"key_fields_by_table": {}, "field_overrides": {}})
        columns = [self.column("Codigo", "nvarchar", max_length=40)]
        catalog.get_columns = MagicMock(return_value=columns)
        catalog.get_key_fields = MagicMock(return_value=[])

        _form, update, _columns = catalog.build_configs(
            TableReference("dbo", "SinClave"),
            {},
            {"enabled": True},
            override_keys=["Codigo"],
        )

        self.assertTrue(update["enabled"])
        self.assertEqual(update["key_fields"], ["Codigo"])

    def test_manual_key_is_checked_for_duplicates(self):
        catalog = SQLServerCatalog({}, {})
        columns = [self.column("Codigo", "nvarchar", max_length=40)]
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value
        cursor.fetchone.return_value = None
        catalog._connect = MagicMock(return_value=connection)

        unique = catalog.validate_unique_key(
            TableReference("dbo", "Productos"), ["Codigo"], columns
        )

        self.assertTrue(unique)
        sql = cursor.execute.call_args.args[0]
        self.assertIn("FROM [dbo].[Productos]", sql)
        self.assertIn("GROUP BY [Codigo]", sql)
        self.assertIn("HAVING COUNT_BIG(*) > 1", sql)

    def test_manual_key_with_duplicates_is_rejected(self):
        catalog = SQLServerCatalog({}, {})
        columns = [self.column("Codigo", "nvarchar", max_length=40)]
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value
        cursor.fetchone.return_value = (1,)
        catalog._connect = MagicMock(return_value=connection)

        unique = catalog.validate_unique_key(
            TableReference("dbo", "Productos"), ["Codigo"], columns
        )

        self.assertFalse(unique)


if __name__ == "__main__":
    unittest.main()
