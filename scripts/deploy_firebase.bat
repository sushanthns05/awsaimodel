@echo off
REM ===========================================================================
REM Build React Dashboard and Deploy to Firebase Hosting
REM ===========================================================================

set COMSPEC=C:\WINDOWS\system32\cmd.exe

echo [1/3] Running frontend Vitest test suite...
cd frontend
call npm test
if %ERRORLEVEL% NEQ 0 (
    echo Error: Frontend tests failed. Aborting deployment.
    cd ..
    exit /b %ERRORLEVEL%
)

echo [2/3] Building production bundle with Vite...
call npm run build
if %ERRORLEVEL% NEQ 0 (
    echo Error: Frontend build failed.
    cd ..
    exit /b %ERRORLEVEL%
)
cd ..

echo [3/3] Deploying to Firebase Hosting...
call npx firebase-tools deploy --only hosting
echo Deployment complete!

