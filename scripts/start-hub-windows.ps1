# AgentTalk Hub - Windows Docker Starter
# Requires: Docker Desktop (with WSL2 backend)

$ErrorActionPreference = "Stop"

Write-Host "=== AgentTalk Hub - Windows Docker ===" -ForegroundColor Cyan
Write-Host ""

# Check Docker
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Error "Docker not found. Please install Docker Desktop: https://www.docker.com/products/docker-desktop"
    exit 1
}

# Check Docker Desktop is running
try {
    $null = docker info 2>$null
} catch {
    Write-Error "Docker Desktop is not running. Please start Docker Desktop first."
    exit 1
}

Write-Host "Docker Desktop detected" -ForegroundColor Green

# Check .env file
$envFile = Join-Path $PSScriptRoot ".." ".env"
if (-not (Test-Path $envFile)) {
    Write-Host ""
    Write-Host ".env file not found. Creating template..." -ForegroundColor Yellow
    
    $token = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    
    $template = @"
# AgentTalk Hub Configuration
AGENTTALK_TOKEN=$token
AGENTTALK_PORT=8787

# Feishu Integration (optional)
FEISHU_ENABLE=0
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_ALERT_CHAT_ID=

# Public URL (for Feishu callbacks)
AGENTTALK_PUBLIC_BASE_URL=
"@
    
    $template | Set-Content -Path $envFile -Encoding UTF8
    Write-Host "Created .env file at: $envFile" -ForegroundColor Green
    Write-Host "Please edit it with your settings, then run this script again." -ForegroundColor Yellow
    exit 0
}

Write-Host "Loading .env file..." -ForegroundColor Green

# Parse .env file
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#\s][^=]*)\s*=\s*(.*?)\s*$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}

# Validate required vars
if (-not $env:AGENTTALK_TOKEN) {
    Write-Error "AGENTTALK_TOKEN is required in .env file"
    exit 1
}

Write-Host ""
Write-Host "Starting AgentTalk Hub..." -ForegroundColor Cyan

# Use Windows-specific compose file
$composeFile = Join-Path $PSScriptRoot ".." "docker-compose.windows.yml"

# Build and start
docker compose -f $composeFile up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to start AgentTalk Hub"
    exit 1
}

Write-Host ""
Write-Host "✓ AgentTalk Hub started successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Hub URL: http://localhost:$env:AGENTTALK_PORT" -ForegroundColor Cyan
Write-Host "Web UI:  http://localhost:$env:AGENTTALK_PORT" -ForegroundColor Cyan
Write-Host ""
Write-Host "Management commands:" -ForegroundColor Yellow
Write-Host "  View logs:   docker logs -f agenttalk-hub" -ForegroundColor White
Write-Host "  Stop Hub:    docker compose -f docker-compose.windows.yml down" -ForegroundColor White
Write-Host "  Restart:     docker compose -f docker-compose.windows.yml restart" -ForegroundColor White
Write-Host ""

# Optional: Show logs
docker logs -f agenttalk-hub --tail 20
