@echo off
chcp 65001 > nul
REM AgentTalk Hub - Windows Docker Starter (Batch version)
REM Requires: Docker Desktop (with WSL2 backend)

echo === AgentTalk Hub - Windows Docker ===
echo.

REM Check Docker
docker info > nul 2>&1
if errorlevel 1 (
    echo Error: Docker Desktop is not running.
    echo Please install and start Docker Desktop: https://www.docker.com/products/docker-desktop
    exit /b 1
)

echo Docker Desktop detected.

REM Check .env file
if not exist .env (
    echo.
    echo .env file not found. Creating template...
    (
        echo # AgentTalk Hub Configuration
        echo AGENTTALK_TOKEN=change-me-to-a-random-string
        echo AGENTTALK_PORT=8787
        echo.
        echo # Feishu Integration ^(optional^)
        echo FEISHU_ENABLE=0
        echo FEISHU_APP_ID=
        echo FEISHU_APP_SECRET=
        echo FEISHU_ALERT_CHAT_ID=
        echo.
        echo # Public URL ^(for Feishu callbacks^)
        echo AGENTTALK_PUBLIC_BASE_URL=
    ) > .env
    echo Created .env template. Please edit it with your settings.
    exit /b 1
)

echo Loading .env file...
for /f "usebackq tokens=1,* delims==" %%a in (`.env`) do (
    set "%%a=%%b"
)

if "%AGENTTALK_TOKEN%"=="" (
    echo Error: AGENTTALK_TOKEN is required in .env file
    exit /b 1
)

echo.
echo Starting AgentTalk Hub...
docker compose -f docker-compose.windows.yml up -d --build

if errorlevel 1 (
    echo Error: Failed to start AgentTalk Hub
    exit /b 1
)

echo.
echo ✓ AgentTalk Hub started successfully!
echo.
echo Hub URL: http://localhost:%AGENTTALK_PORT%
echo Web UI:  http://localhost:%AGENTTALK_PORT%
echo.
echo Management commands:
echo   View logs:   docker logs -f agenttalk-hub
echo   Stop Hub:    docker compose -f docker-compose.windows.yml down
echo   Restart:     docker compose -f docker-compose.windows.yml restart
echo.
