"""Fábricas de proveedores para mantener la GUI independiente del motor SQL."""

from __future__ import annotations

from typing import Any, Mapping

from catalog import SQLServerCatalog
from database import ConfigurationError, SQLServerRepository
from postgresql import PostgreSQLCatalog, PostgreSQLRepository


def normalize_provider(config: Mapping[str, Any]) -> str:
    value = str(config.get("provider", "sqlserver")).strip().casefold()
    aliases = {
        "sql server": "sqlserver", "mssql": "sqlserver", "sqlserver": "sqlserver",
        "postgres": "postgresql", "postgresql": "postgresql", "pgsql": "postgresql",
    }
    if value not in aliases:
        raise ConfigurationError(f"Motor de base de datos no compatible: {value!r}.")
    return aliases[value]


def create_repository(
    db_config: Mapping[str, Any], form_config: Mapping[str, Any],
    update_config: Mapping[str, Any] | None = None,
    operation_logger: Any | None = None,
) -> SQLServerRepository:
    repository_class = (
        PostgreSQLRepository
        if normalize_provider(db_config) == "postgresql"
        else SQLServerRepository
    )
    return repository_class(db_config, form_config, update_config, operation_logger)


def create_catalog(db_config: Mapping[str, Any], selector_config: Mapping[str, Any]):
    catalog_class = (
        PostgreSQLCatalog
        if normalize_provider(db_config) == "postgresql"
        else SQLServerCatalog
    )
    return catalog_class(db_config, selector_config)


def provider_display_name(config: Mapping[str, Any]) -> str:
    return "PostgreSQL" if normalize_provider(config) == "postgresql" else "SQL Server"
