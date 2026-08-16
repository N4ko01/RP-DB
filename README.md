# SQL Record Manager

Aplicación de escritorio para administrar registros de SQL Server y PostgreSQL
sin necesidad de escribir consultas SQL manualmente. Esta Aplicación es una ayuda para las automatizaciones de insercion de datos , edición  , deletes controlados y carga masiva de información con muchos registros que se necesitan en corto tiempo .

## ¿Qué permite hacer?

- Conectarse a SQL Server o PostgreSQL.
- Detectar tablas, columnas y claves disponibles.
- Insertar registros manualmente.
- Insertar múltiples filas desde Excel.
- Buscar y actualizar registros.
- Buscar y eliminar registros con confirmación.
- Consultar el historial de operaciones.

## Instalación para usuarios finales

La aplicación se distribuye mediante un instalador de Windows publicado en
**GitHub Releases**. El usuario no necesita instalar Python ni las librerías
del proyecto.

Para instalarla:

1. Abre la sección **Releases** del repositorio.
2. Descarga `SQLRecordManager-Setup-1.0.0.exe` o la versión más reciente.
3. Ejecuta el instalador.
4. Elige la carpeta de instalación.
5. Decide si deseas crear un acceso directo en el escritorio.
6. Presiona **Install**.
7. Abre SQL Record Manager desde el menú Inicio o el acceso directo.

## Requisitos externos

El instalador no incluye los servidores de base de datos ni todos los drivers
del sistema.

### SQL Server

El equipo debe tener un driver ODBC compatible con SQL Server. La aplicación
detecta automáticamente los drivers instalados, incluyendo las familias 11,
13, 17, 18 y posteriores.

Descarga oficial:

[Microsoft ODBC Driver for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

### PostgreSQL

La aplicación incluye el conector Python para PostgreSQL, pero necesita acceso
a un servidor PostgreSQL existente, ya sea en el mismo equipo o en la red.

Descargas oficiales:

[PostgreSQL para Windows](https://www.postgresql.org/download/windows/)

## Configuración de conexión

Al abrir la aplicación:

1. Selecciona **SQL Server** o **PostgreSQL**.
2. Escribe el servidor y la base de datos.
3. Completa el usuario y la contraseña cuando corresponda.
4. Para SQL Server, selecciona el driver ODBC.
5. Para PostgreSQL, utiliza normalmente el puerto `5432`.
6. Presiona **Conectar y cargar tablas**.
7. Selecciona una tabla y presiona **Usar tabla seleccionada**.

Las credenciales se guardan mediante el almacén seguro del sistema. No deben
escribirse en el código ni compartirse por correo o chat.

## Operaciones principales

### Insertar

Completa los campos obligatorios y presiona **Insertar registro**. Los campos
autogenerados, como `IDENTITY` o `serial`, no se solicitan manualmente.

### Importar Excel

Utiliza archivos `.xlsx` o `.xlsm` con cabeceras compatibles con las columnas de
la tabla. La aplicación muestra una vista previa y ejecuta la carga por lotes.

### Actualizar

Busca una fila, selecciónala, modifica sus valores y confirma la actualización.
Cuando existe una clave primaria o única, se exige que solo se modifique una
fila.

### Eliminar

Busca y selecciona la fila en **Buscar / eliminar**. Revisa el resultado y
confirma la advertencia. Delete es una operación permanente.

### SQL / Logs

Permite revisar las operaciones realizadas, las filas afectadas, el estado de
la transacción y el SQL parametrizado. Los valores reales de las filas no se
guardan en el log.

## Licencia

Este proyecto se distribuye bajo la licencia [MIT](LICENSE).
