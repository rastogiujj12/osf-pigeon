from mock import MagicMock


class MockCoroutine(MagicMock):

    async def __call__(self, *args, **kwargs):
        return super(MockCoroutine, self).__call__(*args, **kwargs)

    async def __await__(self):
        pass
