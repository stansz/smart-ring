FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Drop privileges inside the container. This is a rootless Podman
# deployment: container uid 0 maps to the host service account (sz), and
# container uid 1000 maps into the subuid range while carrying the host
# GID (sz) — so the bind mounts (/app, /dashboard, /garmin-raw, all
# sz:sz 775) stay writable. Verified empirically before shipping.
USER 1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1

# No --reload in production. Code changes on the host mounts require a
# container restart (sudo systemctl restart smart-ring-api), matching the
# documented workflow in docs/RUNTIME.md.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
