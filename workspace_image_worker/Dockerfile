FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends skopeo ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY src/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && useradd --uid 10001 --create-home collector
COPY src/navigan /app/navigan
COPY workspace_image_worker/entrypoint.py /app/entrypoint.py
RUN mkdir -p /app/certs && python -c "import urllib.request; urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem','/app/certs/global-bundle.pem')" && chmod 644 /app/certs/global-bundle.pem
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["python", "/app/entrypoint.py"]
