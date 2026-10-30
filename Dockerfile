FROM python:3.10-slim-buster

WORKDIR /app

# ffmpeg এবং প্রয়োজনীয় টুল ইনস্টল করা হচ্ছে
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "main.py"]
