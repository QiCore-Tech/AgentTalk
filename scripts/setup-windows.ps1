# AgentTalk Windows Setup Script
# Run in PowerShell: .\scripts\setup-windows.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== AgentTalk Windows Setup ===" -ForegroundColor Cyan

# 1. Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error "Python 3.12+ is required. Please install from https://python.org"
    exit 1
}

$pyVersion = & $python.Source --version 2>$null
Write-Host "Found: $pyVersion" -ForegroundColor Green

# 2. Check uv (optional but recommended)
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Write-Host "uv found, using uv for install" -ForegroundColor Green
} else {
    Write-Host "uv not found, will use pip" -ForegroundColor Yellow
}

# 3. Install AgentTalk
$installExtras = "[feishu,llm,windows]"
if ($uv) {
    Write-Host "Installing with uv..." -ForegroundColor Cyan
    & uv pip install -e ".$installExtras"
} else {
    Write-Host "Installing with pip..." -ForegroundColor Cyan
    & $python.Source -m pip install -e ".$installExtras"
}

# 4. Create config directory
$configDir = Join-Path $env:USERPROFILE ".agenttalk"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

# 5. Setup Hub connection
$hubUrl = Read-Host "Enter Hub URL (e.g., https://agents.qicore.tech)"
$token = Read-Host "Enter Hub token"

$config = @{
    hub_url = $hubUrl
    token = $token
} | ConvertTo-Json

$configPath = Join-Path $configDir "config.json"
$config | Set-Content -Path $configPath -Encoding UTF8

Write-Host "Config saved to $configPath" -ForegroundColor Green

# 6. Instructions
Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start your AI agent in a terminal window (e.g., claude, codex)"
Write-Host "  2. Register it: agenttalk register --short-id my-agent --tmux-target mywindow:0.0"
Write-Host "     (On Windows, use a unique identifier for your terminal window)"
Write-Host "  3. Start relay: agenttalk daemon start"
Write-Host ""
Write-Host "Note: On Windows, agents run directly without tmux."
Write-Host "      Keep your agent terminal window open for the relay to work."
Write-Host ""
