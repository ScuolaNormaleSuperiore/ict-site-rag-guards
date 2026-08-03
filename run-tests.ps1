<#
.SYNOPSIS
    Runs the ict-site-rag-guards test suite.

.DESCRIPTION
    Two modes, because the tests do not all need the same environment.

    -Unit   Runs everything under tests/unit with the local Python interpreter.
            Fast, no container, no core dependency: those tests import nothing
            from `cat`. This is the loop to use while writing checks.

    default Runs the whole suite inside the running container. Needed by
            tests/integration, which imports the plugin module and therefore
            needs `cat` and its dependencies importable. The tests still never
            contact the running Cat: the container is used as an interpreter,
            not as a server.

    Exit code is the one pytest returns, so the script can be reused in a hook
    or in CI.

.PARAMETER Unit
    Run only the pure-logic tests, locally.

.PARAMETER Detailed
    Pass -v to pytest, listing every test name.

.EXAMPLE
    .\run-tests.ps1 -Unit
    Fast local run while developing a new check.

.EXAMPLE
    .\run-tests.ps1
    Full suite before committing.

.EXAMPLE
    .\run-tests.ps1 -Detailed
    Full suite, one line per test.
#>
[CmdletBinding()]
param(
    [switch]$Unit,
    [switch]$Detailed
)

# Not using $ErrorActionPreference = 'Stop': this script drives native commands
# and inspects their exit codes explicitly.

$pluginDir = $PSScriptRoot
$service = 'cheshire-cat-core'

# Where the plugin folder appears inside the container: compose mounts ./core on /app.
$pluginInContainer = '/app/cat/plugins/ict-site-rag-guards'

$pytestArgs = @()
if ($Detailed) { $pytestArgs += '-v' }

# --- local mode: pure logic only ------------------------------------------------

if ($Unit) {
    Write-Host "Test di unita' (logica pura), interprete locale" -ForegroundColor Cyan

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Host "python non trovato nel PATH." -ForegroundColor Red
        Write-Host "Usa la suite nel container:  .\run-tests.ps1"
        exit 1
    }

    & python -c "import pytest" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pytest non e' installato in questo interprete:" -ForegroundColor Red
        Write-Host "  $($python.Source)"
        Write-Host "Installalo una volta con:  python -m pip install pytest"
        Write-Host "Oppure usa la suite nel container:  .\run-tests.ps1"
        exit 1
    }

    Push-Location $pluginDir
    try {
        & python -m pytest tests/unit @pytestArgs
    }
    finally {
        Pop-Location
    }
    exit $LASTEXITCODE
}

# --- container mode: whole suite ------------------------------------------------

$composeFile = Join-Path $pluginDir '..\..\..\..\compose.yml'
if (-not (Test-Path $composeFile)) {
    Write-Host "compose.yml non trovato dove atteso:" -ForegroundColor Red
    Write-Host "  $composeFile"
    Write-Host "Lo script assume che il plugin stia in core/cat/plugins/ del progetto Stregatto."
    exit 1
}
$composeFile = (Resolve-Path $composeFile).Path

$containerId = docker compose -f $composeFile ps -q $service 2>$null
if (-not $containerId) {
    Write-Host "Il container '$service' non e' in esecuzione." -ForegroundColor Red
    Write-Host "Avvialo con:  docker compose -f `"$composeFile`" up -d"
    Write-Host "Oppure lancia solo i test di unita':  .\run-tests.ps1 -Unit"
    exit 1
}

Write-Host "Suite completa (unita' + contratto) nel container '$service'" -ForegroundColor Cyan

# -w is required: pytest.ini, and the pythonpath it declares, are resolved from
# the plugin folder. The core is reached through the "/app" entry of that same
# pythonpath, so no PYTHONPATH variable is needed here.
& docker compose -f $composeFile exec -T -w $pluginInContainer $service python -m pytest @pytestArgs
exit $LASTEXITCODE
