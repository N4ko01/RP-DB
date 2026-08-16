# Arquitectura del proyecto

Este documento sirve como mapa rápido para quien empieza a trabajar en el
proyecto.

## Flujo principal

1. `app.py` carga configuración, credenciales y el registro de operaciones.
2. `providers.py` selecciona SQL Server o PostgreSQL.
3. La página de conexión usa el catálogo del proveedor para descubrir tablas,
   columnas y claves.
4. `catalog.py` transforma esos metadatos en campos que la GUI puede mostrar.
5. `database.py` contiene la lógica común y la implementación SQL Server.
6. `postgresql.py` adapta esa API al dialecto y conector de PostgreSQL.
7. `gui.py` muestra Insert, Update, Delete, Excel y Logs sin construir SQL.

## Responsabilidad de cada archivo

- `config.py`: valores iniciales y límites de seguridad.
- `credential_store.py`: perfil local y contraseña almacenada con `keyring`.
- `database.py`: validaciones, transacciones y repositorio SQL Server.
- `postgresql.py`: repositorio y catálogo PostgreSQL mediante `psycopg`.
- `providers.py`: fábricas para evitar condicionales de motor por toda la GUI.
- `catalog.py`: modelos de metadatos y conversión de tipos SQL a campos.
- `excel_import.py`: lectura y validación; no ejecuta SQL.
- `operation_log.py`: log sin valores sensibles.
- `gui.py`: componentes y páginas Tkinter.

## Regla para añadir otro motor

Implementa un repositorio y un catálogo con la misma API pública, regístralos
en `providers.py` y evita introducir sentencias SQL nuevas dentro de `gui.py`.

## Seguridad de Update y Delete

Con una clave primaria o única, la operación debe afectar exactamente una fila.
Cuando una tabla no tiene clave, se comparan los valores originales, se pide una
cantidad explícita y toda la operación se ejecuta dentro de una transacción. Un
resultado distinto del solicitado produce `ROLLBACK`.
