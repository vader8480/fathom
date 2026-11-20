# Fathom: AVL documentation web app.
#
#   docker build -t fathom .
#   docker run -d -p 8080:8080 -v fathom-data:/data fathom
#
# Multi-arch (what .github/workflows/publish.yml pushes to ghcr.io/vader8480/fathom):
#   docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -t fathom .
# Kubernetes: deploy/helm/fathom (Helm chart, k3s on Raspberry Pi quick start in its README).
#
# The server runs as the unprivileged user `fathom` (uid/gid 10001) and writes
# only to /data and /tmp, so the root filesystem can be read-only. A /data
# volume written by an older image that ran as root needs its owner changed once:
#   docker run --rm -u 0 -v fathom-data:/data fathom chown -R 10001:10001 /data
#
# Floor-plan PDFs are rasterized with poppler-utils (pdftoppm), installed by
# default. Skip it with --build-arg WITH_PDF_TOOLS=false (PDF uploads then
# answer 422 with guidance).
#
# Server-side PDF / PNG export of builds needs Chromium (adds ~300 MB). Opt in with:
#   docker build --build-arg WITH_CHROMIUM=true -t fathom .
# Without it the viewer's Print / PDF button still works in the browser.
#
# Runtime settings (all optional):
#   FATHOM_AUTH="user:pass[,u2:p2]"   in-memory admin logins (or add users with `fathom user add`)
#   FATHOM_PUBLIC_VIEW=1              keep /p/* viewer pages and builds public when auth is on
#   FATHOM_PUBLIC_URL=https://av.example.org   base URL encoded in device QR codes
#   FATHOM_MAX_UPLOAD_MB=50 / FATHOM_MAX_JSON_MB=20   request body caps
#   FATHOM_MAX_BACKUP_MB=4096         largest backup zip accepted by upload-and-restore
#   FATHOM_LLM_URL / FATHOM_LLM_MODEL / FATHOM_LLM_API_KEY / FATHOM_LLM_TIMEOUT / FATHOM_LLM_MAX_CONTEXT
#                                     optional OpenAI-compatible bridge for assistant notes
#   FATHOM_PLUGINS / FATHOM_LIBRARY / FATHOM_CHECKLISTS   extension directories (os.pathsep-separated)
#   FATHOM_PDF_RASTERIZER, FATHOM_ODA, FATHOM_ODA_XVFB    floor-plan converters
#   FATHOM_UNIFI_URL / FATHOM_UNIFI_SITE / FATHOM_UNIFI_API_KEY (or _USER / _PASSWORD) / FATHOM_UNIFI_VERIFY_TLS
#   FATHOM_DISCOVERY_INTERFACE        network discovery defaults (per-project settings win)
#
# The container is optional: the reference deployment is an Ubuntu VM with
# deploy/fathom.service (README › Running on Ubuntu). Passive discovery probes
# (mDNS, LLDP, ARP) only see the container's network unless it shares the host's.
# The LLDP / CDP listener also needs CAP_NET_RAW, which a non-root process only
# gets from a file capability: /usr/local/bin/python-netraw is a copy of the
# interpreter that carries cap_net_raw. Start the server through it, e.g.
#   docker run --network host fathom \
#     python-netraw -m gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 4 --timeout 180 \
#       --worker-tmp-dir /dev/shm --access-logfile - fathom.server:app
# NET_RAW is in Docker's default capability set; where capabilities are dropped
# (--cap-drop ALL, the Helm chart) add it back (--cap-add NET_RAW), otherwise
# python-netraw refuses to start (EPERM). The default command does not use it,
# so the server holds no capabilities unless it is started this way.

ARG PYTHON_IMAGE=python:3.12-slim

# Installs into /install so the runtime image gets site-packages and the
# console scripts without the source tree or pip's build leftovers.
FROM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY fathom ./fathom
RUN pip install --no-cache-dir --prefix=/install ".[serve,discovery]"

FROM ${PYTHON_IMAGE}

ARG WITH_PDF_TOOLS=true
ARG WITH_CHROMIUM=false
RUN set -e; pkgs="libcap2-bin"; \
    if [ "$WITH_PDF_TOOLS" = "true" ]; then pkgs="$pkgs poppler-utils"; fi; \
    if [ "$WITH_CHROMIUM" = "true" ]; then pkgs="$pkgs chromium fonts-dejavu-core fonts-liberation"; fi; \
    apt-get update && apt-get install -y --no-install-recommends $pkgs; \
    cp "$(readlink -f /usr/local/bin/python3)" /usr/local/bin/python-netraw; \
    setcap cap_net_raw+ep /usr/local/bin/python-netraw; \
    apt-get purge -y libcap2-bin && rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 10001 fathom; \
    useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin fathom; \
    install -d -o 10001 -g 10001 -m 0750 /data

COPY --from=build /install /usr/local

# USER (the name) lets `fathom backup create` and friends resolve an author
# even when the container is started with a uid that has no passwd entry.
ENV FATHOM_DATA=/data \
    FATHOM_CHROME=/usr/bin/chromium \
    FATHOM_CHROME_NO_SANDBOX=1 \
    PYTHONUNBUFFERED=1 \
    USER=fathom \
    HOME=/tmp
USER 10001:10001
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"

# gunicorn: a couple of workers with threads; writes are serialized per project by a file lock.
# The worker heartbeat file lives in /dev/shm (always tmpfs) so a slow SD card or a read-only
# root filesystem cannot stall it.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "180", "--worker-tmp-dir", "/dev/shm", "--access-logfile", "-", "fathom.server:app"]
