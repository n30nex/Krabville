# syntax=docker/dockerfile:1.7
FROM node:24.15.0-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.13.6-slim-bookworm@sha256:2b09112b54420d2e3e814f2cbe34e8e54d32b8c5abd4e72e89cda4758fc6400a
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    KRABVILLE_DATA_DIR=/data \
    KRABVILLE_DATABASE=/data/krabville.db \
    KRABVILLE_REPORT_DIR=/data/reports \
    KRABVILLE_FRONTEND_DIR=/app/frontend/dist \
    KRABVILLE_ASSET_DIR=/app/frontend/dist/assets \
    KRABVILLE_CONTROL_SOCKET=/data/control.sock

RUN groupadd --gid 1000 krabville \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin krabville \
    && mkdir -p /app /data /home/krabville/.codex \
    && chown -R krabville:krabville /app /data /home/krabville
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir .
COPY --from=frontend /build/dist ./frontend/dist
COPY deploy/inference-entrypoint.sh /usr/local/bin/krabville-inference-entrypoint
RUN chmod 0555 /usr/local/bin/krabville-inference-entrypoint \
    && chown -R krabville:krabville /app
USER 1000:1000
CMD ["krabville-api"]
