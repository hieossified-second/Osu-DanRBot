FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

# Força o Python a imprimir os logs sem colocar em buffer
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "main.py"]