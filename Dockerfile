FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir flask gunicorn

EXPOSE 8080

CMD cd web && gunicorn app:app --bind 0.0.0.0:8080 --workers 2 --timeout 120
