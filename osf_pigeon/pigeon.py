import re
import json
import os
from io import BytesIO
from datetime import datetime
import internetarchive
from asyncio import events

import tempfile
import math
import asyncio
import requests

from datacite import DataCiteMDSClient
from datacite.errors import DataCiteNotFoundError

from osf_pigeon import settings
import zipfile
import bagit
from ratelimit import sleep_and_retry
from ratelimit.exception import RateLimitException
from sanic.exceptions import SanicException

REG_ID_TEMPLATE = f"osf-registrations-{{guid}}-{settings.ID_VERSION}"
PROVIDER_ID_TEMPLATE = (
    f"collection-osf-registration-providers-{{guid}}-{settings.ID_VERSION}"
)


def get_and_write_file_data_to_temp(from_url, to_dir, name):
    with get_with_retry(from_url) as response:
        with open(os.path.join(to_dir, name), "wb") as fp:
            for chunk in response.iter_content():
                fp.write(chunk)


async def get_and_write_json_to_temp(from_url, to_dir, name, parse_json=None):
    pages = await get_paginated_data(from_url, parse_json)
    with open(os.path.join(to_dir, name), "w") as fp:
        json.dump(pages, fp)

    return pages


def create_zip_data(temp_dir):
    zip_data = BytesIO()
    zip_data.name = "bag.zip"
    with zipfile.ZipFile(zip_data, "w") as fp:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                file_name = re.sub(f"^{temp_dir}", "", file_path)
                fp.write(file_path, arcname=file_name)
    zip_data.seek(0)
    return zip_data


async def get_relationship_attribute(key, url, func):
    return {key: list(map(func, (await get_paginated_data(url))["data"]))}


async def get_metadata_for_ia_item(json_metadata):
    """
    This is meant to take the response JSON metadata and format it for IA buckets, this is not
    used to generate JSON to be uploaded as raw data into the buckets.
    :param json_metadata: metadata from OSF registration view contains attributes and relationship
    urls.

    Note: Internet Archive advises that all metadata that points to internal OSF features should have a specific `osf_`
    prefix. Example: `registry` should be `osf_registry`, however metadata such as affiliated_institutions is
    self-explanatory and doesn't need a prefix.

    :return: ia_metadata the metadata for an IA bucket. Should include the following if they are
     not null:
        - publisher
        - title
        - description
        - date
        - osf_category
        - osf_subjects
        - osf_tags
        - osf_registration_doi
        - osf_registry
        - osf_registration_schema
        - creator (biblographic contributors, IA recommended this keyword)
        - article_doi
        - parent
        - children
        - source
        - affiliated_institutions
        - license
    """
    relationship_data = [
        get_relationship_attribute(
            "creator",
            f'{settings.OSF_API_URL}v2/registrations/{json_metadata["data"]["id"]}/contributors/?filter[bibliographic]=true',
            lambda contrib: contrib["embeds"]["users"]["data"]["attributes"][
                "full_name"
            ],
        ),
        get_relationship_attribute(
            "affiliated_institutions",
            f'{settings.OSF_API_URL}v2/registrations/{json_metadata["data"]["id"]}/institutions/',
            lambda institution: institution["attributes"]["name"],
        ),
        get_relationship_attribute(
            "osf_subjects",
            f'{settings.OSF_API_URL}v2/registrations/{json_metadata["data"]["id"]}/subjects/',
            lambda subject: subject["attributes"]["text"],
        ),
        get_relationship_attribute(
            "children",
            f'{settings.OSF_API_URL}v2/registrations/{json_metadata["data"]["id"]}/children/',
            lambda child: f'https://archive.org/details/{REG_ID_TEMPLATE.format(guid=child["id"])}',
        ),
    ]

    relationship_data = {
        k: v
        for pair in await asyncio.gather(*relationship_data)
        for k, v in pair.items()
    }  # merge all the pairs

    parent = json_metadata["data"]["relationships"]["parent"]["data"]
    if parent:
        relationship_data[
            "parent"
        ] = f"https://archive.org/details/{REG_ID_TEMPLATE.format(guid=parent['id'])}"

    embeds = json_metadata["data"]["embeds"]

    if not embeds["license"].get("errors"):  # Fix me
        relationship_data["license"] = embeds["license"]["data"]["attributes"]["url"]

    doi = next(
        (
            identifier["attributes"]["value"]
            for identifier in embeds["identifiers"]["data"]
            if identifier["attributes"]["category"] == "doi"
        ),
        None,
    )
    osf_url = "/".join(json_metadata["data"]["links"]["html"].split("/")[:3]) + "/"

    attributes = json_metadata["data"]["attributes"]
    article_doi = json_metadata["data"]["attributes"]["article_doi"]
    ia_metadata = {
        "publisher": "Center for Open Science",
        "osf_registration_doi": doi,
        "title": attributes["title"],
        "description": attributes["description"],
        "osf_category": attributes["category"],
        "osf_tags": attributes["tags"],
        "date": str(
            datetime.strptime(
                attributes["date_created"], "%Y-%m-%dT%H:%M:%S.%fZ"
            ).date()
        ),
        "article_doi": f"urn:doi:{article_doi}" if article_doi else "",
        "osf_registry": embeds["provider"]["data"]["attributes"]["name"],
        "osf_registration_schema": embeds["registration_schema"]["data"]["attributes"][
            "name"
        ],
        "source": osf_url
        + json_metadata["data"]["relationships"]["registered_from"]["data"]["id"],
        **relationship_data,
    }
    return ia_metadata


async def write_datacite_metadata(guid, temp_dir, metadata):

    try:
        doi = next(
            (
                identifier["attributes"]["value"]
                for identifier in metadata["data"]["embeds"]["identifiers"]["data"]
                if identifier["attributes"]["category"] == "doi"
            )
        )
    except StopIteration:
        raise DataCiteNotFoundError(
            f"Datacite DOI not found for registration {guid} on OSF server."
        )

    client = DataCiteMDSClient(
        url=settings.DATACITE_URL,
        username=settings.DATACITE_USERNAME,
        password=settings.DATACITE_PASSWORD,
        prefix=settings.DATACITE_PREFIX,
    )

    try:
        xml_metadata = client.metadata_get(doi)
    except DataCiteNotFoundError:
        raise DataCiteNotFoundError(
            f"Datacite DOI {doi} not found for registration {guid} on Datacite server."
        )

    with open(os.path.join(temp_dir, "datacite.xml"), "w") as fp:
        fp.write(xml_metadata)

    return xml_metadata


@sleep_and_retry
def get_with_retry(url, retry_on=(), sleep_period=None, headers=None):
    if not headers:
        headers = {}

    if settings.OSF_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {settings.OSF_BEARER_TOKEN}"

    resp = requests.get(url, headers=headers, stream=True)
    if resp.status_code in retry_on:
        raise RateLimitException(
            message="Too many requests, sleeping.",
            period_remaining=sleep_period or int(resp.headers.get("Retry-After") or 0),
        )  # This will be caught by @sleep_and_retry and retried
    resp.raise_for_status()

    return resp


async def get_pages(url, page, result={}, parse_json=None):
    url = f"{url}?page={page}&page={page}"
    resp = get_with_retry(url, retry_on=(429,))

    result[page] = resp.json()["data"]

    if parse_json:
        result[page] = parse_json(resp.json())["data"]

    return result


def get_contributors(response):
    contributor_data_list = []
    for contributor in response["data"]:
        contributor_data = {}
        embed_data = contributor["embeds"]["users"]["data"]
        institution_url = embed_data["relationships"]["institutions"]["links"][
            "related"
        ]["href"]
        institution_response = get_with_retry(institution_url, retry_on=(429,))
        institution_data = institution_response.json()["data"]
        institution_list = [
            institution["attributes"]["name"] for institution in institution_data
        ]
        contributor_data["affiliated_institutions"] = institution_list
        contributor.update(contributor_data)
        contributor_data_list.append(contributor)
    response["data"] = contributor_data_list
    return response


async def get_paginated_data(url, parse_json=None):
    data = get_with_retry(url, retry_on=(429,)).json()

    tasks = []
    is_paginated = data.get("links", {}).get("next")

    if parse_json:
        data = parse_json(data)

    if is_paginated:
        result = {1: data["data"]}
        total = data["links"].get("meta", {}).get("total") or data["meta"].get("total")
        per_page = data["links"].get("meta", {}).get("per_page") or data["meta"].get(
            "per_page"
        )

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


def get_ia_item(guid):
    session = internetarchive.get_session(
        config={
            "s3": {"access": settings.IA_ACCESS_KEY, "secret": settings.IA_SECRET_KEY},
        },
    )
    return session.get_item(guid)


def sync_metadata(guid, metadata):
    """
    This is used to sync the metadata of archive.org items with OSF Registrations. The OSF metadata actively being
    synced is as follows:
        - title
        - description
        - date
        - category
        - subjects
        - tags
        - affiliated_institutions
        - license
        - article_doi

    `moderation_state` is an allowable key, but only to determine a withdrawal status of a registration.
    :param guid:
    :param metadata:
    :return:
    """

    if not metadata:
        return

    valid_updatable_metadata_keys = [
        "title",
        "description",
        "date",
        "modified",
        "category",
        "subjects",
        "tags",
        "article_doi",
        "affiliated_institutions",
        "license",
        "moderation_state",
    ]

    invalid_keys = set(metadata.keys()).difference(set(valid_updatable_metadata_keys))
    if invalid_keys:
        raise SanicException(
            f"Metadata payload contained invalid tag(s): `{', '.join(list(invalid_keys))}`"
            f" not included in valid keys: `{', '.join(valid_updatable_metadata_keys)}`.",
            status_code=400,
        )

    # remap these with `osf_` prefix for IA
    keys = [
        "category",
        "subjects",
        "tags",
        "article_doi",
    ]
    for key in keys:
        if key in metadata:
            metadata[f"osf_{key}"] = metadata.pop(key)

    item_name = REG_ID_TEMPLATE.format(guid=guid)
    ia_item = get_ia_item(item_name)
    if (
        not metadata.get("moderation_state") == "withdrawn"
    ):  # withdrawn == not searchable
        ia_item.modify_metadata(metadata)

    else:
        description = ia_item.metadata.get("description")
        if description:
            metadata[
                "description"
            ] = f"Note this registration has been withdrawn: \n{description}"
        else:
            metadata["description"] = "This registration has been withdrawn"

        del metadata["moderation_state"]
        ia_item.modify_metadata(metadata)
        ia_item.modify_metadata({"noindex": True})

    return ia_item, list(metadata.keys())


def create_subcollection(collection_id, metadata=None, parent_collection=None):
    """
    The expected sub-collection hierarchy is as follows top-level OSF collection -> provider
    collection -> collection for nodes with multiple children -> all only child nodes

    :param collection_id: the IA item name for the collections to be created
    :param metadata: dict should attributes for the provider's sub-collection is being created
    :param parent_collection: str the name of the  sub-collection's parent

    :return:
    """
    if metadata is None:
        metadata = {}

    session = internetarchive.get_session(
        config={
            "s3": {"access": settings.IA_ACCESS_KEY, "secret": settings.IA_SECRET_KEY},
        },
    )

    collection = internetarchive.Item(session, collection_id)
    collection.upload(
        files={"dummy.txt": BytesIO(b"dummy")},
        metadata={
            "mediatype": "collection",
            "collection": parent_collection,
            **metadata,
        },
    )


async def upload(item_name, data, metadata):
    ia_item = get_ia_item(item_name)
    ia_metadata = await get_metadata_for_ia_item(metadata)
    provider_id = metadata["data"]["embeds"]["provider"]["data"]["id"]

    ia_item.upload(
        data,
        metadata={
            "collection": PROVIDER_ID_TEMPLATE.format(guid=provider_id),
            **ia_metadata,
        },
        access_key=settings.IA_ACCESS_KEY,
        secret_key=settings.IA_SECRET_KEY,
    )
    return ia_item


async def get_registration_metadata(guid, temp_dir, filename):
    metadata = await get_paginated_data(
        f"{settings.OSF_API_URL}v2/registrations/{guid}/"
        f"?embed=parent"
        f"&embed=children"
        f"&embed=provider"
        f"&embed=identifiers"
        f"&embed=license"
        f"&embed=registration_schema"
        f"&related_counts=true"
        f"&version=2.20"
    )
    if metadata["data"]["attributes"]["withdrawn"]:
        raise PermissionError(f"Registration {guid} is withdrawn")

    with open(os.path.join(temp_dir, filename), "w") as fp:
        json.dump(metadata, fp)

    return metadata


async def get_raw_data(guid, temp_dir):
    try:
        get_and_write_file_data_to_temp(
            from_url=f"{settings.OSF_FILES_URL}v1/resources/{guid}/providers/osfstorage/?zip=",
            to_dir=temp_dir,
            name="archived_files.zip",
        )
    except requests.exceptions.ChunkedEncodingError:
        raise requests.exceptions.ChunkedEncodingError(
            f"OSF file system is sending incomplete streams for {guid}"
        )


async def archive(guid):
    with tempfile.TemporaryDirectory(
        prefix=REG_ID_TEMPLATE.format(guid=guid)
    ) as temp_dir:
        # await first to check if withdrawn
        metadata = await get_registration_metadata(guid, temp_dir, "registration.json")
        tasks = [
            write_datacite_metadata(guid, temp_dir, metadata),
            get_and_write_json_to_temp(
                from_url=f"{settings.OSF_API_URL}v2/registrations/{guid}/wikis/"
                f"?page[size]=100",
                to_dir=temp_dir,
                name="wikis.json",
            ),
            get_and_write_json_to_temp(
                from_url=f"{settings.OSF_API_URL}v2/registrations/{guid}/logs/"
                f"?page[size]=100",
                to_dir=temp_dir,
                name="logs.json",
            ),
            get_and_write_json_to_temp(
                from_url=f"{settings.OSF_API_URL}v2/registrations/{guid}/contributors/"
                f"?page[size]=100",
                to_dir=temp_dir,
                name="contributors.json",
                parse_json=get_contributors,
            ),
        ]
        # only download archived data if there are files
        file_count = metadata["data"]["relationships"]["files"]["links"]["related"][
            "meta"
        ]["count"]
        if file_count:
            tasks.append(get_raw_data(guid, temp_dir))

        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        bagit.make_bag(temp_dir)
        bag = bagit.Bag(temp_dir)
        assert bag.is_valid()

        zip_data = create_zip_data(temp_dir)
        ia_item = await upload(REG_ID_TEMPLATE.format(guid=guid), zip_data, metadata)

        return ia_item, guid


def run(coroutine):
    loop = events.new_event_loop()
    try:
        events.set_event_loop(loop)
        return loop.run_until_complete(coroutine)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            events.set_event_loop(None)
            loop.close()
