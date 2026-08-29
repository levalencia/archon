FROM python:3.11-slim@sha256:be1575ed968de893bd54f4c56315ff7c4736ce522c1bca08fd521731aafc0d76

WORKDIR /runner
COPY sandbox_runner /runner/sandbox_runner
RUN apt-get update \
 && apt-get install --yes --no-install-recommends libseccomp2 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 archon \
 && useradd --system --uid 10001 --gid archon --home-dir /nonexistent archon \
 && mkdir -p /run/archon-sandbox \
 && chown archon:archon /run/archon-sandbox
USER archon
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/runner
ENTRYPOINT ["python", "-m", "sandbox_runner.server"]
