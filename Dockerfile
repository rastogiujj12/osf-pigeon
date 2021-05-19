FROM python:3.6-slim-buster

# Install requirements
COPY requirements.txt .
RUN apk add --no-cache --virtual .build-deps \
      alpine-sdk \
      musl-dev \
      libxslt-dev \
      libxml2 \
  && pip install -r requirements.txt \
  && apk del .build-deps


# Install application into container
COPY . .

ENTRYPOINT ["python", "-m", "osf_pigeon"]
