FROM python:3.10-slim

WORKDIR /app

COPY . .

# 安装 curl 用于下载文件
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir flask gunicorn psutil orjson requests pandas numpy duckdb flask-socketio python-socketio

# 下载真实的数据库文件（绕过 LFS 指针）
RUN curl -L -o /app/bybit_eth_data/data/processed/eth_perpetual.db \
    "https://media.githubusercontent.com/media/Thomas134/VSCode-ETH-data/master/bybit_eth_data/data/processed/eth_perpetual.db" && \
    curl -L -o /app/bybit_eth_data/data/processed/eth_structure.db \
    "https://media.githubusercontent.com/media/Thomas134/VSCode-ETH-data/master/bybit_eth_data/data/processed/eth_structure.db"

EXPOSE 8080

CMD cd web && python app.py