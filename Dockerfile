# RailVia — one image, one process.
#
# The UI is built to static files by Node at BUILD time, then served by
# FastAPI at RUN time. So the running container has no Node in it, one origin,
# no CORS and no proxy — and only one thing to deploy.
#
# The optimiser uses OR-Tools, SciPy, NumPy and scikit-learn (~460 MB),
# so it runs as a dedicated container on Render. A container has neither
# serverless package size nor function timeout constraints.

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

# Hugging Face Spaces runs the container as user 1000 against an image built
# by root, so anything the app writes — the plan cache above all — has to be
# owned by that user. Creating the user here rather than chowning afterwards
# keeps the image small: a recursive chown copies every file it touches into
# a new layer.
RUN useradd -m -u 1000 app

WORKDIR /app

# libgomp1 is the OpenMP runtime. LightGBM, and parts of SciPy and
# scikit-learn, are native wheels that link against it, and Debian slim
# images do not ship it. Without this the wheels install cleanly and then
# fail at import with "libgomp.so.1: cannot open shared object file".
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: application edits should not rebuild this layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app src/ src/
# The RailRadar responses and derived sections, committed deliberately so a
# deployment reproduces the same numbers with no API key and no network.
COPY --chown=app:app data/cache/railradar/ data/cache/railradar/
COPY --chown=app:app data/grounded_sections.json data/
# The solved plans, one per month the UI's picker can reach.
#
# Without these the container solves on the first request, and a month-long
# CP-SAT model peaks at 1,148 MB — measured — against a 512 MB instance,
# which is an OOM kill before the first page renders. They are deterministic
# and total half a megabyte, so they ship rather than being computed.
# Regenerate with: python scripts/precompute.py --months 12
COPY --chown=app:app data/cache/plans/ data/cache/plans/
COPY --chown=app:app --from=ui /ui/out/ web/out/
COPY --chown=app:app scripts/ scripts/

ENV PYTHONUNBUFFERED=1

# Never build the CP-SAT model in this container.
#
# This is the line that makes the image fit. With it the server answers from
# the plans copied above and peaks at 253 MB; without it the first request
# builds a month-long model and peaks at 1,148 MB, and a 512 MB instance
# kills it. A month nobody precomputed still gets an answer — the
# constructive schedule, labelled as such in the status so it is never
# mistaken for an optimised plan.
ENV ALLOW_RUNTIME_SOLVE=0

# Belt and braces. Nothing at run time builds a model while the line above
# stands, but if someone turns it back on, two workers peak at 369 MB and
# eight at 651 MB. Two also scored best on plan quality.
ENV SOLVER_WORKERS=2
USER app
EXPOSE 7860

# One worker. Each holds its own solved-plan cache, and CP-SAT already uses
# every core it is given — more workers would multiply memory and duplicate
# solves rather than serve more traffic.
# 7860 is what Hugging Face Spaces expects. Render and Fly set PORT
# explicitly, which overrides it, so one command serves both.
CMD ["sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
