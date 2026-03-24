#!/bin/bash
# Fors8 Setup Script
# Run this once to set up the project

set -e

echo "Fors8 — Geopolitical War Prediction Engine"
echo "============================================"
echo ""

# Check dependencies
command -v python3 >/dev/null || { echo "Python 3 required"; exit 1; }
command -v node >/dev/null || { echo "Node.js required"; exit 1; }

echo "[1/4] Installing backend dependencies..."
cd backend && pip3 install -r requirements.txt
cd ..

echo ""
echo "[2/4] Installing frontend dependencies..."
cd frontend && npm install
cd ..

echo ""
echo "[3/4] Configuring environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — edit it to add your API keys"
else
    echo ".env already exists — skipping"
fi

echo ""
echo "[4/4] Setting up PostgreSQL..."
if command -v psql >/dev/null; then
    psql -d postgres -c "CREATE DATABASE fors8;" 2>/dev/null && \
        echo "PostgreSQL database 'fors8' created" || \
        echo "PostgreSQL database 'fors8' already exists"
else
    echo "PostgreSQL not found — chat history will not persist"
fi

echo ""
echo "============================================"
echo "Setup complete! Run: npm run dev"
