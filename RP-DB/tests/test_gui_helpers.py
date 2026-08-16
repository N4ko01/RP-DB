import unittest

from gui import InsertFormApp, field_type_display


class GuiHelperTests(unittest.TestCase):
    def test_field_type_display_prefers_real_sql_type(self):
        self.assertEqual(
            field_type_display(
                {"name": "campania", "type": "str", "sql_type_display": "NVARCHAR(150)"}
            ),
            "NVARCHAR(150)",
        )

    def test_field_type_display_has_fallback_for_manual_config(self):
        self.assertEqual(field_type_display({"type": "int"}), "ENTERO")

    def test_window_size_is_parsed(self):
        self.assertEqual(InsertFormApp._parse_window_size("1180x780"), (1180, 780))

    def test_window_size_with_position_is_parsed(self):
        self.assertEqual(
            InsertFormApp._parse_window_size("900x600+40+30"),
            (900, 600),
        )

    def test_invalid_window_size_uses_safe_default(self):
        self.assertEqual(
            InsertFormApp._parse_window_size("valor-invalido"),
            (1180, 780),
        )


if __name__ == "__main__":
    unittest.main()
