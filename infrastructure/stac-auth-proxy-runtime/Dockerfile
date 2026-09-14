# Built with the repository root as context, so the row-level authorization filter in
# docs/ can be copied in verbatim rather than duplicated here. See the
# `Code.from_docker_build` call in infrastructure/app.py.
ARG PYTHON_VERSION=3.13
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:${PYTHON_VERSION}

WORKDIR /tmp
COPY infrastructure/stac-auth-proxy-runtime/requirements.txt requirements.txt

RUN python -m pip install \
  --no-cache-dir \
  --disable-pip-version-check \
  --no-binary pydantic \
  --target /asset \
  -r requirements.txt

COPY infrastructure/stac-auth-proxy-runtime/src/ /asset/

# The same filter module the local compose stack mounts into the proxy container.
# /asset becomes /var/task, which is on sys.path, so this is importable as
# `workshop_filters` -- matching ITEMS_FILTER_CLS / COLLECTIONS_FILTER_CLS.
COPY docs/workshop_filters.py /asset/

CMD ["echo", "hello world"]
