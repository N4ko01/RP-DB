# SQL Record Manager — Guía de usuario

Esta guía explica cómo utilizar la aplicación sin necesidad de conocer su
código fuente.

## ¿Qué hace el programa?

SQL Record Manager permite trabajar con tablas de SQL Server y PostgreSQL desde
una interfaz gráfica. Puedes:

- Conectarte a una base de datos.
- Elegir una tabla disponible.
- Insertar registros manualmente.
- Insertar muchas filas desde Excel.
- Buscar y actualizar registros.
- Buscar y eliminar registros con confirmación.
- Consultar el historial de operaciones realizadas.

![Flujo inicial](images/flujo-inicio.svg)

## 1. Instalación

Abre PowerShell dentro de la carpeta del proyecto y ejecuta:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Para SQL Server necesitas tener instalado un driver ODBC compatible. Para
PostgreSQL, la aplicación utiliza el conector incluido en `requirements.txt`.

## 2. Abrir la aplicación

Con el entorno virtual activo:

```powershell
python app.py
```

Se abrirá la pantalla **Conexión**.

## 3. Conectarse a una base de datos

En la pantalla de conexión:

1. Selecciona el motor: **SQL Server** o **PostgreSQL**.
2. Escribe el servidor o equipo donde está la base de datos.
3. Escribe el nombre de la base de datos.
4. Completa el usuario y la contraseña cuando corresponda.
5. En SQL Server, selecciona o escribe el driver ODBC disponible.
6. En PostgreSQL, indica el puerto; normalmente es `5432`.
7. Presiona **Conectar y cargar tablas**.

La aplicación mostrará las tablas visibles para el usuario conectado.

![Conexión y selección](images/flujo-inicio.svg)

### Recordar la conexión

La opción **Recordar esta conexión** guarda los datos generales del perfil. La
contraseña se almacena mediante el almacén seguro del sistema y no se escribe
en archivos de texto.

## 4. Elegir una tabla

Después de conectarte:

1. Abre la lista **Tabla de trabajo**.
2. Selecciona la tabla que deseas administrar.
3. Presiona **Usar tabla seleccionada**.

El programa lee automáticamente sus columnas, tipos de datos y claves. Con esa
información genera los formularios disponibles.

## 5. Insertar un registro

En **Insertar registro**:

1. Completa los campos obligatorios, marcados con `*`.
2. Revisa fechas, números y valores seleccionados.
3. Presiona **Insertar registro**.

Los campos `IDENTITY`, seriales o generados automáticamente no se solicitan al
usuario. Si la base de datos detecta un duplicado en una clave primaria o única,
rechazará la operación y conservará la información sin cambios.

## 6. Insertar desde Excel

La opción **Insertar desde Excel** permite cargar varias filas.

El archivo debe cumplir estas condiciones:

- Ser `.xlsx` o `.xlsm`.
- Tener una fila de cabeceras.
- Utilizar nombres de columnas compatibles con la tabla.
- Contener valores válidos para cada tipo de campo.

Pasos:

1. Presiona **Seleccionar archivo**.
2. Revisa la vista previa.
3. Comprueba que las columnas y filas sean correctas.
4. Presiona **Insertar filas**.

La inserción se realiza por lotes. Si ocurre un error, la operación completa se
revierte mediante `ROLLBACK`.

![Operaciones principales](images/operaciones.svg)

## 7. Buscar y actualizar

En **Buscar / actualizar**:

1. Selecciona la columna de búsqueda.
2. Elige **Contiene** o **Exacto**.
3. Escribe el valor.
4. Presiona **Buscar**.
5. Selecciona una fila y presiona **Editar seleccionado**.
6. Modifica los campos necesarios.
7. Presiona **Actualizar registro**.
8. Confirma la operación.

Cuando una tabla tiene una clave primaria o única, la aplicación exige que solo
se modifique un registro. En tablas sin clave única puede solicitarse una
cantidad concreta de filas coincidentes.

## 8. Buscar y eliminar

La pestaña **Buscar / eliminar** funciona de forma similar a Update:

1. Selecciona una columna.
2. Escribe el valor que deseas buscar.
3. Presiona **Buscar**.
4. Selecciona la fila correcta.
5. Presiona **Preparar eliminación**.
6. Revisa nuevamente el resultado.
7. Presiona **Eliminar seleccionado**.
8. Confirma la advertencia.

![Eliminación controlada](images/delete-seguro.svg)

La eliminación es permanente. Si la tabla no tiene una clave única, puedes
indicar cuántas coincidencias eliminar. La cantidad solicitada debe ser válida
y la aplicación cancela la operación si el motor devuelve un número diferente.

## 9. SQL / Logs

La página **SQL / Logs** muestra:

- La última actividad realizada.
- La tabla utilizada.
- La cantidad de filas afectadas.
- La duración de la operación.
- Si terminó con `COMMIT` o `ROLLBACK`.
- El SQL parametrizado utilizado.

Los valores reales enviados en las filas no se escriben en el log.

## 10. Errores frecuentes

### No se encuentra el driver de SQL Server

Instala un driver ODBC de SQL Server compatible y vuelve a abrir la aplicación.
También puedes escribir manualmente el nombre del driver en la pantalla de
conexión.

### No aparecen tablas

Comprueba que el usuario tenga permisos para consultar las tablas y que los
filtros de tablas permitidas no estén restringiendo el resultado.

### Falta una columna del Excel

Revisa que la cabecera del Excel coincida con el nombre de la columna esperada.

### La aplicación rechaza un valor numérico

Los campos `decimal` y `float` aceptan tanto punto como coma decimal, por
ejemplo `12.50` y `12,50`. Los campos enteros solo aceptan números sin decimales.

### Una actualización o eliminación no continúa

Puede que la tabla no tenga una clave única o que otra persona haya modificado
la fila después de tu búsqueda. Vuelve a buscar y verifica el registro.

## Recomendaciones de uso

- Verifica siempre la tabla activa antes de insertar, actualizar o eliminar.
- Utiliza una clave primaria o única para operaciones individuales.
- Haz una búsqueda antes de Delete y revisa la fila seleccionada.
- Concede al usuario solo los permisos necesarios.
- Prueba primero las operaciones en una base de datos de desarrollo.
- No compartas archivos de credenciales ni perfiles guardados.
