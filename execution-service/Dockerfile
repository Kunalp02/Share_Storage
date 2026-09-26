FROM python:3.12-slim
WORKDIR /app
COPY platform-auth /tmp/platform-auth
RUN pip install --no-cache-dir /tmp/platform-auth
COPY execution-service/pyproject.toml execution-service/README.md ./
COPY execution-service/src ./src
RUN pip install --no-cache-dir .
EXPOSE 8765
CMD ["agent-execution"]
