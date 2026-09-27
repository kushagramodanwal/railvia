# RailVia — one image, one process.
#
# The UI is built to static files by Node at BUILD time, then served by
# FastAPI at RUN time. So the running container has no Node in it, one origin,
# no CORS and no proxy — and only one thing to deploy.

# ── build the UI ────────────────────────────────────────────────────────
FROM node:22-slim AS ui

WORKDIR /ui
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# Empty API origin: the UI is served from the same host as the API, so it
# calls /api directly rather than a hardcoded URL.
ENV STATIC_EXPORT=1
ENV NEXT_PUBLIC_API_ORIGIN=""
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
RUN npm run build

# ── run the API, serving that UI ────────────────────────────────────────
FROM python:3.13-slim

RUN useradd -m -u 1000 app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app src/ src/
COPY --chown=app:app data/cache/railradar/ data/cache/railradar/
COPY --chown=app:app data/grounded_sections.json data/
COPY --chown=app:app --from=ui /ui/out/ web/out/
COPY --chown=app:app scripts/ scripts/
RUN mkdir -p data/cache/plans && chown -R app:app data/cache

ENV PYTHONUNBUFFERED=1
ENV SOLVER_WORKERS=2
USER app
EXPOSE 7860

CMD ["sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
