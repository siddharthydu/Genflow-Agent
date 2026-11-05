FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PLAYWRIGHT_BROWSERS_PATH=/opt/genflow-browsers
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg xvfb x11vnc novnc websockify fluxbox supervisor ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/genflow-venv
ENV PATH=/opt/genflow-venv/bin:$PATH
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && python -m playwright install --with-deps chromium && chmod -R a+rX /opt/genflow-browsers
COPY backend/genflow /app/genflow
COPY deploy/supervisord.conf /etc/supervisor/conf.d/genflow.conf
RUN useradd --create-home --uid 10001 genflow && mkdir -p /data /tmp/genflow-supervisor && chown -R genflow:genflow /data /app /tmp/genflow-supervisor
ENV GENFLOW_DATA=/data DISPLAY=:99 PYTHONUNBUFFERED=1
USER genflow
EXPOSE 8080 6080
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/genflow.conf"]
