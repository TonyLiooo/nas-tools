# Use slim-bullseye as the base image
FROM python:3.11.10-slim-bookworm

# Copy S6 Overlay
COPY --from=shinsenter/s6-overlay / /

# Set environment variables
ENV PYTHONPATH=/usr/lib/python3/dist-packages/ \
    DEBIAN_FRONTEND="noninteractive" \
    S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SYNC_DISKS=1 \
    HOME="/nt" \
    TERM="xterm" \
    PATH=${PATH}:/usr/lib/chromium:/command \
    TZ="Asia/Shanghai" \
    NASTOOL_CONFIG="/config/config.yaml" \
    NASTOOL_AUTO_UPDATE=false \
    NASTOOL_CN_UPDATE=true \
    NASTOOL_VERSION=master \
    REPO_URL="https://github.com/TonyLiooo/nas-tools.git" \
    PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple" \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    PYTHONWARNINGS="ignore:semaphore_tracker:UserWarning" \
    WORKDIR="/nas-tools"

# Set the working directory
WORKDIR ${WORKDIR}

# Install dependencies
RUN set -xe && \
    apt-get update -y && \
    apt-get install -y wget bash build-essential && \ 
    apt-get install -y $(wget --no-check-certificate -qO- https://raw.githubusercontent.com/TonyLiooo/nas-tools/master/package_list_debian.txt) && \
    ln -sf /command/with-contenv /usr/bin/with-contenv && \
    ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime && \
    echo "${TZ}" > /etc/timezone && \
    locale-gen zh_CN.UTF-8 && \
    curl https://rclone.org/install.sh | bash && \
    if [ "$(uname -m)" = "x86_64" ]; then ARCH=amd64; elif [ "$(uname -m)" = "aarch64" ]; then ARCH=arm64; fi && \
    curl -L https://dl.min.io/client/mc/release/linux-${ARCH}/mc -o /usr/bin/mc && \
    chmod +x /usr/bin/mc && \
    pip install --upgrade pip setuptools wheel && \
    pip install cython && \
    pip install -r https://raw.githubusercontent.com/TonyLiooo/nas-tools/master/requirements.txt && \
    apt-get remove -y build-essential && \
    apt-get autoremove -y && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache /var/tmp/*

# Create user and group
RUN set -xe && \
    mkdir -p ${HOME} && \
    groupadd -r nt -g 911 && \
    useradd -r nt -g nt -d ${HOME} -s /bin/bash -u 911 && \
    python_ver=$(python3 -V | awk '{print $2}') && \
    echo "${WORKDIR}/" > /usr/local/lib/python${python_ver%.*}/site-packages/nas-tools.pth && \
    echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf && \
    echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf && \
    echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers && \
    git config --global pull.ff only && \
    git clone -b master ${REPO_URL} ${WORKDIR} --depth=1 --recurse-submodule && \
    git config --global --add safe.directory ${WORKDIR}

# Copy root filesystem
COPY --chmod=755 ./rootfs /

# Expose port
EXPOSE 3000

# Set volume for configuration
VOLUME [ "/config" ]

# Set entry point
ENTRYPOINT [ "/init" ]
