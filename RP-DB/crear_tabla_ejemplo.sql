CREATE TABLE dbo.Clientes (
    ClienteID INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    Nombre NVARCHAR(150) NOT NULL,
    Documento NVARCHAR(20) NOT NULL,
    Edad INT NULL,
    Correo NVARCHAR(180) NULL,
    FechaRegistro DATE NOT NULL,
    Activo BIT NOT NULL,
    TipoCliente NVARCHAR(30) NOT NULL,
    Observacion NVARCHAR(500) NULL
);

