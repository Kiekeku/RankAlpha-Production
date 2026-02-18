FROM atmoz/sftp:latest
# Add a lightweight TCP checker for healthchecks
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends netcat-openbsd \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*
USER root
COPY infra/sftp/sftp-init.sh /etc/sftp.d/init.sh
RUN chmod +x /etc/sftp.d/init.sh
