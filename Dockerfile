FROM node:22-bookworm AS web-build

ARG VITE_AGENTTALK_TOKEN
ENV VITE_AGENTTALK_TOKEN=${VITE_AGENTTALK_TOKEN}

WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV AGENTTALK_HOST=0.0.0.0
ENV AGENTTALK_PORT=8787
ENV AGENTTALK_DATABASE=/data/agenttalk.sqlite3
ENV AGENTTALK_WEB_DIST=/app/web/dist

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra feishu

COPY --from=web-build /app/web/dist ./web/dist
COPY docker/entrypoint.sh /usr/local/bin/agenttalk-hub-entrypoint
RUN chmod +x /usr/local/bin/agenttalk-hub-entrypoint

VOLUME ["/data"]
EXPOSE 8787

ENTRYPOINT ["agenttalk-hub-entrypoint"]
