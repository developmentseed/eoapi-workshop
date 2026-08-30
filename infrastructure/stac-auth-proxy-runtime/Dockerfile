ARG PYTHON_VERSION=3.13
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:${PYTHON_VERSION}

WORKDIR /tmp
COPY requirements.txt requirements.txt

RUN python -m pip install \
  --no-cache-dir \
  --disable-pip-version-check \
  --no-binary pydantic \
  --target /asset \
  -r requirements.txt

COPY src/ /asset/

CMD ["echo", "hello world"]
