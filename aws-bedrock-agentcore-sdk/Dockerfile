FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /app
# Environment variables
ENV PYTHONUNBUFFERED=1 \
    AWS_REGION=eu-west-1 \
    AWS_DEFAULT_REGION=eu-west-1

COPY requirements.txt .
# Install from requirements file
RUN python -m pip install --no-cache-dir -r requirements.txt
# Signal that this is running in Docker for host binding logic
ENV DOCKER_CONTAINER=1

ENV PYTHONUNBUFFERED=1
COPY agent.py .
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore
# AgentCore HTTP endpoint
EXPOSE 8080
# Health check using the /ping endpoint provided by AgentCore SDK
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=3)" || exit 1

# Run agent (no OpenTelemetry CLI dependency required)
CMD ["python", "agent.py"]