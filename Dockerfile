FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
RUN useradd -r -u 10001 stride && mkdir /data && chown stride /data
USER stride
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.server:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
