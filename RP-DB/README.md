# Administrador de datos para SQL Server y PostgreSQL

Aplicación de escritorio en Python/Tkinter que se conecta a SQL Server o PostgreSQL, muestra
las tablas disponibles y genera el formulario a partir de sus metadatos.
Incluye inserción manual, búsqueda, actualización y eliminación segura,
inserción masiva desde Excel, progreso por lotes y un visor de SQL/logs. Todas
las operaciones usan consultas parametrizadas.

## Estructura

- `config.py`: conexión, permisos de tablas, personalizaciones y opciones.
- `catalog.py`: descubre tablas, columnas, tipos, IDENTITY y claves.
- `database.py`: conexión, validación, búsqueda, inserción y actualización.
- `postgresql.py`: dialecto, conexión y catálogo específicos de PostgreSQL.
- `providers.py`: selecciona la implementación correspondiente a cada motor.
- `excel_import.py`: lectura y validación del Excel; no contiene SQL.
- `operation_log.py`: historial de operaciones sin valores sensibles.
- `credential_store.py`: perfil local y contraseña en el almacén seguro.
- `gui.py`: interfaz gráfica; no contiene SQL.
- `app.py`: inicia la aplicación.
- `crear_tabla_ejemplo.sql`: tabla con la que funciona la configuración inicial.
- `tests/`: pruebas de la lógica sin conectarse a SQL Server.

## 1. Requisitos

- Windows con Python 3.10 o superior.
- SQL Server o PostgreSQL accesible desde el equipo.
- Para SQL Server, un driver ODBC compatible (11, 13, 17, 18 o posterior).
- Para PostgreSQL se usa `psycopg`, instalado desde `requirements.txt`.

En una terminal abierta dentro de la carpeta del proyecto:

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## 2. Conectarse desde la interfaz

Al abrir `app.py`, la primera opción del menú es **Conexión**. Allí puedes
ingresar:

- motor, servidor e instancia o puerto;
- base de datos;
- autenticación de SQL Server o Windows;
- usuario y contraseña cuando corresponda;
- controlador ODBC y confianza en el certificado.

Presiona **Conectar y cargar tablas**, selecciona una tabla y luego **Usar tabla
seleccionada**. Las páginas Insertar, Buscar/actualizar, Excel y SQL/Logs se
crean dentro de la misma ventana.

Si **Recordar esta conexión** está marcado, los nuevos datos reemplazan el
perfil anterior. Servidor, base, usuario, controlador y última tabla se guardan
en el perfil local de la aplicación. La contraseña nunca se escribe en ese
archivo ni en `config.py`: se guarda mediante `keyring` en el Administrador de
credenciales de Windows. **Olvidar datos guardados** elimina ambos.

`DB_CONFIG` en `config.py` contiene solamente los valores iniciales que se
mostrarán cuando todavía no exista un perfil:

```python
DB_CONFIG = {
    "provider": "sqlserver",  # o "postgresql"
    "server": r"SERVIDOR\INSTANCIA",
    "database": "MiBase",
    "driver": "ODBC Driver 18 for SQL Server",
    "driver_candidates": [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
    ],
    "trusted_connection": True,
    "username": "",
    "password": "",
    "trust_server_certificate": True,
    "connection_timeout": 8,
}
```

La aplicación comprueba los drivers SQL Server instalados y elige el primero
compatible, incluyendo las familias 11, 13, 17, 18 y posteriores. Para ver los
disponibles en tu equipo:

```powershell
python -c "import pyodbc; print(pyodbc.drivers())"
```

El error `IM002` indica que el nombre configurado no corresponde a un driver
ODBC instalado. Puedes corregir `driver`, instalar Microsoft ODBC Driver 18/17
o dejar ambos nombres en `driver_candidates`.

Las variables `SQLSERVER_HOST`, `SQLSERVER_DATABASE`, `SQLSERVER_DRIVER`,
`SQLSERVER_TRUSTED` y `SQLSERVER_TRUST_CERTIFICATE` también sirven como valores
iniciales. Después de recordar una conexión, prevalece el perfil guardado.

## 3. Seleccionar una tabla automáticamente

La selección ocurre en la página **Conexión** del mismo programa:

1. Se conecta usando los datos escritos o recordados.
2. Consulta todas las tablas visibles para ese usuario.
3. Permite escoger `esquema.tabla`.
4. Detecta columnas, tipos, nulabilidad, `IDENTITY`, campos calculados, valores
   predeterminados y la clave primaria o primer índice `UNIQUE` utilizable.
5. Genera las pantallas de inserción, actualización y Excel.

Los formularios muestran el tipo SQL real junto al nombre visible, por ejemplo
`Campania (NVARCHAR(150))`, `Precio (DECIMAL(12,2))` o `Stock (INT)`.

Puedes mostrar todo o limitar las tablas permitidas:

```python
TABLE_SELECTOR_CONFIG = {
    "allowed_schemas": "*",  # o ["dbo", "ventas"]
    "allowed_tables": "*",   # o ["dbo.Clientes", "dbo.Campania_Example"]
    "excluded_schemas": ["sys", "INFORMATION_SCHEMA"],
    "excluded_tables": [],
    "include_default_columns": False,
    "key_fields_by_table": {},
    "field_overrides": {},
}
```

Las columnas `IDENTITY`, calculadas y `rowversion` no se incluyen en el INSERT.
Con `include_default_columns: False`, tampoco se piden columnas que SQL Server
puede completar mediante `DEFAULT`.

Si una tabla no tiene clave primaria ni índice `UNIQUE`, **Buscar / actualizar**
se habilita igualmente. La aplicación compara todos los valores originales
compatibles, muestra cuántas filas idénticas existen y permite escribir cuántas
de ese total deben modificarse.

También puedes definir la combinación directamente en el código:

```python
"key_fields_by_table": {
    "dbo.Campania_Example": ["campania", "publisher", "num_campania"],
}
```

### Personalizar campos detectados

La detección automática puede complementarse con etiquetas y widgets:

```python
"field_overrides": {
    "dbo.Clientes": {
        "TipoCliente": {
            "label": "Tipo de cliente",
            "widget": "combobox",
            "options": ["Persona", "Empresa"],
        },
    },
}
```

### Configuración base del formulario

`FORM_CONFIG` conserva una configuración base y permite ejecutar las pruebas.
Cuando seleccionas una tabla desde la interfaz, sus campos se reemplazan por
los metadatos detectados automáticamente:

```python
FORM_CONFIG = {
    "window_title": "Registro de productos",
    "schema": "dbo",
    "table": "Productos",
    "identity_column": "ProductoID",  # usa None si no necesitas devolver un ID
    "fields": [
        {
            "name": "NombreProducto",  # nombre exacto en SQL Server
            "label": "Producto",       # texto visible en la GUI
            "type": "str",
            "required": True,
            "max_length": 100,
        },
        {
            "name": "Precio",
            "label": "Precio",
            "type": "decimal",
            "required": True,
        },
        {
            "name": "Stock",
            "label": "Stock",
            "type": "int",
            "required": True,
        },
        {
            "name": "Categoria",
            "label": "Categoría",
            "type": "str",
            "required": True,
            "widget": "combobox",
            "options": ["A", "B", "C"],
        },
        {
            "name": "Activo",
            "label": "Activo",
            "type": "bool",
            "required": True,
            "widget": "checkbox",
            "default": True,
        },
    ],
}
```

Tipos disponibles: `str`, `int`, `float`, `decimal`, `bool`, `date`, `datetime`
y `time`. Widgets disponibles: `entry`, `multiline`, `checkbox` y `combobox`.

Formatos aceptados:

- `date`: `AAAA-MM-DD`
- `datetime`: `AAAA-MM-DD HH:MM:SS`
- `time`: `HH:MM:SS`
- `decimal` y `float`: aceptan punto o coma decimal
- un campo opcional vacío se envía como `NULL`

No incluyas en `fields` una columna `IDENTITY`, calculada o con valor automático
que SQL Server deba completar. La opción `identity_column` solamente devuelve el
ID creado mediante `OUTPUT INSERTED`; no lo agrega al conjunto de valores.

## 4. Configurar búsqueda y actualización

En `config.py`, configura `UPDATE_CONFIG`:

```python
UPDATE_CONFIG = {
    "enabled": True,
    "allow_non_unique_updates": True,
    "max_rows_per_update": 100000,
    "key_fields": ["ProductoID"],
    "searchable_fields": "*",
    "result_fields": "*",
    "editable_fields": "*",
    "default_search_mode": "contains",
    "max_results": 200,
}
```

Opciones:

- `enabled`: muestra u oculta la pestaña de actualización.
- `allow_non_unique_updates`: habilita el modo por cantidad cuando la tabla no
  tiene una clave declarada.
- `max_rows_per_update`: límite de seguridad de una actualización confirmada.
- `key_fields`: columna o columnas que identifican una sola fila. Usa la clave
  primaria siempre que exista.
- `searchable_fields`: con `"*"`, la GUI lee todas las columnas reales y permite
  buscar por cualquiera. También puede ser una lista, por ejemplo
  `["NombreProducto", "Categoria"]`.
- `result_fields`: columnas visibles en los resultados. `"*"` muestra todas.
- `editable_fields`: campos modificables. `"*"` usa todos los campos definidos
  en `FORM_CONFIG["fields"]`.
- `default_search_mode`: `"contains"` para coincidencia parcial o `"exact"`.
- `max_results`: máximo de filas devueltas por búsqueda.

`identity_column` y `key_fields` cumplen funciones diferentes. La primera solo
permite mostrar el ID producido por un `INSERT`; la segunda identifica la fila
que será actualizada.

### Tabla sin IDENTITY o clave primaria

No es obligatorio modificar la tabla. Con el modo no único habilitado:

```python
FORM_CONFIG = {
    "schema": "dbo",
    "table": "Campania_Example",
    "identity_column": None,
    "fields": [
        {"name": "campania", "label": "Campaña", "type": "str", "required": True},
        {"name": "publisher", "label": "Publisher", "type": "str", "required": True},
        {"name": "num_campania", "label": "Número", "type": "int", "required": False},
    ],
}

UPDATE_CONFIG = {
    "enabled": True,
    "allow_non_unique_updates": True,
    "max_rows_per_update": 100000,
    "searchable_fields": "*",
    "result_fields": "*",
    "editable_fields": "*",
    "default_search_mode": "contains",
    "max_results": 200,
}
```

Al seleccionar un resultado, la interfaz vuelve a contar las filas con todos
los valores originales. Si encuentra 20 filas idénticas, permite elegir una
cantidad entre 1 y 20. SQL Server ejecuta `UPDATE TOP (cantidad)` dentro de una
transacción y la aplicación verifica `@@ROWCOUNT`. Si el total afectado no
coincide con lo solicitado, hace `rollback`.

La columna **N°** de los resultados es solamente visual. Ayuda a navegar la
tabla, pero no se utiliza como identificador SQL.

## 5. Configurar la inserción masiva desde Excel

La tercera pestaña se controla desde `BULK_INSERT_CONFIG` en `config.py`:

```python
BULK_INSERT_CONFIG = {
    "enabled": True,
    "allowed_extensions": [".xlsx", ".xlsm"],
    "sheet_name": None,          # None usa la hoja activa
    "header_row": 1,             # fila que contiene las cabeceras
    "require_all_headers": True,
    "ignore_extra_columns": True,
    "column_mapping": {},        # cabecera Excel -> campo SQL
    "preview_rows": 20,
    "max_rows": 100000,
    "batch_size": 500,
}
```

Reglas del archivo:

- La página muestra un panel con cada nombre de cabecera exacto, su tipo SQL y
  si es obligatorio u opcional. La vista previa repite el tipo en los títulos.

- Las cabeceras deben usar los valores `name` de `FORM_CONFIG["fields"]`; no
  los valores `label` mostrados en pantalla. La comparación no distingue
  mayúsculas de minúsculas.
- No agregues la columna `IDENTITY`. Si aparece como columna adicional, se
  ignora cuando `ignore_extra_columns` es `True`.
- Las filas completamente vacías se omiten.
- Se aceptan `.xlsx` y `.xlsm`. El formato antiguo `.xls` no está habilitado.
- Las fechas pueden ser fechas reales de Excel o texto `AAAA-MM-DD`; para fecha
  y hora también se acepta `AAAA-MM-DD HH:MM:SS`.
- Si `require_all_headers` es `False`, solo se exigen los campos con
  `required: True`; los campos opcionales ausentes se envían como `NULL`.

Si las cabeceras del Excel tienen nombres diferentes, puedes mapearlas a los
campos SQL:

```python
"column_mapping": {
    "Campaña Excel": "campania",
    "Medio": "publisher",
}
```

El programa valida todas las filas antes de habilitar la inserción y muestra
una vista previa. La carga se ejecuta por lotes dentro de una sola transacción:
si SQL Server rechaza una fila, se hace `rollback` y no queda una carga parcial.

Con los valores predeterminados admite hasta `100000` filas y las divide en
lotes de `500`. Por ejemplo, un Excel de `10000` filas se envía en `20` lotes.
La barra de progreso muestra el lote y las filas enviadas. El `commit` ocurre
solo al completar todos los lotes.

## 6. SQL y logs

La pestaña **SQL / Logs** muestra la estructura parametrizada que utiliza la
tabla seleccionada. Para `Campania_Example` sería:

```sql
INSERT INTO [dbo].[Campania_Example]
([campania], [publisher], [num_campania])
VALUES (?, ?, ?);
```

También registra fecha, tabla, operación, resultado, cantidad de filas, lotes,
duración, archivo de origen y SQL. No registra contraseñas ni los valores de
las filas. Se configura así:

```python
LOG_CONFIG = {
    "enabled": True,
    "file_path": "logs/operations.log",
    "max_bytes": 2_000_000,
}
```

El visor se actualiza al abrir la pestaña o presionar **Actualizar**. Cuando el
archivo alcanza el tamaño máximo, se conserva una copia `.log.1` y comienza un
archivo nuevo.

## 7. Ejecutar

```powershell
python app.py
```

En **Conexión**, ingresa o revisa las credenciales recordadas, carga las tablas
y selecciona una. Después, en **Insertar**, llena el formulario y selecciona
**Insertar registro**. Puedes regresar a **Conexión** para usar otro servidor,
usuario, base de datos o tabla sin cerrar el programa.

En **Buscar / actualizar**:

1. Las columnas se cargan automáticamente; usa **Actualizar columnas** si la
   tabla cambió después de abrir el programa.
2. Elige la columna, el modo y el valor.
3. Presiona **Buscar** o **Mostrar todos**.
4. Selecciona una fila y presiona **Editar seleccionado** (también puedes hacer
   doble clic).
5. Modifica el formulario inferior y presiona **Actualizar registro**.

En **Insertar desde Excel**:

1. Presiona **Seleccionar Excel**.
2. Espera la validación de cabeceras, tipos y filas.
3. Revisa la vista previa y la cantidad total encontrada.
4. Presiona **Insertar filas validadas** y confirma la operación.

En **SQL / Logs** puedes copiar el INSERT generado y consultar el resultado de
las operaciones anteriores.

## 8. Personalizar la apariencia

La interfaz utiliza una barra superior, menú lateral y tarjetas minimalistas.
El menú se contrae automáticamente cuando la ventana tiene poco ancho y los
formularios colocan cada etiqueta encima de su campo en tamaños reducidos.

Puedes cambiar la apariencia desde `UI_CONFIG` en `config.py`, sin modificar
`gui.py`:

```python
UI_CONFIG = {
"app_name": "SQL Record Manager",
"logo_path": "",
    "logo_opacity": 0.60,
    "logo_width": 142,
    "window_icon_path": "assets/app_window_icon.png",
    "window_icon_ico": "assets/app_window_icon.ico",
"taskbar_icon_ico": "assets/app_window_icon.ico",
"windows_app_id": "SQLRecordManager",
    "window_size": "1180x780",
    "min_width": 760,
    "min_height": 600,
    "sidebar_width": 224,
    "sidebar_collapsed_width": 68,
    "responsive_breakpoint": 900,
    "resize_debounce_ms": 110,
    "form_resize_debounce_ms": 90,
    "form_responsive_breakpoint": 600,
    "resize_width_tolerance": 8,
    "font_family": "Segoe UI",
    "colors": {
        "background": "#0E0E10",
        "surface": "#171719",
        "topbar": "#050505",
        "sidebar": "#0A0A0B",
        "sidebar_active": "#303035",
        "primary": "#45454C",
        "text": "#F4F4F5",
        "muted": "#A1A1AA",
        "border": "#34343A",
    },
}
```

En Windows, `window_icon_ico` controla el icono pequeño de la ventana y
`taskbar_icon_ico` el icono grande mostrado por la aplicación en la barra de
tareas. En otros sistemas el gestor de ventanas puede utilizar un único icono.

Al abrir **Buscar / actualizar**, las columnas se leen automáticamente desde
SQL Server. El botón **Actualizar columnas** solo es necesario si la estructura
de la tabla cambió mientras la aplicación estaba abierta.

Los valores `resize_debounce_ms` y `form_resize_debounce_ms` evitan redibujar
todos los controles por cada píxel mientras arrastras la ventana. Valores entre
80 y 140 ms suelen ofrecer una respuesta fluida; reducirlos hace que la interfaz
reaccione antes, pero aumenta el trabajo de redibujado.

Para mejorar todavía más el rendimiento, la aplicación mantiene fuera del
administrador geométrico la página que no está visible. Durante el arrastre se
redimensiona solamente la ventana exterior; la barra, el menú y la página activa
se acomodan juntos al pausar. Esto evita que Tkinter reorganice simultáneamente
las pantallas de inserción, actualización e importación por cada píxel.

## Seguridad y transacciones

- Los valores se mandan mediante parámetros (`?` en SQL Server y `%s` en
  PostgreSQL); no se concatenan al SQL.
- La contraseña no se guarda en archivos ni en los logs; se almacena en el
  Administrador de credenciales de Windows mediante `keyring`.
- Esquema, tabla y columnas proceden del catálogo autorizado o de `config.py`;
  se delimitan con corchetes y cualquier corchete interno se escapa de forma
  segura. También se admiten nombres que contengan espacios.
- Cada inserción, actualización, eliminación o carga masiva hace `commit` solo si termina
  correctamente; ante un error hace `rollback`.
- Con una clave única se exige exactamente una fila. Sin clave, se bloquean las
  coincidencias originales y se exige exactamente la cantidad confirmada.
- El log muestra coincidencias originales, cantidad solicitada, filas afectadas,
  SQL parametrizado y resultado `COMMIT` o `ROLLBACK`.
- Después de una actualización correcta, la interfaz abre automáticamente
  **SQL / Logs** para mostrar el registro recién generado.
- Conviene otorgar al usuario únicamente acceso a los metadatos necesarios y
  permisos `SELECT`, `INSERT`, `UPDATE` y `DELETE` sobre las tablas autorizadas. También
  puedes restringirlas mediante `allowed_tables`.

## Ejecutar las pruebas

Desde la carpeta del proyecto:

```powershell
python -m unittest discover -s tests -v
```

Estas pruebas validan conversiones, detección de metadatos, persistencia segura
del perfil, cabeceras de Excel, campos obligatorios, logs, lotes y consultas
parametrizadas. No necesitan una base de datos activa.
