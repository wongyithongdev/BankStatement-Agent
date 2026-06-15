FROM python:3.12-slim

RUN pip install --no-cache-dir pdfplumber openpyxl pandas

WORKDIR /workspace

# No entrypoint — scripts are passed as args by the agent harness
