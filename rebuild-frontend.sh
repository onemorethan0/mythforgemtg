#!/bin/bash
# Rebuild the frontend after source changes
cd "$(dirname "$0")/frontend"
echo "🔨 Rebuilding frontend..."
npm run build
if [ $? -eq 0 ]; then
  echo "✅ Frontend rebuilt successfully"
else
  echo "❌ Frontend build failed"
  exit 1
fi
