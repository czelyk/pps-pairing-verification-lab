FROM debian:trixie-slim@sha256:3a39a0592364683e6bab97937b72cad5a8fa6dcbbee90edb3bb48c7f8e94f258
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates cmake git python3 rsync && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v7.0.1 --recursive --shallow-submodules https://github.com/nasa/cFS.git /cfs && test "$(git -C /cfs rev-parse HEAD)" = 088b2fa828db9ff7e00733f1908e0eeb59f66ce3
RUN git init /sbn && git -C /sbn fetch --depth 1 https://github.com/nasa/SBN.git 387f660e9df62beaed51b88e093ceac789300b0d && git -C /sbn checkout --detach FETCH_HEAD
WORKDIR /cfs
COPY prepare.py /tmp/prepare.py
RUN python3 /tmp/prepare.py
