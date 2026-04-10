FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl nmap netcat-openbsd procps iputils-ping python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json .
RUN npm install --production

COPY app.js .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Flag — random per build
RUN node -e "const c=require('crypto');console.log('CTF{bravo_fortress_'+c.randomBytes(8).toString('hex')+'}')" > /flag.txt \
    && chmod 600 /flag.txt

RUN mkdir -p /app/files && echo "Welcome to Fort SSH file server" > /app/files/readme.txt

EXPOSE 9090
ENTRYPOINT ["/entrypoint.sh"]
