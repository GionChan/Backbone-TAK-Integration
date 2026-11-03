# EFDI TAK relay image.  Targets:
#   relay  the product: relay/ only                    docker build --target relay -t efdi-tak-relay .
#   demo   relay + demo/ (scenarios, live map, router)  docker build --target demo  -t efdi-tak-demo .
# Layout mirrors the repo (/opt/tak/relay, /opt/tak/demo) so imports work the same as natively.
FROM python:3.12-slim AS relay

# ffmpeg + mediamtx are used only when GATEWAY_VIDEO=1 (relay/video_relay.py). mediamtx is the RTSP
# server: ffmpeg's RTSP muxer has no listen mode. Version pinned to the one tested end-to-end.
ARG MEDIAMTX_VERSION=v1.21.1
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && arch="${TARGETARCH:-amd64}" \
    && curl -fsSL -o /tmp/mediamtx.tar.gz \
       "https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_${arch}.tar.gz" \
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
