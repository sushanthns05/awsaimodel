#!/usr/bin/env bash
# =============================================================================
# Build React Dashboard and Deploy to Firebase Hosting
# =============================================================================
set -e

echo "[1/3] Running Vitest frontend unit tests..."
cd frontend
npm test

echo "[2/3] Building production bundle..."
npm run build
cd ..

echo "[3/3] Deploying to Firebase Hosting..."
npx firebase-tools deploy --only hosting
echo "Frontend deployed successfully!"

