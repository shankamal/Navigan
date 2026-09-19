FROM python:3.12-alpine3.23

RUN addgroup -S navigan && adduser -S -G navigan -u 10001 navigan
WORKDIR /app
COPY agent.py /app/agent.py
USER 10001:10001
ENTRYPOINT ["python", "/app/agent.py"]
