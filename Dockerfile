FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt && useradd --create-home studio
COPY backend/ backend/
COPY alembic.ini ./
COPY --from=frontend /build/dist frontend/dist/
RUN mkdir -p .runtime/data && chown -R studio:studio /app
USER studio
EXPOSE 9030
CMD ["python", "-m", "uvicorn", "backend.app.api:app", "--host", "0.0.0.0", "--port", "9030"]
