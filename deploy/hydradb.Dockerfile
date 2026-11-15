FROM ghcr.io/hydra-db/hydradb:0.4.0
USER root
COPY deploy/start-hydradb.sh /usr/local/bin/start-repocortex-hydradb
ENV CLOUD_PROVIDER=local LOCAL_PATH=/data/store \
    GRAPH_NAMESPACE=default GRAPH_ID=default \
    GRAPH_CELL_ID=cell-0 GRAPH_CELLS=cell-0 GRAPH_NODE_ID=node-0 \
    GRAPH_DATA_CACHE_DIR=/data/cache GRAPH_DATA_CACHE_PART_BYTES=4194304 \
    GRAPH_DATA_CACHE_MAX_OPEN_FILES=512 GRAPH_AUTH_TOKEN_FILE=/data/auth-token \
    GRAPH_ALLOW_PLAINTEXT=true RUST_MIN_STACK=33554432 GRAPH_USAGE_REPORT_ENABLED=false
ENTRYPOINT ["sh", "/usr/local/bin/start-repocortex-hydradb"]
