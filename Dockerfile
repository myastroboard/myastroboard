# syntax=docker/dockerfile:1.7
# =================================
# Builder stage
# =================================
FROM python:3.14.6-slim AS builder

# Build environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Set automatically by BuildKit (amd64 / arm64)
ARG TARGETARCH

# Build dependencies: all production wheels ship prebuilt (sgp4, cryptography,
# psutil, astropy, numpy, pandas, matplotlib, qh3/jh2 all publish cp314/abi3 wheels).
# The C/C++ compiler is only for the amd64 NumPy rebuild below.
RUN apt-get update && apt-get upgrade -y \
    && if [ "$TARGETARCH" = "amd64" ]; then \
         apt-get install -y --no-install-recommends gcc g++; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and build wheels
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --wheel-dir /wheels -r requirements.txt

# amd64: rebuild from source the packages whose PyPI wheels require an x86-64-v2 CPU
# (SSE4.2/POPCNT) and crash at import on VMs with a generic CPU model - e.g. Proxmox
# "kvm64", the default of the Home Assistant OS VM scripts. The cpu-compat workflow
# (scripts/check_cpu_compat.sh) flags any new offender; see CONTRIBUTING.md
# "CPU compatibility" before adding one here.
# NumPy: no baseline (its "min" is X86_V2 itself); it still picks its SSE4/AVX2/
# AVX-512 kernels at runtime on CPUs that have them. Other packages build with the
# compiler defaults, which target any x86-64 CPU.
# --no-cache-dir: pip's wheel cache ignores the -C settings and would silently reuse
# a wheel built with other options.
ARG REBUILD_FOR_OLD_CPUS="numpy"
RUN if [ "$TARGETARCH" = "amd64" ]; then \
      set -e; \
      for pkg in $REBUILD_FOR_OLD_CPUS; do \
        version=$(sed -n "s/^${pkg}===//Ip" requirements.txt); \
        [ -n "$version" ] || { echo "$pkg: no '${pkg}===' pin in requirements.txt"; exit 1; }; \
        wheel_name=$(echo "$pkg" | tr 'A-Z.-' 'a-z__'); \
        find /wheels -iname "${wheel_name}-*.whl" -delete; \
        extra=""; \
        if [ "$pkg" = "numpy" ]; then \
          extra="-Csetup-args=-Dcpu-baseline=none -Csetup-args=-Dallow-noblas=true"; \
        fi; \
        pip wheel --no-cache-dir --no-binary "$pkg" --no-deps --wheel-dir /wheels \
          "${pkg}==${version}" $extra; \
      done; \
    fi

# Minify static assets during build so production serves pre-minified files
COPY scripts/minify_static.py ./scripts/minify_static.py
COPY static/ ./static-src/
COPY requirements-build.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements-build.txt \
    && python ./scripts/minify_static.py ./static-src ./static-dist

# =================================
# Production stage
# =================================
FROM python:3.14.6-slim AS production

# Labels
LABEL maintainer="Gloup"
LABEL org.opencontainers.image.title="MyAstroBoard"
LABEL org.opencontainers.image.description="Self-hosted astronomy dashboard for observation planning and astrophotography"
LABEL org.opencontainers.image.url="https://github.com/myastroboard/myastroboard"
LABEL org.opencontainers.image.source="https://github.com/myastroboard/myastroboard"
LABEL org.opencontainers.image.licenses="AGPL-3.0"
LABEL org.opencontainers.image.vendor="WorldOfGZ"
LABEL org.opencontainers.image.documentation="https://github.com/myastroboard/myastroboard/tree/main/docs"

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install runtime dependencies
RUN set -eux; \
    apt-get update; \
    apt-get upgrade -y; \
    apt-get install -y --no-install-recommends \
       curl \
       ca-certificates \
       tzdata \
       passwd; \
    rm -rf /var/lib/apt/lists/* /tmp/* /usr/share/doc /usr/share/man/* /usr/share/info/*

# Copy wheels from builder and install
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels /root/.cache/pip

# Version file
COPY VERSION /app/VERSION

# Application code
COPY backend/ ./backend/
COPY templates/ ./templates/
COPY --from=builder /build/static-dist ./static/
# Picked up by gunicorn from the working directory: listen address (IPv4 + IPv6)
COPY gunicorn.conf.py ./gunicorn.conf.py

# Create non-root user
RUN useradd -m -u 1000 appuser

# Application directories
RUN mkdir -p /app/data && chown appuser:appuser /app/data


# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && sed -i 's/\r$//' /entrypoint.sh \
    && chown root:root /entrypoint.sh

# Expose port
EXPOSE 5000

# Native healthcheck: used by Home Assistant (no watchdog option) and plain docker run;
# docker-compose.yml overrides it with its own.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:5000/health || exit 1

# Entrypoint root -> fix perms -> drop user
ENTRYPOINT ["/entrypoint.sh"]

# Default command (listen address: gunicorn.conf.py)
CMD ["gunicorn", "-w", "2", "backend.app:app"]
