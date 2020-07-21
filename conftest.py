import pytest
import responses
from osf_pigeon import settings


@pytest.fixture
def mock_waterbutler(guid, zip_data):
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        rsps.add(
            responses.GET,
            f'{settings.OSF_FILES_URL}v1/resources/{guid}/providers/osfstorage/?zip=',
            status=200,
            body=zip_data
        )
        yield rsps


@pytest.fixture
def mock_osf_api(guid):
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        yield rsps


@pytest.fixture
def mock_datacite(guid):
    doi = settings.DOI_FORMAT.format(prefix=settings.DATACITE_PREFIX, guid=guid)
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        rsps.add(
            responses.GET,
            f'{settings.DATACITE_URL}metadata/{doi}', status=200)
        yield rsps
