FROM --platform=linux/amd64 python:3.11.6

# Set working directory
WORKDIR /app

# Create venv
RUN python3 -m venv venv

# Copy all files
COPY . .

# Activate venv and install dependencies
RUN source venv/bin/activate && \
    pip3 install --upgrade pip && \
    pip3 install -r requirements.txt && \
    pip3 install -e .

# Keep container running for development/debugging
CMD ["tail", "-f", "/dev/null"]
