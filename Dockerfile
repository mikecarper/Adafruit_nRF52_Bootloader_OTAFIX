# OTAFIX build environment for Linux x86_64 and AArch64 hosts.
# Keep the release toolchain at Arm GNU 14.2.Rel1, not Debian's older GCC.
# Initialize submodules and mount the checkout at /src; see README.md.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      cmake \
      curl \
      xz-utils \
      python3 \
      python-is-python3 \
      python3-pip \
      python3-setuptools \
      git \
      ca-certificates \
    && pip3 install --break-system-packages --no-cache-dir adafruit-nrfutil intelhex \
    && rm -rf /var/lib/apt/lists/*

# Hashes are from Arm's matching .tar.xz.sha256asc files at the URL below.
RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
      amd64) toolchain_host=x86_64; \
        toolchain_sha256=62a63b981fe391a9cbad7ef51b17e49aeaa3e7b0d029b36ca1e9c3b2a9b78823 ;; \
      arm64) toolchain_host=aarch64; \
        toolchain_sha256=87330bab085dd8749d4ed0ad633674b9dc48b237b61069e3b481abd364d0a684 ;; \
      *) echo "Only linux/amd64 and linux/arm64 are supported" >&2; exit 1 ;; \
    esac; \
    toolchain_archive="arm-gnu-toolchain-14.2.rel1-${toolchain_host}-arm-none-eabi.tar.xz"; \
    curl --fail --show-error --location --retry 3 --connect-timeout 20 --max-time 300 \
      "https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel/${toolchain_archive}" \
      --output /tmp/arm-gnu-toolchain.tar.xz; \
    printf '%s  %s\n' "$toolchain_sha256" /tmp/arm-gnu-toolchain.tar.xz | sha256sum --check -; \
    mkdir -p /opt/arm-gnu-toolchain; \
    tar -xJf /tmp/arm-gnu-toolchain.tar.xz -C /opt/arm-gnu-toolchain --strip-components=1; \
    rm /tmp/arm-gnu-toolchain.tar.xz

ENV PATH="/opt/arm-gnu-toolchain/bin:${PATH}"
RUN test "$(arm-none-eabi-gcc -dumpfullversion)" = 14.2.1

WORKDIR /src
CMD ["make", "BOARD=wismesh_tag", "all"]
