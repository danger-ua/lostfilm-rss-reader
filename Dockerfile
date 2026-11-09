# Use a slim Python image
FROM python:3.12-alpine3.24

# Install system dependencies
RUN apk add --no-cache curl

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
