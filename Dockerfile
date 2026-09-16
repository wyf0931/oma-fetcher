# Includes CPython 3.12, Debian Bookworm, and uv; keeping this on GHCR avoids
# a second registry dependency during builds on restricted Docker networks.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    FETCHER_HOST=0.0.0.0 \
    FETCHER_PORT=7890

WORKDIR /srv/app

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
ARG http_proxy
ARG https_proxy
ARG all_proxy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev \
    && .venv/bin/python -m playwright install --with-deps chromium \
    && .venv/bin/scrapling install --force \
    && rm -rf /var/lib/apt/lists/* /root/.cache

COPY app ./app
COPY db ./db
COPY web ./web

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/fetcher \
    && chown -R appuser:appuser /srv/app /tmp/fetcher /ms-playwright

USER appuser
EXPOSE 7890

CMD ["sh", "-c", ".venv/bin/uvicorn app.main:app --host ${FETCHER_HOST} --port ${FETCHER_PORT}"]
