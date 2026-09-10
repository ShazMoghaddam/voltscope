FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY voltscope ./voltscope
COPY extract.py .

# SQLite lives on a mounted volume in production so it survives restarts.
ENV VOLTSCOPE_DB=/data/voltscope.db
EXPOSE 8000

# Shell form so $PORT (set by most PaaS, including Render) is expanded.
CMD uvicorn --factory voltscope.api.app:get_app --host 0.0.0.0 --port ${PORT:-8000}
