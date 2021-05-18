FROM python:3.6-slim-buster

RUN mkdir -p /code
WORKDIR /code

COPY requirements.txt /code/

RUN apt-get update \
    && apt-get install -y \
      python3-dev \
      gcc \
      musl-dev \
      libxslt-dev \
      libxml2 \
    && apt-get clean \
    && apt-get autoremove -y

RUN pip3 install --no-cache-dir -r /code/requirements.txt

# Install application into container
COPY . /code/

EXPOSE 2020

ENTRYPOINT ["python", "-m", "osf_pigeon"]
