# Stage 1: Docker CLI/Engine
FROM docker:latest AS docker_base

# Stage 2: Python environment with venv
FROM python:3.9-slim AS python_base

# Install required system dependencies
RUN apt-get update && apt-get install -y \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY . .

# Create and activate virtual environment
RUN python -m venv venv
ENV PATH="/app/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Rust binary
FROM rust:latest AS rust_base

# Set working directory
WORKDIR /app

# Copy Rust source code and build
COPY path/to/rust/source .
RUN cargo build --release

# Final Stage: Combine all components
FROM docker_base

# Copy Python environment
COPY --from=python_base /app /app

# Copy Rust binary
COPY --from=rust_base /app/target/release/your_rust_binary /usr/local/bin/

# Set working directory
WORKDIR /app

# Set entrypoint
ENTRYPOINT ["./venv/bin/python", "your_entrypoint_script.py"]

