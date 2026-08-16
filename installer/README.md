# Construir el instalador de Windows

## Requisitos de desarrollo

- Windows.
- Python instalado.
- Dependencias del proyecto instaladas.
- PyInstaller: `python -m pip install pyinstaller`.
- Inno Setup para crear el archivo `Setup.exe`.

## Generar la aplicación

Desde PowerShell en la raíz del repositorio:

```powershell
python -m pip install -r RP-DB/requirements.txt
python -m pip install pyinstaller
Set-ExecutionPolicy -Scope Process Bypass
./build_windows.ps1
```

Esto genera la aplicación en `dist/SQLRecordManager.exe`.

## Generar el instalador

Abre `installer/SQLRecordManager.iss` con Inno Setup y presiona **Compile**.
El instalador resultante se guardará en:

```text
dist/installer/SQLRecordManager-Setup-1.0.0.exe
```

Ese archivo es el que debe subirse a una GitHub Release.

## Publicar una versión

```powershell
git add .
git commit -m "Preparar instalador de Windows"
git push origin main
git tag v1.0.0
git push origin v1.0.0
```

Después crea una Release en GitHub usando la etiqueta `v1.0.0` y adjunta el
archivo `SQLRecordManager-Setup-1.0.0.exe`.
