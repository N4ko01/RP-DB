import json
import tempfile
import unittest
from pathlib import Path

from credential_store import CredentialProfileStore


class FakeKeyring:
    def __init__(self):
        self.passwords = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        self.passwords.pop((service, username), None)


class CredentialStoreTests(unittest.TestCase):
    def test_password_is_not_written_to_json_and_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            backend = FakeKeyring()
            store = CredentialProfileStore(path=path, backend=backend)
            config = {
                "server": "sql.example.local",
                "database": "Analytics",
                "driver": "ODBC Driver 17 for SQL Server",
                "trusted_connection": False,
                "username": "analista",
                "password": "clave-secreta",
                "trust_server_certificate": True,
                "connection_timeout": 8,
                "update_keys_by_table": {
                    "dbo.Campania_Example": ["campania", "publisher"]
                },
            }

            store.save(config, "dbo.Campania_Example")

            raw_file = path.read_text(encoding="utf-8")
            self.assertNotIn("clave-secreta", raw_file)
            self.assertNotIn('"password"', raw_file)
            loaded = store.load({})
            self.assertEqual(loaded["password"], "clave-secreta")
            self.assertEqual(loaded["last_table"], "dbo.Campania_Example")
            self.assertEqual(
                loaded["update_keys_by_table"]["dbo.Campania_Example"],
                ["campania", "publisher"],
            )

    def test_new_credentials_replace_previous_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            backend = FakeKeyring()
            store = CredentialProfileStore(path=path, backend=backend)
            first = {
                "server": "server-one",
                "database": "db-one",
                "trusted_connection": False,
                "username": "user-one",
                "password": "password-one",
            }
            second = {
                "server": "server-two",
                "database": "db-two",
                "trusted_connection": False,
                "username": "user-two",
                "password": "password-two",
            }
            store.save(first)
            store.save(second)

            loaded = store.load({})
            self.assertEqual(loaded["server"], "server-two")
            self.assertEqual(loaded["username"], "user-two")
            self.assertEqual(loaded["password"], "password-two")
            self.assertNotIn("password-one", json.dumps(loaded))

    def test_windows_authentication_removes_saved_password(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeKeyring()
            store = CredentialProfileStore(
                path=Path(directory) / "profile.json", backend=backend
            )
            store.save(
                {
                    "server": "server",
                    "database": "db",
                    "trusted_connection": False,
                    "username": "user",
                    "password": "secret",
                }
            )
            store.save(
                {
                    "server": "server",
                    "database": "db",
                    "trusted_connection": True,
                    "username": "",
                    "password": "",
                }
            )
            self.assertEqual(store.load({})["password"], "")


if __name__ == "__main__":
    unittest.main()
