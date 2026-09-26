# Vendors the MinIO client (mc) binary from its GitHub release — see
# setup/docker/images/minio/Dockerfile for why (quay.io/minio/mc no longer
# accepts anonymous pulls). Kept as its own image, matching upstream's split
# between quay.io/minio/minio and quay.io/minio/mc, so docker-compose.yml's
# minio-init service (which only ever runs `mc ...`) doesn't carry the
# ~130 MB minio server binary it never uses.
FROM alpine:3.20

ARG MC_VERSION=RELEASE.2025-04-16T18-13-26Z

RUN apk add --no-cache ca-certificates curl && \
    curl -fsSL -o /usr/bin/mc \
      "https://github.com/minio/mc/releases/download/${MC_VERSION}/mc.linux-amd64.${MC_VERSION}" && \
    chmod +x /usr/bin/mc

ENTRYPOINT ["mc"]
