# Fathom: AVL documentation web app.
#
#   docker build -t fathom .
#   docker run -d -p 8080:8080 -v fathom-data:/data fathom
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
#                                     server-wide defaults for the UniFi discovery probe (per-project
#                                     settings in Discovery › Sources win)
#   FATHOM_DISCOVERY_INTERFACE        interface the LLDP listener and mDNS browser bind to (default: all)
#
# Network discovery (Discovery view) is passive and only runs when a user
# presses Run. For mDNS / LLDP / ARP to see the AV network the container must
# share the host's network namespace (`--network host`); the LLDP frame
# listener additionally needs CAP_NET_RAW (`--cap-add NET_RAW`). Without
# them only the UniFi controller probe has anything to report.

FROM python:3.12-slim

ARG WITH_PDF_TOOLS=true
ARG WITH_CHROMIUM=false
RUN set -e; pkgs=""; \
    if [ "$WITH_PDF_TOOLS" = "true" ]; then pkgs="$pkgs poppler-utils"; fi; \
    if [ "$WITH_CHROMIUM" = "true" ]; then pkgs="$pkgs chromium fonts-dejavu-core fonts-liberation"; fi; \
    if [ -n "$pkgs" ]; then \
      apt-get update && apt-get install -y --no-install-recommends $pkgs && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY pyproject.toml README.md ./
COPY fathom ./fathom
RUN pip install --no-cache-dir ".[serve,discovery]"

ENV FATHOM_DATA=/data \
    FATHOM_CHROME=/usr/bin/chromium \
    FATHOM_CHROME_NO_SANDBOX=1 \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"

# gunicorn: a couple of workers with threads; writes are serialized per project by a file lock
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "180", "--access-logfile", "-", "fathom.server:app"]
