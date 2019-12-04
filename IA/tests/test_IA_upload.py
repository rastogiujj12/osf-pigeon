import os
import mock
import asyncio
import unittest
import responses
from IA.tests.utils import MockCoroutine

from IA.IA_upload import upload, chunked_upload

HERE = os.path.dirname(os.path.abspath(__file__))


class TestIAUploader(unittest.TestCase):

    @responses.activate
    def test_IA_upload(self):
        responses.add(
            responses.Response(
                responses.PUT,
                'http://s3.us.archive.org/bucketname/file_name',
            ),
        )
        asyncio.run(upload('bucketname', 'file_name', b'content'))

    @responses.activate
    @mock.patch('IA.IA_upload.asyncio.gather', MockCoroutine())
    @mock.patch('IA.IA_upload.asyncio.coroutine')
    @mock.patch('IA.IA_upload.mp_from_ids')
    @mock.patch('IA.IA_upload.boto.connect_s3')
    def test_IA_chunked_upload(self, mock_upload, mock_mp_from_ids, mock_coroutine):
        mock_multipart = MockCoroutine()
        mock_coroutine.return_value = mock_multipart

        responses.add(
            responses.Response(
                responses.PUT,
                'http://s3.us.archive.org/bucketname/file_name',
            ),
        )
        mock_bucket = mock.Mock()
        mock_connection = mock.Mock()
        mock_connection.lookup.return_value = mock_bucket
        mock_upload.return_value = mock_connection

        asyncio.run(chunked_upload('bucketname', 'file_name', b'content'))
        connection_args = mock_upload.call_args_list[0][1]

        assert connection_args['host'] == 's3.us.archive.org'
        assert connection_args['is_secure'] is False

        mock_connection.lookup.assert_called_with('bucketname')
        mock_bucket.initiate_multipart_upload.assert_called_with('file_name')
        assert mock_mp_from_ids.call_args_list[0][0][1] == 'file_name'
        mock_coroutine.call_args_list[0][0][0]._mock_name == 'upload_part_from_file'

        bytes_to_upload = mock_multipart.call_args_list[0][0][0].read()
        assert bytes_to_upload == b'content'
