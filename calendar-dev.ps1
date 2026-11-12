[CmdletBinding()]
param(
    [ValidateSet('start','stop')][string]$Action = 'start',
    [switch]$StopCompose,
    [string]$Binary = $env:CALENDAR_LLAMA_BINARY,
    [string]$Model = $env:CALENDAR_MODEL_PATH,
    [ValidateRange(1,65535)][int]$Port = $(if ($env:CALENDAR_MODEL_PORT) { [int]$env:CALENDAR_MODEL_PORT } else { 8080 }),
    [string]$Bind = $(if ($env:CALENDAR_MODEL_BIND) { $env:CALENDAR_MODEL_BIND } else { '127.0.0.1' }),
    [ValidateRange(5,1800)][int]$TimeoutSeconds = 300
)
$ErrorActionPreference = 'Stop'
$compose = @('compose','-f','docker-compose.yml','-f','compose.agent.yml')
$dir = Join-Path $PSScriptRoot '.calendar-dev'
$state = Join-Path $dir 'llama.json'

function Get-OwnedProcess {
    if (!(Test-Path -LiteralPath $state)) { return }
    $saved = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
    $p = Get-Process -Id ([int]$saved.pid) -ErrorAction SilentlyContinue
    if ($p -and $p.Path -eq $saved.path -and $p.StartTime.ToUniversalTime().Ticks.ToString() -eq $saved.ticks) {
        return $p
    }
}

function Wait-Page([string]$Url, [int]$Seconds, $Process, [switch]$JsonHealth) {
    $end = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        if ($Process.HasExited) { throw "llama-server exited ($($Process.ExitCode)). See $dir\llama-error.log" }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4
            if ($response.StatusCode -eq 200 -and (!$JsonHealth -or ($response.Content | ConvertFrom-Json).status -eq 'ok')) { return }
        } catch { }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $end)
    throw "Timed out waiting for $Url. Inspect .calendar-dev logs and docker compose logs backend."
}

Push-Location $PSScriptRoot
$lock = $null
$launched = $null
$ready = $false
$oldBase = $env:AGENT_MODEL_BASE_URL
$oldName = $env:AGENT_MODEL_NAME
try {
    [void](New-Item -ItemType Directory -Path $dir -Force)
    $lock = [IO.File]::Open((Join-Path $dir 'operation.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $owned = Get-OwnedProcess
    if ($Action -eq 'stop') {
        if ($owned) { $owned.Kill(); $owned.WaitForExit(); Write-Host 'Stopped the recorded llama-server.' }
        if (Test-Path -LiteralPath $state) { Remove-Item -LiteralPath $state }
        if ($StopCompose) {
            & docker @compose stop web backend postgres
            if ($LASTEXITCODE) { throw 'Compose stop failed.' }
        }
        return
    }
    if ($owned) { throw 'A managed llama-server is already running. Stop it before restarting.' }
    if (!$Binary) { $Binary = 'C:\llamacpp\llama-server.exe' }
    if (!$Model) { $Model = Join-Path $PSScriptRoot 'Qwen3.8-27B-UD-Q4_K_XL.gguf' }
    foreach ($file in @($Binary,$Model,'backend/.env')) {
        if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing required file: $file" }
    }
    $Model = (Resolve-Path -LiteralPath $Model).Path
    $Binary = (Resolve-Path -LiteralPath $Binary).Path
    $ip = [ipaddress]::Parse($Bind)
    if ($ip.AddressFamily -ne 'InterNetwork' -or $ip.Equals([ipaddress]::Any)) {
        throw 'Bind must be a specific IPv4 interface address (default 127.0.0.1).'
    }
    if (!$env:AGENT_MODEL_BASE_URL) { $env:AGENT_MODEL_BASE_URL = "http://host.docker.internal:$Port/v1" }
    if (!$env:AGENT_MODEL_NAME) { $env:AGENT_MODEL_NAME = 'calendar-qwen' }
    if ($env:AGENT_MODEL_NAME -notmatch '^[a-zA-Z0-9._-]+$') { throw 'Use letters, digits, dash, underscore or dot for AGENT_MODEL_NAME.' }
    & docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE) { throw 'Docker Desktop Linux engine is unavailable.' }
    $configJson = & docker @compose config --format json
    if ($LASTEXITCODE) { throw 'Invalid Compose configuration. Check backend/.env and root Grafana configuration.' }
    $services = ($configJson -join [Environment]::NewLine | ConvertFrom-Json).services
    $publicPorts = @{}
    $ports = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port
    if ($ports -contains $Port) { throw "Model port $Port is occupied." }
    foreach ($service in @{web=3000;backend=8000;postgres=5432}.GetEnumerator()) {
        $published = ($services.($service.Key).ports | Where-Object target -eq $service.Value).published
        if (!$published) { throw "Missing published port for $($service.Key)." }
        $publicPorts[$service.Key] = [int]$published
        if ($Port -eq [int]$published) { throw "Model port $Port is reserved for $($service.Key)." }
        if ($ports -contains [int]$published) {
            $mapping = & docker @compose port $service.Key $service.Value 2>$null
            if (!$mapping -or !($mapping -match ":$published$")) { throw "Port $published is occupied outside this Compose service." }
        }
    }
    $launched = Start-Process -FilePath $Binary -ArgumentList @('--model',('"{0}"' -f $Model),'--host',$Bind,'--port',$Port,'--alias',$env:AGENT_MODEL_NAME,'--jinja','--ctx-size','4096','--parallel','1') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dir 'llama.log') -RedirectStandardError (Join-Path $dir 'llama-error.log')
    @{pid=$launched.Id;path=$Binary;ticks=$launched.StartTime.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json | Set-Content -LiteralPath $state
    Wait-Page "http://${Bind}:$Port/health" $TimeoutSeconds $launched -JsonHealth
    & docker @compose up -d --build postgres backend web
    if ($LASTEXITCODE) { throw 'Compose startup failed. Check Docker output for port, migration or build errors.' }
    Wait-Page "http://127.0.0.1:$($publicPorts.backend)/health" 90 $launched -JsonHealth
    'import os,json,urllib.request; u=os.environ["AGENT_MODEL_BASE_URL"].rstrip("/")+"/models"; ids=[m["id"] for m in json.load(urllib.request.urlopen(u,timeout=8))["data"]]; assert os.environ["AGENT_MODEL_NAME"] in ids' | & docker @compose exec -T backend python -
    if ($LASTEXITCODE) { throw 'Backend could not reach the configured model alias. Check AGENT_MODEL_BASE_URL, the Docker interface and firewall.' }
    Wait-Page "http://127.0.0.1:$($publicPorts.web)/auth" 90 $launched
    $ready = $true
    Write-Host "Ready: http://localhost:$($publicPorts.web)/agent"
} finally {
    if ($launched -and !$ready) {
        if (!$launched.HasExited) { $launched.Kill(); $launched.WaitForExit() }
        if (Test-Path -LiteralPath $state) { Remove-Item -LiteralPath $state }
    }
    $env:AGENT_MODEL_BASE_URL = $oldBase
    $env:AGENT_MODEL_NAME = $oldName
    if ($lock) { $lock.Dispose() }
    Pop-Location
}
