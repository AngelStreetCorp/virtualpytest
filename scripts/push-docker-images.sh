#!/bin/bash
# Deprecated — do not use.
#
# This script used to build backend_host / backend_server on a laptop and push them to
# ghcr.io/$GITHUB_USERNAME with a personal access token, for a Render deployment that no
# longer exists. It published under a personal namespace, tagged only `:latest`, and built
# from whatever was in the working tree.
#
# Images are now published by CI, from the public repo only, on a `release-*` tag:
#   .github/workflows/release-images.yml  ->  ghcr.io/angelstreetcorp/virtualpytest-{server,host}
#
# To consume them, set VPT_IMAGE_TAG in setup/docker/.env (see docs/get-started/docker.md).
# To build locally, use the stack itself:  ./setup/docker/launch.sh --rebuild
echo "This script is deprecated. Images are published by .github/workflows/release-images.yml"
echo "on a release-* tag in the public repo. See docs/get-started/docker.md (VPT_IMAGE_TAG)."
exit 1
