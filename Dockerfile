# Shared super-memory service image.
# Python 3.11 slim + the GitHub CLI (the PR ingester shells out to `gh`), running the
# FastAPI app. The fact store is markdown on a mounted volume (YUNAKI_FACTS_DIR=/data),
# so the same tested ingest/recall/consolidate code runs unchanged behind HTTP.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    YUNAKI_FACTS_DIR=/data

WORKDIR /app

# GitHub CLI (pinned) — used by ingest_pr.py via `gh` with GH_TOKEN from the environment.
ARG GH_VERSION=2.62.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" -o /tmp/gh.tgz \
    && tar -xzf /tmp/gh.tgz -C /tmp \
    && mv "/tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh* \
    && apt-get purge -y curl && apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt server/requirements.txt
RUN pip install --upgrade pip && pip install -r server/requirements.txt

# Reuse the core CLI modules verbatim; the service is a thin layer over them.
COPY facts.py ingest_pr.py consolidate.py ./
COPY server/ ./server/

RUN mkdir -p /data
EXPOSE 8000

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
