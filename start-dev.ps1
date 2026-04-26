param(
    [switch]$SkipMigrate,
    [switch]$NoRunserver,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at '$pythonExe'. Activate/create your venv first."
}

# Make Scoop shims available in this shell so mysqld can be found.
$env:PATH = "$HOME\scoop\shims;$env:PATH"
$mysqldCommand = Get-Command mysqld -ErrorAction SilentlyContinue
if (-not $mysqldCommand) {
    throw "mysqld was not found in PATH. Install mysql-lts (Scoop) or add MySQL bin to PATH."
}

$mysqlAdminCommand = Get-Command mysqladmin -ErrorAction SilentlyContinue

function Test-MySqlListening {
    try {
        return [bool](Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction Stop)
    }
    catch {
        return $false
    }
}

function Test-MySqlReady {
    if ($mysqlAdminCommand) {
        & $mysqlAdminCommand.Source ping -h 127.0.0.1 -P 3306 --protocol=tcp --connect-timeout=1 --silent *> $null
        return ($LASTEXITCODE -eq 0)
    }

    return (Test-MySqlListening)
}

function Wait-MySqlReady {
    param(
        [int]$TimeoutSeconds = 30
    )

    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        [System.Threading.Thread]::Sleep(1000)
        if (Test-MySqlReady) {
            return $true
        }
    }

    return $false
}

if (-not (Test-MySqlListening)) {
    Write-Host 'MySQL is not listening on 3306. Starting mysqld...'

    $mysqlLog = Join-Path $projectRoot 'mysqld-dev.log'
    Get-Job -Name 'dronesec-mysqld-dev' -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue
    Start-Job -Name 'dronesec-mysqld-dev' -ScriptBlock {
        param(
            [string]$WorkingDirectory,
            [string]$LogPath
        )

        Set-Location $WorkingDirectory
        mysqld --console "--log-error=$LogPath"
    } -ArgumentList $projectRoot, $mysqlLog | Out-Null

    if (-not (Wait-MySqlReady -TimeoutSeconds 30)) {
        throw "MySQL did not start within 30 seconds. Check '$mysqlLog' for details."
    }

    Write-Host 'MySQL is now running.'
}
else {
    Write-Host 'MySQL already running on 3306.'
}

if (-not (Wait-MySqlReady -TimeoutSeconds 30)) {
    throw 'MySQL is listening but not ready for connections.'
}

if (-not $SkipMigrate) {
    Write-Host 'Running migrations...'
    & $pythonExe .\manage.py migrate
    if ($LASTEXITCODE -ne 0) {
        throw "Migrations failed with exit code $LASTEXITCODE."
    }
}

if (-not $NoRunserver) {
    Write-Host "Starting Django server on http://127.0.0.1:$Port ..."
    & $pythonExe .\manage.py runserver "127.0.0.1:$Port"
}
