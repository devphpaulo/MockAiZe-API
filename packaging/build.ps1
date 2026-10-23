param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepositoryRoot
try {
    & $Python -m PyInstaller --noconfirm --clean packaging/service.spec
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao empacotar serviço.' }
    & $Python -m PyInstaller --noconfirm --clean packaging/config.spec
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao empacotar configurador.' }
    $PayloadPath = Join-Path $RepositoryRoot 'build\payload'
    if (Test-Path -LiteralPath $PayloadPath) {
        $ResolvedPayload = (Resolve-Path -LiteralPath $PayloadPath).Path
        if ($ResolvedPayload -ne (Join-Path $RepositoryRoot 'build\payload')) { throw 'Destino inválido.' }
        Remove-Item -LiteralPath $ResolvedPayload -Recurse -Force
    }
    New-Item -Path $PayloadPath -ItemType Directory -Force | Out-Null
    Copy-Item -Path 'dist\MockAiZeApiService\*' -Destination $PayloadPath -Recurse
    Copy-Item -LiteralPath 'dist\MockAiZeApiConfig.exe' -Destination $PayloadPath
    & $Python packaging/collect_licenses.py (Join-Path $PayloadPath 'licenses')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao coletar licenças dos componentes.' }
    & $Python -m PyInstaller --noconfirm --clean packaging/setup.spec
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao empacotar setup.' }
    $SetupPath = Join-Path $RepositoryRoot 'dist\MockAiZe-API-Setup.exe'
    try {
        $SetupHash = (Get-FileHash -LiteralPath $SetupPath -Algorithm SHA256 -ErrorAction Stop).Hash
    } catch {
        throw 'O instalador final não está disponível. Confira o histórico do antivírus; não desative a proteção nem distribua artefatos incompletos.'
    }
    $ReleasePath = Join-Path $RepositoryRoot 'release'
    New-Item -Path $ReleasePath -ItemType Directory -Force | Out-Null
    Copy-Item -LiteralPath $SetupPath -Destination (Join-Path $ReleasePath 'MockAiZe-API-Setup.exe') -Force
    Write-Output "Instalador Windows: release\MockAiZe-API-Setup.exe"
    Write-Output "SHA-256: $SetupHash"
    # PKG is PyInstaller's temporary archive, never a distribution deliverable.
    foreach ($PkgRelative in @('build\service\MockAiZeApiService.pkg', 'build\config\MockAiZeApiConfig.pkg', 'build\setup\MockAiZe-API-Setup.pkg')) {
        $PkgPath = [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $PkgRelative))
        if (-not $PkgPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Intermediário fora do workspace.' }
        if (Test-Path -LiteralPath $PkgPath) { Remove-Item -LiteralPath $PkgPath -Force }
    }
} finally {
    Pop-Location
}
