ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
COPY --chown=10001:10001 registry-control/ /registry-control/
COPY --chown=10001:10001 aws-rds-global-bundle.pem /etc/ssl/certs/aws-rds-global-bundle.pem

ENV ML_CONTROL_DIR=/registry-control \
    ML_DB_SSLROOTCERT=/etc/ssl/certs/aws-rds-global-bundle.pem \
    PGSSLROOTCERT=/etc/ssl/certs/aws-rds-global-bundle.pem

USER appuser
