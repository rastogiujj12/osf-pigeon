import os
import argparse
import json
import logging
import requests
import settings
from IA.utils import get_with_retry

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HERE = os.path.dirname(os.path.abspath(__file__))


def json_with_pagination(path, guid, page, url, token):
    # Get JSON of registration logs
    response = make_json_api_request(url, token)

    # Craft filename based on page number
    json_filename = guid + '-' + str(page) + '.json'
    file_location = os.path.join(path, json_filename)
    json_data = response['data']
    with open(file_location, 'w') as file:
        json.dump(json_data, file)
    return response


def make_json_api_request(url, token):
    auth_header = {'Authorization': f'Bearer {token}'}
    response = get_with_retry(url, retry_on=(429,), headers=auth_header)
    if response.status_code >= 400:
        status_code = response.status_code
        content = getattr(response, 'content', None)
        raise requests.exceptions.HTTPError('Status code {}. {}'.format(status_code, content))

    return response.json()


def create_logs(guid, directory, pagesize, bearer_token):
    # Creating directories
    path = os.path.join(HERE, directory, guid)
    if not os.path.exists(path):
        os.mkdir(path)

    path = os.path.join(path, 'logs')

    try:
        os.mkdir(path)
    except FileExistsError:
        pass

    # Retrieving page 1
    url = settings.OSF_API_URL + settings.OSF_LOGS_URL.format(guid, pagesize)
    response = json_with_pagination(path, guid, 1, url, bearer_token)
    page_num = 2

    # Retrieve the rest of the pages (if applicable)
    while response['links']['next']:
        next_link = response['links']['next']
        response = json_with_pagination(path, guid, page_num, next_link, bearer_token)
        page_num = page_num + 1

    print('Log data successfully transferred!')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-g',
        '--guid',
        help='This is the GUID of the target node on the OSF',
        required=True
    )
    parser.add_argument(
        '-t',
        '--token',
        help='Auth token for osf. This is required.',
        required=True
    )
    parser.add_argument(
        '-d',
        '--directory',
        help='This is the target Directory for the project and its files',
        default='.'
    )
    parser.add_argument(
        '-p',
        '--pagesize',
        help='How many logs should appear per file? Default is 100'
    )
    args = parser.parse_args()
    guid = args.guid
    directory = args.directory
    pagesize = args.pagesize
    bearer_token = args.token

    create_logs(guid, directory, pagesize, bearer_token)
