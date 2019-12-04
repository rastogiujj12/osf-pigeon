import math
import asyncio
import requests
from typing import Tuple, Dict
from ratelimit import sleep_and_retry
from ratelimit.exception import RateLimitException


@sleep_and_retry
def get_with_retry(
        url,
        retry_on: Tuple[int] = (),
        sleep_period: int = None,
        headers: Dict = None) -> requests.Response:

    if not headers:
        headers = {}

    resp = requests.get(url, headers=headers)
    if resp.status_code in retry_on:
        raise RateLimitException(
            message='Too many requests, sleeping.',
            period_remaining=sleep_period or int(resp.headers.get('Retry-After') or 0)
        )  # This will be caught by @sleep_and_retry and retried

    return resp


@sleep_and_retry
def put_with_retry(
        url: str,
        data: bytes,
        headers: dict = None,
        retry_on: Tuple[int] = (),
        sleep_period: int = None) -> requests.Response:

    if headers is None:
        headers = {}

    resp = requests.put(url, headers=headers, data=data)
    if resp.status_code in retry_on:
        raise RateLimitException(
            message='Too many requests, sleeping.',
            period_remaining=sleep_period or int(resp.headers.get('Retry-After') or 0)
        )  # This will be caught by @sleep_and_retry and retried

    return resp


async def get_pages(url, page, result={}):
    url = f'{url}?page={page}'
    resp = get_with_retry(url, retry_on=(429,))
    result[page] = resp.json()['data']
    return result


async def get_paginated_data(url):

    data = get_with_retry(url, retry_on=(429,)).json()
    result = {1: data['data']}

    tasks = []
    if data['links']['next'] is not None:
        pages = math.ceil(int(data['meta']['total']) / int(data['meta']['per_page']))
        for i in range(1, pages):
            task = get_pages(url, i + 1, result)
            tasks.append(task)

    await asyncio.gather(*tasks)

    pages_as_list = []
    # through the magic of async all our pages have loaded.
    for page in list(result.values()):
        pages_as_list += page

    return pages_as_list
