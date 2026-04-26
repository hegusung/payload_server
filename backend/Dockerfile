FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY dist/ ./dist/
EXPOSE 8080 8443
CMD ["python3", "-m", "app.main"]
