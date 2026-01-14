FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code
COPY src/ src/
COPY scripts/ scripts/

# Expose default port
EXPOSE 8000

# Set entrypoint to our new server
# We use the PATH environment variable to target the venv python directly
ENTRYPOINT ["python", "-m", "src.a2a_adapter.server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]