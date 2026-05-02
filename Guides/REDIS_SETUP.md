# Redis (rate limits)

Set `REDIS_ENABLED=true` and `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD` in `.env`. Flask-Limiter uses Redis when reachable; otherwise it falls back to in-memory storage (not shared across workers).
