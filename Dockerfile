# EFDI TAK relay image.  Targets:
#   relay  the product: relay/ only                    docker build --target relay -t efdi-tak-relay .
#   demo   relay + demo/ (scenarios, live map, router)  docker build --target demo  -t efdi-tak-demo .
# Layout mirrors the repo (/opt/tak/relay, /opt/tak/demo) so imports work the same as natively.
FROM python:3.12-slim AS relay

# ffmpeg + mediamtx are used only when GATEWAY_VIDEO=1 (relay/video_relay.py). mediamtx is the RTSP
# server: ffmpeg's RTSP muxer has no listen mode. Version pinned to the one tested end-to-end.
ARG MEDIAMTX_VERSION=v1.21.1
# SHA256 from the release's checksums.sha256; change together with MEDIAMTX_VERSION.
ARG MEDIAMTX_SHA256_AMD64=653abc672a3e693f8d3b2717752492fdcfb8072291ec108d03d3dd857411b0ee
ARG MEDIAMTX_SHA256_ARM64=6a3aa635fb60ea9b8d566ec306f0a42ff1b6b52a3942bc2baffbe55880d4c3dd
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && arch="${TARGETARCH:-amd64}" \
    && case "$arch" in amd64) sum="$MEDIAMTX_SHA256_AMD64" ;; arm64) sum="$MEDIAMTX_SHA256_ARM64" ;; \
         *) echo "no mediamtx checksum for $arch" >&2; exit 1 ;; esac \
    && curl -fsSL -o /tmp/mediamtx.tar.gz \
       "https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_${arch}.tar.gz" \
    && echo "$sum  /tmp/mediamtx.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/mediamtx.tar.gz -C /usr/local/bin mediamtx \
    && rm /tmp/mediamtx.tar.gz

WORKDIR /opt/tak
COPY relay/requirements.txt relay/requirements.txt
RUN pip install --no-cache-dir -r relay/requirements.txt
COPY relay/ relay/

# Unprivileged runtime user. The mounted key must be readable by it (Docker Desktop bind
# mounts are; on Linux: chmod 640 + group 10001, or run with `user: "0"` in compose).
RUN useradd --system --uid 10001 --no-create-home tak
USER tak
ENV PYTHONUNBUFFERED=1
# Inside the container the HTTP port must listen on all interfaces for port publishing to work;
# docker-compose.yml publishes it on the host's 127.0.0.1 only.
ENV GATEWAY_HTTP_BIND=0.0.0.0
EXPOSE 8087 8088 6971/udp 8554
# /healthz is 200 only while the fabric link is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 CMD python3 -c \
  "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('GATEWAY_HTTP_PORT','8088'), timeout=4)"
CMD ["python3", "-u", "relay/tak_gateway.py"]

FROM relay AS demo
# Demo services (router, map, scenarios) have no /healthz.
HEALTHCHECK NONE
COPY demo/ demo/
CMD ["python3", "-u", "demo/live_map.py"]
