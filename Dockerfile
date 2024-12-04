FROM --platform=linux/amd64 python:3.11.6

# Set working directory
WORKDIR /app

# Create venv
RUN python3 -m venv venv

# Copy only requirements first to leverage caching
COPY requirements.txt .

# Install dependencies
RUN . venv/bin/activate && \
    pip3 install --upgrade pip && \
    pip3 install -r requirements.txt

# Copy the rest of the application
COPY . .

# Install the package in editable mode
RUN . venv/bin/activate && \
    pip3 install -e .

ENTRYPOINT ["tail", "-f", "/dev/null"]