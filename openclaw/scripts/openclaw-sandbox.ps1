<#
.SYNOPSIS
    Run OpenClaw in a Docker Sandbox with cloud LLM providers via auth-proxy.

.DESCRIPTION
    OpenClaw runs isolated in a sandbox. All LLM API requests route through
    auth-proxy on the host, which injects credentials. The sandbox never
    sees API keys.

    Sandbox-side scripts live in scripts/sandbox/ and are deployed at build
    time. They are configured entirely through environment variables so they
    stay independent of the host launcher.

    Architecture:
      Host:    auth-proxy (localhost:AuthProxyPort)
      Sandbox: OpenClaw TUI + gateway + bridge
      Bridge:  sandbox:BridgePort -> Docker HTTP proxy -> host:AuthProxyPort -> cloud

.PARAMETER SkipBuild
    Skip the install phase if the sandbox already exists.

.PARAMETER AuthProxyPort
    Port where auth-proxy is listening on the host (default: 12435).

.PARAMETER BridgePort
    Port for the bridge inside the sandbox (default: 54321).

.PARAMETER Providers
    Comma-separated list of provider names to configure in OpenClaw.
    Must match route names in your auth-proxy config.
    If empty, all routes discovered from auth-proxy are used.

.PARAMETER Models
    JSON string mapping provider names to model arrays. Example:
    '{"openai": [{"id": "gpt-5.1", "name": "GPT 5.1"}]}'

.PARAMETER SandboxName
    Name for the Docker Sandbox (default: openclaw).

.EXAMPLE
    .\openclaw-sandbox.ps1 -Providers "openai" -Models '{"openai": [{"id": "gpt-5.1", "name": "GPT 5.1"}]}'

.EXAMPLE
    .\openclaw-sandbox.ps1 -SkipBuild -Providers "openai"
#>

param(
    [switch]$SkipBuild,
    [int]$AuthProxyPort = 12435,
    [int]$BridgePort = 54321,
    [string]$Providers = "",
    [Parameter(Mandatory=$true)]
    [string]$Models,
    [string]$SandboxName = "openclaw"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SandboxDir = Join-Path $ScriptDir "sandbox"


# Helper functions

function Assert-ExitCode {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $Message (exit code $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Test-AuthProxy {
    param([int]$Port)
    Write-Host "`n==> Checking auth-proxy on localhost:$Port..." -ForegroundColor Cyan
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        $routeNames = ($health.routes | ForEach-Object { $_.name }) -join ", "
        Write-Host "    Auth proxy running. Routes: $routeNames" -ForegroundColor Green
    } catch {
        Write-Host "    ERROR: auth-proxy not reachable on localhost:$Port" -ForegroundColor Red
        Write-Host "    Start it first: auth-proxy serve --port $Port" -ForegroundColor Yellow
        exit 1
    }
}

function Deploy-FileToSandbox {
    param(
        [string]$Name,
        [string]$LocalPath,
        [string]$RemotePath,
        [switch]$Executable
    )
    $content = (Get-Content $LocalPath -Raw) -replace "`r", ''
    $chmod = if ($Executable) { "`nchmod +x $RemotePath" } else { "" }
    $cmd = "cat > $RemotePath << '__SANDBOX_DEPLOY_EOF__'`n${content}`n__SANDBOX_DEPLOY_EOF__${chmod}"
    $cmd = $cmd -replace "`r", ''
    docker sandbox exec $Name bash -c $cmd
    Assert-ExitCode "Failed to deploy $(Split-Path $LocalPath -Leaf) to $RemotePath"
}

function Initialize-Sandbox {
    param([string]$Name)
    docker sandbox stop $Name 2>$null
    docker sandbox rm $Name 2>$null
    Start-Sleep -Seconds 2

    Write-Host "`n==> Creating sandbox..." -ForegroundColor Cyan
    docker sandbox create --name $Name shell .
    Assert-ExitCode "Failed to create sandbox"

    Write-Host "==> Allowing network for downloads..." -ForegroundColor Cyan
    docker sandbox network proxy $Name --allow-host '*'
    Assert-ExitCode "Failed to configure network proxy"
}

function Install-SandboxDependencies {
    param([string]$Name)
    Write-Host "==> Installing dependencies inside sandbox..." -ForegroundColor Cyan
    Deploy-FileToSandbox -Name $Name `
        -LocalPath (Join-Path $SandboxDir "install.sh") `
        -RemotePath "~/install.sh" -Executable
    docker sandbox exec $Name bash -c '~/install.sh'
    Assert-ExitCode "Install failed inside sandbox"
}

function Deploy-SandboxScripts {
    param([string]$Name)
    Write-Host "==> Deploying sandbox scripts..." -ForegroundColor Cyan

    Deploy-FileToSandbox -Name $Name `
        -LocalPath (Join-Path $SandboxDir "auth-proxy-bridge.js") `
        -RemotePath "~/auth-proxy-bridge.js"

    Deploy-FileToSandbox -Name $Name `
        -LocalPath (Join-Path $SandboxDir "configure-openclaw.py") `
        -RemotePath "~/configure-openclaw.py" -Executable

    Deploy-FileToSandbox -Name $Name `
        -LocalPath (Join-Path $SandboxDir "start.sh") `
        -RemotePath "~/start.sh" -Executable
}

function Set-SandboxNetworkPolicy {
    param(
        [string]$Name,
        [int]$AllowPort
    )
    Write-Host "==> Locking down network (allowing ONLY localhost:$AllowPort)..." -ForegroundColor Cyan
    docker sandbox network proxy $Name `
        --policy deny `
        --allow-host "localhost:$AllowPort"
    Assert-ExitCode "Failed to configure network proxy"
}


# Main

# Validate -Models JSON
try {
    $modelsObj = $Models | ConvertFrom-Json
} catch {
    Write-Host "ERROR: -Models is not valid JSON." -ForegroundColor Red
    Write-Host "       Expected: '{""provider"": [{""id"": ""model-id"", ""name"": ""Display Name""}]}'" -ForegroundColor Yellow
    exit 1
}
foreach ($prop in $modelsObj.PSObject.Properties) {
    $providerName = $prop.Name
    foreach ($i in 0..($prop.Value.Count - 1)) {
        $model = $prop.Value[$i]
        if (-not $model.id) {
            Write-Host "ERROR: models.$providerName[$i] is missing required field 'id'." -ForegroundColor Red
            Write-Host "       Each model must have: {""id"": ""model-id"", ""name"": ""Display Name""}" -ForegroundColor Yellow
            exit 1
        }
        if (-not $model.name) {
            Write-Host "ERROR: models.$providerName[$i] is missing required field 'name'." -ForegroundColor Red
            Write-Host "       Each model must have: {""id"": ""model-id"", ""name"": ""Display Name""}" -ForegroundColor Yellow
            exit 1
        }
    }
}

# Pre-flight
Test-AuthProxy -Port $AuthProxyPort

# Build phase
if (-not $SkipBuild) {
    Initialize-Sandbox -Name $SandboxName
    Install-SandboxDependencies -Name $SandboxName
    Deploy-SandboxScripts -Name $SandboxName
    Write-Host "==> Install complete.`n" -ForegroundColor Green
}

# Lock down network
Set-SandboxNetworkPolicy -Name $SandboxName -AllowPort $AuthProxyPort

# Build environment variable string for start.sh
$envVars = "BRIDGE_PORT=$BridgePort AUTH_PROXY_PORT=$AuthProxyPort"
if ($Providers) {
    $envVars += " PROVIDERS='$Providers'"
}
if ($Models) {
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Models))
    $envVars += " MODELS_B64='$b64'"
}

# Launch
Write-Host "==> Launching OpenClaw..." -ForegroundColor Cyan
Write-Host "    Auth proxy: localhost:$AuthProxyPort" -ForegroundColor Yellow
if ($Providers) {
    Write-Host "    Providers: $Providers" -ForegroundColor Yellow
}
Write-Host "    Network: sandbox can ONLY reach localhost:$AuthProxyPort`n" -ForegroundColor Yellow

docker sandbox exec -it $SandboxName bash -c "$envVars ~/start.sh"

# After exit
Write-Host "`n==> OpenClaw exited." -ForegroundColor Cyan
Write-Host "    Sandbox '$SandboxName' is still running." -ForegroundColor Gray
Write-Host "    Reconnect: run this script again with -SkipBuild" -ForegroundColor Gray
Write-Host "    Shell:     docker sandbox exec -it $SandboxName bash" -ForegroundColor Gray
Write-Host "    Destroy:   docker sandbox stop $SandboxName; docker sandbox rm $SandboxName" -ForegroundColor Gray
