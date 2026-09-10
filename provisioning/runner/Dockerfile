FROM hashicorp/terraform:1.13.2
ARG MODULE_VERSION=1.0.0
RUN apk add --no-cache python3 py3-pip && python3 -m venv /opt/venv
COPY provisioning/runner/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
COPY provisioning/runner/runner.py /app/runner.py
COPY terraform/modules/aws-eks /app/modules/aws-eks
RUN printf '%s' "$MODULE_VERSION" > /app/module-version
ENTRYPOINT ["/opt/venv/bin/python", "/app/runner.py"]
