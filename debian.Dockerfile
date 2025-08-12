FROM python:3.12.8-slim-bookworm
COPY --from=shinsenter/s6-overlay / /
ENV DEBIAN_FRONTEND=noninteractive
COPY requirements.txt ./
COPY package_list_debian.txt ./
RUN set -xe && \
    echo "deb http://mirrors.ustc.edu.cn/debian/ bookworm main" > /etc/apt/sources.list && \
    echo "deb http://mirrors.ustc.edu.cn/debian/ bookworm-updates main" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.ustc.edu.cn/debian-security/ bookworm-security main" >> /etc/apt/sources.list && \
    apt-get update -y || (sleep 10 && apt-get update -y) && \
    apt-get install -y --no-install-recommends --fix-missing $(cat ./package_list_debian.txt) || \
    (apt-get update -y && apt-get install -y --no-install-recommends --fix-missing $(cat ./package_list_debian.txt)) && \
    apt-get install -y --no-install-recommends curl || \
    (sleep 30 && apt-get update -y && apt-get install -y --no-install-recommends curl) && \
    ln -sf /command/with-contenv /usr/bin/with-contenv && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    locale-gen zh_CN.UTF-8 && \
    curl https://rclone.org/install.sh | bash && \
    if [ "$(uname -m)" = "x86_64" ]; then ARCH=amd64; elif [ "$(uname -m)" = "aarch64" ]; then ARCH=arm64; fi && \
    curl -L https://dl.min.io/client/mc/release/linux-${ARCH}/mc -o /usr/bin/mc && \
    chmod +x /usr/bin/mc && \
    pip install --upgrade pip setuptools wheel && \
    pip install cython && \
    pip install -r ./requirements.txt && \
    apt-get remove -y build-essential && \
    apt-get autoremove -y && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache /var/tmp/*
ENV PYTHONPATH=/usr/local/lib/python3.12/site-packages \
    DEBIAN_FRONTEND="noninteractive" \
    S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SYNC_DISKS=1 \
    HOME="/nt" \
    TERM="xterm" \
    PATH=${PATH}:/usr/lib/chromium \
    LANG="C.UTF-8" \
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
WORKDIR ${WORKDIR}
RUN mkdir ${HOME} \
    && groupadd -r nt -g 911 \
    && useradd -r nt -g nt -d ${HOME} -s /bin/bash -u 911 \
    && python_ver=$(python3 -V | awk '{print $2}') \
    && python_path=$(which python3) \
    && [ -d "/usr/local/lib/python${python_ver%.*}/site-packages" ] || mkdir -p "/usr/local/lib/python${python_ver%.*}/site-packages" \
    && echo "${WORKDIR}/" > /usr/local/lib/python${python_ver%.*}/site-packages/nas-tools.pth \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && git config --global pull.ff only
COPY --chmod=755 . ${WORKDIR}/
RUN git config --global --add safe.directory ${WORKDIR}
COPY --chmod=755 ./docker/rootfs /
EXPOSE 3000
VOLUME [ "/config" ]
ENTRYPOINT [ "/init" ]
