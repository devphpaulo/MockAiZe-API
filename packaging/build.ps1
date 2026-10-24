param([string]$Python = 'python', [string]$InnoCompiler = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepositoryRoot
try {
    if (-not $InnoCompiler) {
        $CompilerCandidates = @((Join-Path $RepositoryRoot 'build/tools/inno/ISCC.exe'),
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")
        $InnoCompiler = $CompilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $InnoCompiler) { throw 'Instale Inno Setup 6.7 ou informe -InnoCompiler com o caminho de ISCC.exe.' }
    $InnoCompiler = (Resolve-Path -LiteralPath $InnoCompiler).Path
    if (-not (Test-Path -LiteralPath 'src/mockaize_api/assets/mockaize.ico')) { throw 'Ícone aprovado ausente.' }
    & $Python packaging/freeze.py packaging/service.spec
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao empacotar o serviço.' }
    foreach ($Frontend in @('config', 'uninstall')) {
        & $InnoCompiler "/DRepositoryRoot=$RepositoryRoot" "packaging/inno/$Frontend.iss"
        if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar frontend nativo $Frontend." }
    }
    $PayloadPath = Join-Path $RepositoryRoot 'build/payload'
    if (Test-Path -LiteralPath $PayloadPath) {
        $ResolvedPayload = (Resolve-Path -LiteralPath $PayloadPath).Path
        if ($ResolvedPayload -ne [IO.Path]::GetFullPath($PayloadPath)) { throw 'Destino de payload inválido.' }
        Remove-Item -LiteralPath $ResolvedPayload -Recurse -Force
    }
    New-Item -Path $PayloadPath -ItemType Directory -Force | Out-Null
    Copy-Item -Path 'dist/MockAiZeApiService/*' -Destination $PayloadPath -Recurse
    Copy-Item -LiteralPath 'build/native/MockAiZeApiConfig.exe', 'build/native/MockAiZeApiUninstall.exe' -Destination $PayloadPath
    & $Python packaging/collect_licenses.py (Join-Path $PayloadPath 'licenses') (Join-Path (Split-Path $InnoCompiler) 'license.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao coletar as licenças dos componentes.' }
    New-Item -Path 'release' -ItemType Directory -Force | Out-Null
    & $InnoCompiler "/DRepositoryRoot=$RepositoryRoot" 'packaging/inno/setup.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o setup Inno.' }
    Copy-Item -LiteralPath 'build/native/MockAiZeApiUninstall.exe' -Destination 'release/MockAiZeApiUninstall.exe' -Force
    & $Python packaging/verify_binaries.py
    if ($LASTEXITCODE -ne 0) { throw 'Verificação do pacote nativo falhou; não distribua o resultado.' }
    $PkgPath = [IO.Path]::GetFullPath((Join-Path $RepositoryRoot 'build/service/MockAiZeApiService.pkg'))
    if (-not $PkgPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Intermediário fora do projeto.' }
    if (Test-Path -LiteralPath $PkgPath) { Remove-Item -LiteralPath $PkgPath -Force }
    Get-Item -LiteralPath 'release/MockAiZe-API-Setup.exe', 'release/MockAiZeApiUninstall.exe' | Select-Object Name,Length
} finally {
    Pop-Location
}
