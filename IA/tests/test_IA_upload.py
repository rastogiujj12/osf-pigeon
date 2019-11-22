import os
import asyncio
import unittest
import responses
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
    async def test_IA_chunked_upload(self):
        responses.add(
            responses.Response(
                responses.PUT,
                'http://s3.us.archive.org/bucketname/file_name',
            ),
        )
        asyncio.run(chunked_upload('bucketname', 'file_name', b'content'))
