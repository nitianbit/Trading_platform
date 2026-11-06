FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY scripts ./scripts
COPY migrate_all.py alembic.ini ./
COPY alembic ./alembic
COPY License.md ./
RUN useradd --uid 10001 --create-home app && mkdir /app/logs && chown app:app /app/logs
ARG DHK_SOURCE_FINGERPRINT
RUN test "${#DHK_SOURCE_FINGERPRINT}" -eq 64
LABEL io.dhk-paper.source-fingerprint=$DHK_SOURCE_FINGERPRINT
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8083", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
