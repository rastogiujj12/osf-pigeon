import re
import time
import json
import os
from io import BytesIO
from datetime import datetime
import internetarchive

import tempfile
import math
import asyncio
import requests

from typing import Tuple, Dict
from ratelimit import sleep_and_retry
from ratelimit.exception import RateLimitException
from datacite import DataCiteMDSClient

from osf_pigeon import settings
import zipfile
import bagit


def get_and_write_file_data_to_temp(url, temp_dir, dir_name):
    response = get_with_retry(url)
    with open(os.path.join(temp_dir, dir_name), 'wb') as fp:
        fp.write(response.content)


def get_and_write_json_to_temp(url, temp_dir, filename):
    pages = asyncio.run(get_paginated_data(url))
    with open(os.path.join(temp_dir, filename), 'w') as fp:
        fp.write(json.dumps(pages))


def bag_and_tag(
        temp_dir,
        guid,
        datacite_username=settings.DATACITE_USERNAME,
        datacite_password=settings.DATACITE_PASSWORD,
        datacite_prefix=settings.DATACITE_PREFIX):

    doi = build_doi(guid)
    xml_metadata = get_datacite_metadata(
        doi,
        datacite_username,
        datacite_password,
        datacite_prefix
    )

    with open(os.path.join(temp_dir, 'datacite.xml'), 'w') as fp:
        fp.write(xml_metadata)

    bagit.make_bag(temp_dir)
    bag = bagit.Bag(temp_dir)
    assert bag.is_valid()


def create_zip_data(temp_dir):
    zip_data = BytesIO()
    with zipfile.ZipFile(zip_data, "w") as zip_file:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                file_name = re.sub(f"^{temp_dir}", "", file_path)
                zip_file.write(file_path, arcname=file_name)
    zip_data.seek(0)
    return zip_data


def get_metadata(temp_dir, filename):
    with open(os.path.join(temp_dir, 'data', filename), 'r') as f:
        node_json = json.loads(f.read())['data']['attributes']

    date_string = node_json['date_created']
    date_string = date_string.partition('.')[0]
    date_time = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S")

    metadata = dict(
        title=node_json['title'],
        description=node_json['description'],
        date=date_time.strftime("%Y-%m-%d"),
        contributor='Center for Open Science',
    )

    article_doi = node_json['article_doi']
    if article_doi:
        metadata['external-identifier'] = f'urn:doi:{article_doi}'

    return metadata


def modify_metadata_with_retry(ia_item, metadata, retries=2, sleep_time=60):
    try:
        ia_item.modify_metadata(metadata)
    except internetarchive.exceptions.ItemLocateError as e:
        if 'Item cannot be located because it is dark' in str(e) and retries > 0:
            time.sleep(sleep_time)
            retries -= 1
            modify_metadata_with_retry(ia_item, metadata, retries, sleep_time)
        else:
            raise e


def main(
        guid,
        datacite_username=settings.DATACITE_USERNAME,
        datacite_password=settings.DATACITE_PASSWORD,
        datacite_prefix=settings.DATACITE_PREFIX,
        ia_access_key=settings.IA_ACCESS_KEY,
        ia_secret_key=settings.IA_SECRET_KEY):

    assert isinstance(ia_access_key, str), 'Internet Archive access key was not passed to pigeon'
    assert isinstance(ia_secret_key, str), 'Internet Archive secret key not passed to pigeon'

    with tempfile.TemporaryDirectory() as temp_dir:
        get_and_write_file_data_to_temp(
            f'{settings.OSF_FILES_URL}v1/resources/{guid}/providers/osfstorage/?zip=',
            temp_dir,
            'archived_files.zip'
        )
        get_and_write_json_to_temp(
            f'{settings.OSF_API_URL}v2/registrations/{guid}/wikis/',
            temp_dir,
            'wikis.json'
        )
        get_and_write_json_to_temp(
            f'{settings.OSF_API_URL}v2/registrations/{guid}/logs/',
            temp_dir,
            'logs.json'
        )
        get_and_write_json_to_temp(
            f'{settings.OSF_API_URL}v2/guids/{guid}',
            temp_dir,
            'registration.json'
        )

        bag_and_tag(
            temp_dir,
            guid,
            datacite_username=datacite_username,
            datacite_password=datacite_password,
            datacite_prefix=datacite_prefix
        )

        zip_data = create_zip_data(temp_dir)

        session = internetarchive.get_session(
            config={
                's3': {
                    'access': ia_access_key,
                    'secret': ia_secret_key
                }
            }
        )
        ia_item = session.get_item(guid)
        metadata = get_metadata(temp_dir, 'registration.json')

        ia_item.upload(
            {'bag.zip': zip_data},
            metadata=metadata,
            headers={'x-archive-meta01-collection': settings.OSF_COLLECTION_NAME},
            access_key=ia_access_key,
            secret_key=ia_secret_key,
        )
        modify_metadata_with_retry(ia_item, metadata)


def build_doi(guid):
    return settings.DOI_FORMAT.format(prefix=settings.DATACITE_PREFIX, guid=guid)


def get_datacite_metadata(doi, datacite_username, datacite_password, datacite_prefix):
    assert isinstance(datacite_password, str), 'Datacite password not passed to pigeon'
    assert isinstance(datacite_username, str), 'Datacite username not passed to pigeon'
    assert isinstance(datacite_prefix, str), 'Datacite prefix not passed to pigeon'
    client = DataCiteMDSClient(
        url=settings.DATACITE_URL,
        username=datacite_username,
        password=datacite_password,
        prefix=datacite_prefix,
    )
    return client.metadata_get(doi)


@sleep_and_retry
def get_with_retry(
        url,
        retry_on: Tuple[int] = (),
        sleep_period: int = None,
        headers: Dict = None) -> requests.Response:

    if not headers:
        headers = {}

    if not settings.OSF_USER_THROTTLE_ENABLED:
        assert settings.OSF_BEARER_TOKEN, \
            'must have OSF_BEARER_TOKEN set to disable the api user throttle of the OSF'
        headers['Authorization'] = settings.OSF_BEARER_TOKEN

    resp = requests.get(url, headers=headers)
    if resp.status_code in retry_on:
        raise RateLimitException(
            message='Too many requests, sleeping.',
            period_remaining=sleep_period or int(resp.headers.get('Retry-After') or 0)
        )  # This will be caught by @sleep_and_retry and retried
    resp.raise_for_status()

    return resp


async def get_pages(url, page, result={}):
    url = f'{url}?page={page}'
    resp = get_with_retry(url, retry_on=(429,))
    result[page] = resp.json()['data']
    return result


async def get_paginated_data(url):
    data = get_with_retry(url, retry_on=(429,)).json()

    tasks = []
    is_paginated = data.get('links', {}).get('next')

    if is_paginated:
        result = {1: data['data']}
        total = data['links'].get('meta', {}).get('total') or data['meta'].get('total')
        per_page = data['links'].get('meta', {}).get('per_page') or data['meta'].get('per_page')

        pages = math.ceil(int(total) / int(per_page))
        for i in range(1, pages):
            task = get_pages(url, i + 1, result)
            tasks.append(task)

        await asyncio.gather(*tasks)
        pages_as_list = []
        # through the magic of async all our pages have loaded.
        for page in list(result.values()):
            pages_as_list += page
        return pages_as_list
    else:
        return data
