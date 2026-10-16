# OTAFIX build environment for Linux x86_64 and AArch64 hosts.
# Install both board-qualified releases for a mixed all-board build.
# ARM_GNU_RELEASE selects the compiler exposed directly on PATH.
# Initialize submodules and mount the checkout at /src; see README.md.
# Trixie's native sanitizer runtime avoids Bookworm's GCC 12 ASan startup
# failures on newer host kernels. This does not select the firmware compiler.
FROM debian:trixie-slim
ARG ARM_GNU_RELEASE=14.2.rel1
ARG ARM_GNU_INSTALL_BOTH=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      cmake \
      curl \
      xz-utils \
      python3 \
      python-is-python3 \
      python3-pip \
      python3-setuptools \
      nodejs \
      git \
      ca-certificates \
    && pip3 install --break-system-packages --no-cache-dir adafruit-nrfutil intelhex cryptography \
    && rm -rf /var/lib/apt/lists/*

# Hashes are from Arm's matching .tar.xz.sha256asc files. The newer release
# uses Arm's official GitLab package endpoint, not the retired downloads URL.
RUN set -eu; \
    toolchain_releases="${ARM_GNU_RELEASE:-14.2.rel1}"; \
    case "$toolchain_releases" in \
      14.2.rel1|15.3.rel1) ;; \
      *) echo "ARM_GNU_RELEASE must be 14.2.rel1 or 15.3.rel1" >&2; exit 1 ;; \
    esac; \
    case "${ARM_GNU_INSTALL_BOTH:-0}" in \
      0) ;; \
      1) toolchain_releases="14.2.rel1 15.3.rel1" ;; \
      *) echo "ARM_GNU_INSTALL_BOTH must be 0 or 1" >&2; exit 1 ;; \
    esac; \
    for toolchain_release in $toolchain_releases; do \
    case "$(dpkg --print-architecture)" in \
      amd64) toolchain_host=x86_64; \
        toolchain_sha256=62a63b981fe391a9cbad7ef51b17e49aeaa3e7b0d029b36ca1e9c3b2a9b78823 ;; \
      arm64) toolchain_host=aarch64; \
        toolchain_sha256=87330bab085dd8749d4ed0ad633674b9dc48b237b61069e3b481abd364d0a684 ;; \
      *) echo "Only linux/amd64 and linux/arm64 are supported" >&2; exit 1 ;; \
    esac; \
    case "$toolchain_release" in \
      14.2.rel1) toolchain_base="https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel" ;; \
      15.3.rel1) \
        toolchain_base="https://gitlab.arm.com/api/v4/projects/tooling%2Fgnu-toolchains-for-arm/packages/generic/gnu-toolchain/15.3.rel1"; \
        case "$toolchain_host" in \
          x86_64) toolchain_sha256=563bebb2b97d53382b956d6ee1fe61e2cae26699901417234a37df505ef9b5fa ;; \
          aarch64) toolchain_sha256=06979e0c8171de58e5dc2a2b2019330a290f30930f27728af98a83e1a7369b3a ;; \
        esac ;; \
      *) echo "ARM_GNU_RELEASE must be 14.2.rel1 or 15.3.rel1" >&2; exit 1 ;; \
    esac; \
    toolchain_archive="arm-gnu-toolchain-${toolchain_release}-${toolchain_host}-arm-none-eabi.tar.xz"; \
    curl --fail --show-error --location --retry 3 --connect-timeout 20 --max-time 300 \
      "${toolchain_base}/${toolchain_archive}" \
      --output /tmp/arm-gnu-toolchain.tar.xz; \
    printf '%s  %s\n' "$toolchain_sha256" /tmp/arm-gnu-toolchain.tar.xz | sha256sum --check -; \
    mkdir -p "/opt/arm-gnu-toolchains/$toolchain_release"; \
    tar -xJf /tmp/arm-gnu-toolchain.tar.xz -C "/opt/arm-gnu-toolchains/$toolchain_release" --strip-components=1; \
    rm /tmp/arm-gnu-toolchain.tar.xz; \
    done; \
    ln -s "/opt/arm-gnu-toolchains/$ARM_GNU_RELEASE" /opt/arm-gnu-toolchain

ENV PATH="/opt/arm-gnu-toolchain/bin:${PATH}"
ENV ARM_GNU_TOOLCHAIN_14_2="/opt/arm-gnu-toolchains/14.2.rel1"
ENV ARM_GNU_TOOLCHAIN_15_3="/opt/arm-gnu-toolchains/15.3.rel1"
# Fail during image creation if a CF2 or signed-DFU test dependency is missing.
RUN if [ "$ARM_GNU_RELEASE" = 15.3.rel1 ]; then \
      test "$(arm-none-eabi-gcc -dumpfullversion)" = 15.3.1; \
    else \
      test "$(arm-none-eabi-gcc -dumpfullversion)" = 14.2.1; \
    fi \
    && test "$(cc -dumpversion)" -ge 14 \
    && node --version \
    && python -c "import cryptography, intelhex"

WORKDIR /src
CMD ["make", "BOARD=wismesh_tag", "all"]
