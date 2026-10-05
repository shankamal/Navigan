FROM python:3.12-alpine3.23

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /root/.cache /usr/local/lib/python3.12/site-packages/pip* \
    && addgroup -S navigan \
    && adduser -S -G navigan -u 10001 navigan

WORKDIR /app
COPY --chown=10001:10001 migration_connector /app/migration_connector

USER 10001:10001
ENTRYPOINT ["python", "-m", "migration_connector.agent"]
