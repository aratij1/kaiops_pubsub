FROM python:3.12-slim
WORKDIR /app
COPY fault_lab.py traffic_generator.py ./
COPY data ./data
RUN mkdir -p /app/runtime && useradd --system --uid 10001 kaiops && chown -R kaiops:kaiops /app
USER kaiops
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=2)"
ENTRYPOINT ["python", "fault_lab.py"]
