# syntax=docker/dockerfile:1.7

FROM golang:1.26.6-alpine3.23 AS terraform
ARG TERRAFORM_VERSION=1.16.2
ARG TERRAFORM_COMMIT=82e042fb6372443813f6759056308d6adc642fa1
ARG OTEL_LOG_VERSION=v0.21.0
ENV GOPROXY=https://proxy.golang.org,direct \
    GOSUMDB=sum.golang.org
RUN apk add --no-cache git \
    && git init /src/terraform \
    && cd /src/terraform \
    && git remote add origin https://github.com/hashicorp/terraform.git \
    && git fetch --depth 1 origin "$TERRAFORM_COMMIT" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$TERRAFORM_COMMIT"
RUN --mount=type=cache,target=/go/pkg/mod \
    cd /src/terraform \
    && OTEL_LOG_MODULES="$(go list -m -f '{{if eq .Version "v0.19.0"}}{{.Path}}{{end}}' all | grep '^go.opentelemetry.io/')" \
    && test -n "$OTEL_LOG_MODULES" \
    && for module in $OTEL_LOG_MODULES; do go get "${module}@${OTEL_LOG_VERSION}"; done \
    && go mod tidy \
    && test "$(go list -m -f '{{.Version}}' go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc)" = "$OTEL_LOG_VERSION" \
    && ! go list -m all | grep -E '^go\.opentelemetry\.io/.* v0\.19\.0$'
RUN --mount=type=cache,target=/go/pkg/mod \
    cd /src/terraform \
    && go mod download -x
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    cd /src/terraform \
    && CGO_ENABLED=0 go build -trimpath \
        -ldflags="-s -w -X github.com/hashicorp/terraform/version.dev=no" \
        -o /out/terraform . \
    && test "$(/out/terraform version | head -n 1)" = "Terraform v${TERRAFORM_VERSION}"

FROM python:3.12-alpine3.23
ARG MODULE_VERSION=1.0.0
RUN apk upgrade --no-cache \
    && addgroup -S navigan \
    && adduser -S -G navigan navigan \
    && python3 -m venv /opt/venv \
    && mkdir -p /workspace /app \
    && chown -R navigan:navigan /workspace /app
COPY --from=terraform /out/terraform /usr/local/bin/terraform
COPY provisioning/runner/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && /opt/venv/bin/python -c "import boto3, botocore" \
    && /opt/venv/bin/python -m pip uninstall --yes pip setuptools wheel \
    && python3 -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /root/.cache /tmp/requirements.txt \
        /opt/venv/lib/python3.12/site-packages/pip* \
        /usr/local/lib/python3.12/site-packages/pip* \
        /usr/local/bin/pip*
COPY provisioning/runner/runner.py /app/runner.py
COPY terraform/modules/aws-eks /app/modules/aws-eks
RUN terraform fmt -recursive /app/modules/aws-eks
RUN printf '%s' "$MODULE_VERSION" > /app/module-version
USER navigan
ENTRYPOINT ["/opt/venv/bin/python", "/app/runner.py"]
