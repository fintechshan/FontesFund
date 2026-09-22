# Use the official Python 3.10 slim image
FROM python:3.10-slim

# Prevent Python from writing .pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1

# Prevent Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for compilation of scientific wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
    libopenblas-dev \
    liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency requirements
COPY requirements.txt .

# Upgrade pip; install CPU-only PyTorch (much smaller than the default CUDA wheel)
# first so transformers/FinBERT has a backend, then the rest of the deps.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download the FinBERT model at build time so it is baked into the image and
# the dashboard never has to fetch it at runtime (fast, reliable cold starts).
RUN python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
AutoTokenizer.from_pretrained('ProsusAI/finbert'); \
AutoModelForSequenceClassification.from_pretrained('ProsusAI/finbert')"

# Copy project files
COPY . .

# Render injects PORT (default 10000) and the app binds 0.0.0.0:$PORT.
# Local `python run_dashboard.py` still defaults to 8050 when PORT is unset.
EXPOSE 10000

# Launch the launcher script
CMD ["python", "run_dashboard.py"]
