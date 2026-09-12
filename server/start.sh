#!/bin/sh
# One image, two services. Railway sets RAILWAY_SERVICE_NAME.
set -e
if [ "$RAILWAY_SERVICE_NAME" = "worker" ] || [ "$TASTE_ROLE" = "worker" ]; then
  exec python -m tasteserver.worker
fi
exec uvicorn tasteserver.api:app --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips='*'
