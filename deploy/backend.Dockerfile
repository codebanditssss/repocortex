FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/models \
    HOST=0.0.0.0 \
    PORT=8765 \
    OMP_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false
WORKDIR /app

# Install CPU wheels first; ordinary torch wheels include large CUDA libraries.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml README.md LICENSE ./
COPY repocortex/ ./repocortex/
RUN pip install .
# Bake public model weights only. Runtime graph exports and credentials are mounted.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('sentence-transformers/all-MiniLM-L6-v2', ignore_patterns=['onnx/*', 'openvino/*', '*.h5', '*.ot', '*.msgpack'])"
ENV HF_HUB_OFFLINE=1
COPY scripts/serve_locate.py scripts/restore_graph.py ./scripts/
COPY results/graph.json ./results/graph.json
RUN mkdir -p /app/data

# Mount corpus.json, embeddings.npz, learned_state.json and learned_state.npz here.
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=25s --start-period=120s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/health', timeout=22).read()"
CMD ["python", "scripts/serve_locate.py"]

# Optional immutable demo target. Supply only these public exports in a staged context.
FROM base AS with-runtime
COPY runtime/corpus.json runtime/embeddings.npz runtime/learned_state.json runtime/learned_state.npz /app/data/

# Default image contains no runtime data. Use --target with-runtime for staged exports.
FROM base AS app
