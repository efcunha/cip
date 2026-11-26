#!/bin/sh
# Pull a base model into the running ollama container and create the derived "cip-llm".
# Usage (as user deploy, inside `sudo stackctl shell --`):
#   BASE_MODEL=qwen2.5:3b-instruct THREADS=<THREADS> sh pull-and-create.sh
# The base model is chosen by the eval step (candidates: qwen2.5:3b-instruct, gemma3:4b,
# qwen2.5:7b-instruct). THREADS should match the --cpus limit of the unit.
set -eu
: "${BASE_MODEL:?set BASE_MODEL}"
: "${THREADS:?set THREADS}"
HERE="$(cd "$(dirname "$0")" && pwd)"
podman exec ollama ollama pull "$BASE_MODEL"
sed -e "s|@BASE_MODEL@|$BASE_MODEL|" -e "s|@THREADS@|$THREADS|" \
  "$HERE/Modelfile.cip-llm.template" | podman exec -i ollama sh -c 'cat > /tmp/Modelfile && ollama create cip-llm -f /tmp/Modelfile'
podman exec ollama ollama list