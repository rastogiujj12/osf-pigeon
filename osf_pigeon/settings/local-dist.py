import os

DATACITE_USERNAME = os.environ.get("DATACITE_USERNAME")
DATACITE_PASSWORD = os.environ.get("DATACITE_PASSWORD")
OSF_BEARER_TOKEN = os.environ.get("OSF_BEARER_TOKEN")

# New tokens can be found at https://archive.org/account/s3.php
IA_ACCESS_KEY = os.environ.get("IA_ACCESS_KEY")
IA_SECRET_KEY = os.environ.get("IA_SECRET_KEY")

OSF_API_URL = "http://192.168.168.167:8000/"
OSF_FILES_URL = "http://192.168.168.167:7777/"
DATACITE_PREFIX = "10.70102"
DATACITE_URL = "https://mds.test.datacite.org/"
DOI_FORMAT = "{prefix}/fk2osf.io/{guid}"
OSF_COLLECTION_NAME = "cos-dev-sandbox"
ID_VERSION = "local_v1"

HOST = "0.0.0.0"
PORT = 2020
