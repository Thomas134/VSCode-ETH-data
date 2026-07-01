FROM python:3.10-slim

WORKDIR /app

COPY . .

# 安装 curl 用于下载文件
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir flask gunicorn psutil orjson requests pandas numpy duckdb flask-socketio python-socketio

EXPOSE 8080

CMD cd web && python app.py