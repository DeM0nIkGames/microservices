FROM python:3.6.15-slim-buster

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

ENV MODEL_ROOT=/data/models
ENV TORCH_HOME=/opt/torch-cache

WORKDIR /service

RUN sed -i \
        -e 's|deb.debian.org/debian|archive.debian.org/debian|g' \
        -e 's|security.debian.org/debian-security|archive.debian.org/debian-security|g' \
        -e '/buster-updates/d' \
        /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgomp1 \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade \
        pip==21.3.1 \
        setuptools==59.6.0 \
        wheel==0.37.1

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p "${MODEL_ROOT}" "${TORCH_HOME}"

RUN python -c "from torchvision.models import vgg19; vgg19(pretrained=True)"

EXPOSE 8000

VOLUME ["/data/models"]

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "300", "--bind", "0.0.0.0:8000", "app:create_app()"]