FROM node:22-alpine AS frontend-build

WORKDIR /frontend

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS api

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN groupadd --system --gid 10001 abud && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home abud

COPY --chown=10001:10001 app ./app
COPY --from=frontend-build /frontend/dist ./frontend/dist

EXPOSE 8000

USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
