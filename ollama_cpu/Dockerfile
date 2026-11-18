FROM ubuntu:24.04 AS download

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl zstd \
    && rm -rf /var/lib/apt/lists/*
ARG TARGETARCH
RUN test "$TARGETARCH" = amd64
# Pin the release and its published SHA-256 together.
RUN curl --fail --location --retry 3 \
        https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-linux-amd64.tar.zst \
        --output /tmp/ollama.tar.zst \
    && echo "87bfafb2acbc89b2e6a1be0a9043de6aa75fb450696f86bc426e65fc448f788d  /tmp/ollama.tar.zst" | sha256sum --check \
    && mkdir /cpu \
    && tar --zstd -xf /tmp/ollama.tar.zst -C /cpu \
        --exclude='lib/ollama/cuda*' \
        --exclude='lib/ollama/rocm*' \
        --exclude='lib/ollama/vulkan*' \
        --exclude='lib/ollama/mlx*' \
        bin/ollama lib/ollama \
    && curl --fail --location --retry 3 \
        https://raw.githubusercontent.com/ollama/ollama/v0.40.16/LICENSE \
        --output /cpu/lib/ollama/OLLAMA_LICENSE \
    && rm /tmp/ollama.tar.zst

FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libopenblas0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=download /cpu/bin/ollama /usr/bin/ollama
COPY --from=download /cpu/lib/ollama /usr/lib/ollama
ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]
