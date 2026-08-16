$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$project = Join-Path $root "RP-DB"
$spec = Join-Path $root "installer\SQLRecordManager.spec"

Set-Location $root

$pyinstallerCheck = & python -m PyInstaller --version 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller no está instalado. Ejecuta: python -m pip install pyinstaller"
}

if (Test-Path (Join-Path $root "build")) {
    Remove-Item -LiteralPath (Join-Path $root "build") -Recurse -Force
}
if (Test-Path (Join-Path $root "dist")) {
    Remove-Item -LiteralPath (Join-Path $root "dist") -Recurse -Force
}

python -m PyInstaller --noconfirm --clean $spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller no pudo generar la aplicación. Revisa el error anterior."
}

$output = Join-Path $root "dist\SQLRecordManager.exe"
if (-not (Test-Path $output)) {
    throw "PyInstaller terminó, pero no se encontró el ejecutable esperado."
}

Write-Host "Aplicación generada en: $output"
Write-Host "Siguiente paso: compilar installer\SQLRecordManager.iss con Inno Setup."
