#!/bin/bash
set -e

# FHIR Server loop moved to separate container (docker-compose)
# or handled by agent wait-for logic.

echo "Starting Green Agent..."
exec uv run src/server.py --host 0.0.0.0 --port 9009
