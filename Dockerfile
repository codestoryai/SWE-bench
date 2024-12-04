# Stage 1: Docker CLI/Engine
FROM docker:dind AS docker_base

# Stage 2: Python environment with venv
FROM python:3.11.6-slim AS python_base

# Install required system dependencies
RUN apt-get update && apt-get install -y \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install requirements first
COPY requirements.txt .
RUN python3 -m venv venv && \
    . venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt

# Set venv in PATH for subsequent commands
ENV PATH="/app/venv/bin:$PATH"

# Copy /swebench files after installing dependencies
COPY ./swebench ./swebench

# # Stage 3: Rust binary
# FROM rust:latest AS rust_base

# # Set working directory
# WORKDIR /app

# # Copy Rust source code and build
# COPY path/to/rust/source .
# RUN cargo build --release

# Final Stage: Combine all components
FROM docker_base

# Copy Python environment
COPY --from=python_base /app /app

# # Copy Rust binary
# COPY --from=rust_base /app/target/release/your_rust_binary /usr/local/bin/

# Set working directory
WORKDIR /app

# Enable Docker daemon
ENV DOCKER_TLS_CERTDIR=""
ENV DOCKER_HOST="unix:///var/run/docker.sock"

# Start dockerd and your application
ENTRYPOINT ["dockerd-entrypoint.sh"]

# # Set entrypoint
# ENTRYPOINT ["./venv/bin/python", "your_entrypoint_script.py"]

# # Keep container running for development/debugging
# CMD ["tail", "-f", "/dev/null"]
