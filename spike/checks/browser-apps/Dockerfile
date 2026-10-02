# Headless Chromium for the browser-apps checks. The mcr image ships the
# browsers but not the Python package; the two versions must match.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
RUN pip install --no-cache-dir --break-system-packages playwright==1.55.0
