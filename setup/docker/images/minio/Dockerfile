# Vendors the MinIO server binary from its GitHub release instead of pulling
# quay.io/minio/minio, which stopped accepting anonymous pulls in late 2026
# (docs/get-started/gcp-standalone.md § "The MinIO workaround"). Docker Hub's
# minio/minio does not exist and bitnami/minio returns empty tag lists, but the
# GitHub release asset URLs still resolve — this is the same source
# setup/local/linux/storage/install_minio.sh uses for a native (non-Docker) install.
#
# Bump MINIO_VERSION here (must be a real https://github.com/minio/minio/releases
# tag) and republish (release-images.yml, workflow_dispatch) when the pinned
# version needs to move; nothing else references this file's default.
FROM alpine:3.20

ARG MINIO_VERSION=RELEASE.2025-07-23T15-54-02Z

RUN apk add --no-cache ca-certificates curl && \
    curl -fsSL -o /usr/bin/minio \
      "https://github.com/minio/minio/releases/download/${MINIO_VERSION}/minio.linux-amd64.${MINIO_VERSION}" && \
    chmod +x /usr/bin/minio

EXPOSE 9000 9001
ENTRYPOINT ["minio"]
