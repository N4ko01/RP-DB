import tempfile
import unittest
from pathlib import Path

from operation_log import OperationLogger


class OperationLogTests(unittest.TestCase):
    def test_log_contains_sql_summary_but_not_row_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.log"
            logger = OperationLogger(
                {"enabled": True, "file_path": str(path), "max_bytes": 100000}
            )
            logger.record(
                operation="INSERT MASIVO",
                schema="dbo",
                table="Campania_Example",
                sql="INSERT INTO [dbo].[Campania_Example] ([campania]) VALUES (?);",
                status="CORRECTO",
                rows=1200,
                batch_size=500,
                batches=3,
                duration_seconds=2.5,
                source_file="datos.xlsx",
                matched_rows=1500,
                requested_rows=1200,
                transaction="COMMIT",
            )
            content = logger.read_latest()
            self.assertIn("INSERT MASIVO", content)
            self.assertIn("Filas: 1200", content)
            self.assertIn("Cantidad de lotes: 3", content)
            self.assertIn("Coincidencias originales: 1500", content)
            self.assertIn("Cantidad solicitada: 1200", content)
            self.assertIn("Transacción: COMMIT", content)
            self.assertIn("VALUES (?)", content)
            self.assertNotIn("mi valor privado", content)


if __name__ == "__main__":
    unittest.main()
