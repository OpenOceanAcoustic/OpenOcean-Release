#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
image="${1:-openocean/field-release:2026.09}"
docker build --pull --tag "$image" \
  --file "$repository_root/containers/linux-release.Dockerfile" "$repository_root"
image_id="$(docker image inspect --format '{{.Id}}' "$image")"
printf '%s@%s\n' "${image%%:*}" "$image_id"
