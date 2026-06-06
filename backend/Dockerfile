# Stage 1: build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Override outDir to stay within /frontend during build
RUN npm run build -- --outDir /dist

# Stage 2: Python backend
FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app/ ./app/
COPY --from=frontend-build /dist/ ./dist/
EXPOSE 8080 8443
CMD ["python3", "-m", "app.main"]
