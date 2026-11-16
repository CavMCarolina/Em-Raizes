# Imagem única: o FastAPI serve a API (/api) e o app do administrador já compilado (/).
# Build:  docker build -t em-raizes .
# Rodar:  docker run -p 8000:8000 --env-file .env em-raizes

# ---------- 1) frontend (TypeScript -> arquivos estáticos)
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 2) backend (Python)
FROM python:3.12-slim AS backend
# commit da imagem (o CI passa com --build-arg); aparece em /api/saude para conferir o deploy
ARG EM_RAIZES_COMMIT=""
ENV EM_RAIZES_COMMIT=${EM_RAIZES_COMMIT}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EM_RAIZES_AMBIENTE=producao \
    EM_RAIZES_PASTA_FRONTEND=/app/frontend \
    PORT=8000
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/src backend/src
RUN pip install ./backend && useradd --create-home --uid 10001 app
COPY --from=frontend /app/frontend/dist /app/frontend
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/saude').status == 200 else 1)"
CMD ["sh", "-c", "uvicorn em_raizes.api.main:criar_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers"]
