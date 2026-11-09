@echo off
REM ===========================================================================
REM Deploy FastAPI Backend and Background Worker to Render
REM ===========================================================================

echo [1/3] Validating Python test suite...
call .venv\Scripts\python.exe -m pytest tests/test_fastapi_endpoints.py
if %ERRORLEVEL% NEQ 0 (
    echo Error: Tests failed. Fix test failures before deploying.
    exit /b %ERRORLEVEL%
)

echo [2/3] Checking Git status...
git status -s

echo [3/3] Deployment instructions:
echo Push changes to your linked GitHub repository.
echo Render will automatically detect render.yaml Blueprint and deploy:
echo   - Web Service: sbg-recruitment-api (FastAPI)
echo   - Background Worker: sbg-recruitment-worker (SQS Consumer)
echo.
echo View deployment status in your Render dashboard: https://dashboard.render.com

