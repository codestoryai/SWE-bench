# Stage 1: Docker CLI/Engine
FROM --platform=linux/amd64 docker:dind AS docker_base

WORKDIR /app

# Install Python 3 and venv
RUN apk add --no-cache python3

# Create and activate virtual environment
RUN python3 -m venv venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy /swebench files after installing dependencies
COPY ./swebench ./swebench

# Start dockerd and your application
ENTRYPOINT ["dockerd-entrypoint.sh"]