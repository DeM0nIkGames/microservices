FROM golang:1.24-bookworm AS builder

ARG MINIO_REF=RELEASE.2025-10-15T17-29-55Z

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone \
    --depth 1 \
    --branch "${MINIO_REF}" \
    https://github.com/minio/minio.git /src

WORKDIR /src

RUN CGO_ENABLED=0 go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /out/minio \
    .


FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system minio \
    && useradd --system --gid minio --home-dir /data minio \
    && mkdir -p /data \
    && chown -R minio:minio /data

COPY --from=builder /out/minio /usr/local/bin/minio

USER minio

EXPOSE 9000 9001

ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]