FROM ubuntu:22.04

SHELL ["/bin/bash", "-c"]
RUN apt-get update -q && \
    apt-get install -y \
    wget curl gnupg unzip software-properties-common python3-distutils python3-pip python3-apt python3-dev iputils-ping && \
    apt-get clean -q && rm -rf /var/lib/apt/lists/*

# Install MongoDB
ARG DEBIAN_FRONTEND=noninteractive
RUN curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
    gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg \
    --dearmor
RUN echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/6.0 multiverse" | tee /etc/apt/sources.list.d/mongodb-org-6.0.list
RUN apt-get update -q && \
    apt-get install -y mongodb-org=6.0.4 mongodb-org-database=6.0.4 mongodb-org-server=6.0.4 mongodb-org-mongos=6.0.4 mongodb-org-tools=6.0.4 && \
    apt-get clean -q && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /data/db

# Install LaTeX
RUN apt-get update -q && \
    apt-get install -y \
    texlive-latex-base texlive-fonts-recommended texlive-fonts-extra dvipng cm-super && \
    apt-get clean -q && rm -rf /var/lib/apt/lists/*

# Install Python Dependencies
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt
RUN rm requirements.txt

WORKDIR /
COPY entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
