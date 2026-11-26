# Ollama for CIP (internal LLM, CPU)

Small local model behind the CIP RAG chat. Answers come only from retrieved RAG context;
on Ollama error/timeout the API falls back to extractive synthesis (`LLM_PROVIDER=local`).

Files: `ollama.container`, `cip-llm.network`, `ollama-models.volume`,
`Modelfile.cip-llm.template`, `pull-and-create.sh`, `cip.env.ollama.example`.

## Open points (user decision)

- **CPU and memory limits** (`@CPUS@`, `@MEMORY@`) and `THREADS` are not decided. The VPS is
  shared with CloudPilot (12 vCPU, ~28 GB available, load avg ~5-6, no GPU). Pick values
  after the eval step measures latency per model.
- Base model (eval step decides).
- Image tag `0.40.18` is the latest GitHub release at the time of writing; confirm the tag
  exists on Docker Hub at pull time.

## Pre-checks (read-only, on the VPS)

```sh
# cpu and memory must be listed, otherwise --cpus/--memory are ignored in rootless:
cat /sys/fs/cgroup/user.slice/user-$(id -u deploy).slice/user@$(id -u deploy).service/cgroup.controllers
df -h; uptime
```

## Render the unit

```sh
sed -e 's|@CPUS@|<CPUS>|' -e 's|@MEMORY@|<MEMORY>|' ollama.container > /tmp/ollama.container
```

## Install (later deployment step; not run by the code change)

```sh
# as user deploy via `sudo stackctl shell --`
cp /tmp/ollama.container cip-llm.network ollama-models.volume /home/deploy/.config/containers/systemd/
systemctl --user daemon-reload
stackctl start ollama
BASE_MODEL=<model> THREADS=<THREADS> sh pull-and-create.sh      # model pull + derived cip-llm
```

Patch `cip-api.container` (add to the existing file; do not replace it):

```ini
[Unit]
After=ollama.service          # in addition to the existing After=
[Container]
Network=cip-llm.network       # in addition to Network=cloudpilot.network
```

Then append `cip.env.ollama.example` keys to `cip.env` (remove MiniMax/DeepSeek keys), and
`stackctl restart cip-api`. Check `stackctl logs ollama` and `stackctl healthcheck`.

## Verify

```sh
podman exec cip-api curl -fsS http://ollama:11434/v1/models
```

Look for `llm_fallback_extractive` in `stackctl logs cip-api`: occasional entries are expected;
many mean timeouts are too tight or the model is overloaded.

## Roll back

Set `LLM_PROVIDER=extractive` in `cip.env`, `stackctl restart cip-api`, then
`stackctl stop ollama`. The volume keeps the models.
