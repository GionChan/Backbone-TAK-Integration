# Edge-AI demo node image.  Build context = repo root:
#   docker compose --profile edge build
FROM python:3.12-slim

# vision stack; add onnxruntime here for EDGE_DETECTOR=onnx
RUN pip install --no-cache-dir \
        eclipse-zenoh==1.9.0 \
        "numpy>=1.26" \
        "pillow>=10"
# RUN pip install --no-cache-dir "onnxruntime>=1.17"

WORKDIR /app
COPY demo/edge_ai/ /app/
# shared with the relay: mandatory heartbeat + bundle/org discovery
COPY relay/heartbeat.py relay/identity.py /app/
RUN useradd --system --uid 10001 --no-create-home tak
USER tak

# edge_node.py (default), frame_publisher.py, or api_gateway.py via compose command
CMD ["python3", "-u", "edge_node.py"]
