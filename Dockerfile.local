FROM continuumio/miniconda3:latest

RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  build-essential \
  git \
  wget \
  ca-certificates \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

COPY environment.yml /tmp/environment.yml

RUN conda env create -f /tmp/environment.yml

RUN echo '#!/bin/bash \n\
  source activate eoapi-workshop \n\
  exec "$@"' > /entrypoint.sh && \
  chmod +x /entrypoint.sh

WORKDIR /home/jovyan
COPY docs ./docs
COPY README.md ./
COPY DEPLOYMENT.md ./

SHELL ["/bin/bash", "-c"]

RUN mkdir -p /home/jovyan/.jupyter

USER root
RUN useradd -m -s /bin/bash jovyan && \
  chown -R jovyan:jovyan /home/jovyan

USER jovyan

ENTRYPOINT ["/entrypoint.sh"]

CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''", "--NotebookApp.password=''"]
