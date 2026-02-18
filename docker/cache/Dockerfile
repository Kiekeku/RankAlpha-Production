FROM redis:alpine3.20

# If you need a custom redis.conf, you can COPY and override redis as well:
# COPY redis.conf /usr/local/etc/redis/redis.conf
# CMD ["redis-server", "/usr/local/etc/redis/redis.conf"]

COPY redis-start.sh /usr/local/bin/redis-start.sh
RUN chmod +x /usr/local/bin/redis-start.sh
