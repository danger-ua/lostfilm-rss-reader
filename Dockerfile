# Use a slim Python image
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:${PATH}"

# Set the working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
COPY README.md ./

# Install dependencies using uv
RUN uv sync --frozen

# Default command to run the scheduler
# Use environment variables for UID and USESS
CMD ["uv", "run", "python", "-m", "lostfilm", "scheduler"]
