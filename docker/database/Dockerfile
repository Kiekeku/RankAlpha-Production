# Dockerfile snippet
FROM postgres:17-alpine3.20

COPY init/*.sql /docker-entrypoint-initdb.d/

# --- optional but neat -------------------------------------------------
# set the database that psql in the init-scripts will connect to by default.
# Then you can drop the whole DO/CREATE DATABASE block if you like.
ENV POSTGRES_DB=rankalpha

EXPOSE 5432

# Copy *all* your bootstrap scripts, not just one
# COPY *.sql /docker-entrypoint-initdb.d/
