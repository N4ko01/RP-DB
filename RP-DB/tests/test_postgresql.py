import unittest

from database import ConfigurationError
from postgresql import (
    PostgreSQLRepository,
    build_postgres_connection_parameters,
    quote_postgres_identifier,
)
from providers import create_repository


class PostgreSQLLogicTests(unittest.TestCase):
    @staticmethod
    def repository():
        return PostgreSQLRepository(
            {
                "provider": "postgresql",
                "server": "localhost",
                "database": "demo",
                "username": "postgres",
                "password": "secret",
            },
            {
                "schema": "public",
                "table": "clientes",
                "identity_column": "id",
                "fields": [{"name": "nombre", "type": "str"}],
            },
            {
                "enabled": True,
                "key_fields": ["id"],
                "searchable_fields": "*",
                "result_fields": "*",
                "editable_fields": "*",
                "max_results": 200,
            },
        )

    def test_identifier_uses_postgresql_quotes(self):
        self.assertEqual(quote_postgres_identifier('a"b'), '"a""b"')
        with self.assertRaises(ConfigurationError):
            quote_postgres_identifier("")

    def test_connection_parameters_include_default_port(self):
        result = build_postgres_connection_parameters(
            {
                "server": "localhost", "database": "demo",
                "username": "postgres", "password": "secret",
            }
        )
        self.assertEqual(result["port"], 5432)
        self.assertNotIn("driver", result)

    def test_postgres_statements_use_native_placeholders(self):
        repo = self.repository()
        self.assertEqual(
            repo.build_insert_statement(),
            'INSERT INTO "public"."clientes" ("nombre") VALUES (%s) RETURNING "id";',
        )
        search = repo.build_search_statement(
            "nombre", "contains", ["id", "nombre"], ["nombre"]
        )
        self.assertIn('CAST("nombre" AS TEXT) LIKE %s', search)
        self.assertTrue(search.endswith("LIMIT 200;"))

    def test_provider_factory_selects_postgresql(self):
        repo = create_repository(
            {"provider": "postgresql", "server": "x", "database": "x", "username": "x"},
            {"schema": "public", "table": "t", "fields": [{"name": "name"}]},
        )
        self.assertIsInstance(repo, PostgreSQLRepository)


if __name__ == "__main__":
    unittest.main()
