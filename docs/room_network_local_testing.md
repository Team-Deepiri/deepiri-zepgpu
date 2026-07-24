# Room Network Local Testing

Phase 8 provides a reproducible local simulation path for testing room networking
without requiring real cloud deployment or a real GPU provider node.

## Goal

Run:

- one local coordinator/backend
- one simulated room node
- fake GPU heartbeat metrics
- no-op remote dispatch flow
- room dashboard visibility

## Prerequisites

- Docker Desktop running
- Poetry environment installed
- Node/npm installed for the UI
- Local backend reachable on `http://127.0.0.1:8000`

## Start coordinator stack

```powershell
cd docker
docker compose up -d --build
docker compose ps