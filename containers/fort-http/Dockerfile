FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl nmap netcat-openbsd procps iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Flag — random per build
RUN python3 -c "import secrets; print(f'CTF{{alpha_fortress_{secrets.token_hex(8)}}}')" > /flag.txt \
    && chmod 600 /flag.txt

RUN mkdir -p /app/files && echo "Welcome to Fort HTTP file server" > /app/files/readme.txt

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
