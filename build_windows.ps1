param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = (Get-Command python).Source
}

if (-not $env:LIBARCHIVE) {
    $ArchiveInt = Join-Path $env:SystemRoot "System32\archiveint.dll"
    if (Test-Path $ArchiveInt) {
        $env:LIBARCHIVE = $ArchiveInt
    }
}

& $Python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller is not installed. Run: & `"$Python`" -m pip install -r requirements-build.txt"
    exit 1
}

$Args = @("--noconfirm")
if ($Clean) {
    $Args += "--clean"
}
$Args += "MultiPaneCommander.spec"

$BuildOriginalPath = $env:PATH
try {
    # Third-party tool directories can contain incompatible DLLs (notably ICU).
    # Let PyInstaller hooks find package DLLs and Windows supply system DLLs.
    $env:PATH = @(
        (Split-Path -Parent $Python),
        (Join-Path $env:SystemRoot "System32"),
        $env:SystemRoot
    ) -join [IO.Path]::PathSeparator
    & $Python -m PyInstaller @Args
    $BuildExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $BuildOriginalPath
}
if ($BuildExitCode -ne 0) {
    exit $BuildExitCode
}

Write-Host ""
Write-Host "Built executable:"
Write-Host "  $ProjectRoot\dist\MultiPaneCommander\MultiPaneCommander.exe"
