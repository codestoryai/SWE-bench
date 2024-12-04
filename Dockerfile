# Stage 1: Docker CLI/Engine
FROM --platform=linux/amd64 docker:dind AS docker_base

WORKDIR /app

# Install Python 3 and venv
RUN apk add python3

# Install build dependencies
RUN apk add \
    cmake \
    make \
    gcc \
    g++ \
    musl-dev \
    python3-dev

COPY . .

RUN python3 -m venv venv
ENV PATH="/app/venv/bin:$PATH"

# Install dependencies
RUN pip3 install -r requirements.txt
RUN pip3 install -e .

# Start dockerd and your application
ENTRYPOINT ["dockerd-entrypoint.sh"]