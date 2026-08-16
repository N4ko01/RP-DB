import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import ValidationError
from excel_import import ExcelImportService


class FakeWorksheet:
    def __init__(self, rows, title="Datos"):
        self.rows = rows
        self.title = title

    def iter_rows(self, values_only=False):
        self.values_only = values_only
        return iter(self.rows)


class FakeWorkbook:
    def __init__(self, rows):
        self.active = FakeWorksheet(rows)
        self.sheetnames = ["Datos"]
        self.closed = False

    def __getitem__(self, name):
        if name != "Datos":
            raise KeyError(name)
        return self.active

    def close(self):
        self.closed = True


class ExcelImportTests(unittest.TestCase):
    def setUp(self):
        self.fields = [
            {"name": "Nombre", "type": "str", "required": True},
            {"name": "Edad", "type": "int", "required": False},
        ]
        self.config = {
            "allowed_extensions": [".xlsx"],
            "sheet_name": None,
            "header_row": 1,
            "require_all_headers": True,
            "ignore_extra_columns": True,
            "column_mapping": {},
            "preview_rows": 2,
            "max_rows": 100,
            "batch_size": 50,
        }

    def load_fake(self, rows, config=None):
        service = ExcelImportService(self.fields, config or self.config)
        workbook = FakeWorkbook(rows)
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as temporary:
            with patch("excel_import.load_workbook", return_value=workbook):
                result = service.load(temporary.name)
        self.assertTrue(workbook.closed)
        return result

    def test_valid_excel_is_prepared_and_blank_rows_are_skipped(self):
        result = self.load_fake(
            [
                ("Nombre", "Edad", "Columna extra"),
                ("Ana", 20, "ignorada"),
                (None, None, None),
                ("Luis", 30.0, "ignorada"),
            ]
        )
        self.assertEqual(result.sheet_name, "Datos")
        self.assertEqual(result.row_count, 2)
        self.assertEqual(result.prepared_rows, [["Ana", 20], ["Luis", 30]])
        self.assertEqual(result.source_row_numbers, [2, 4])

    def test_missing_required_header_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "Faltan cabeceras"):
            self.load_fake([("Nombre",), ("Ana",)])

    def test_invalid_cell_reports_excel_row(self):
        with self.assertRaisesRegex(ValidationError, "Fila 2 del Excel"):
            self.load_fake([("Nombre", "Edad"), ("Ana", "no-es-entero")])

    def test_column_mapping_is_supported(self):
        config = {**self.config, "column_mapping": {"Persona": "Nombre"}}
        result = self.load_fake(
            [("Persona", "Edad"), ("Ana", 20)],
            config=config,
        )
        self.assertEqual(result.prepared_rows, [["Ana", 20]])

    def test_wrong_extension_is_rejected_before_opening(self):
        service = ExcelImportService(self.fields, self.config)
        with tempfile.NamedTemporaryFile(suffix=".csv") as temporary:
            with self.assertRaisesRegex(ValidationError, "Formato no permitido"):
                service.load(temporary.name)


if __name__ == "__main__":
    unittest.main()
