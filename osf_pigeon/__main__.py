import logging
import requests
from osf_pigeon import pigeon
from concurrent.futures import ThreadPoolExecutor
from osf_pigeon import settings
from aiohttp import web

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

sentry_sdk.init(
      dsn=settings.SENTRY_DSN,
      integrations=[AioHttpIntegration()]
)

pigeon_jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pigeon_jobs")
app = web.Application()
routes = web.RouteTableDef()
logging.basicConfig(filename="pigeon.log", level=logging.DEBUG)


def handle_exception(future):
    exception = future.exception()
    if exception:
        app.logger.exception(exception)


def archive_task_done(future):
    if future._result and not future._exception:
        ia_item, guid = future.result()
        resp = requests.post(
            f"{settings.OSF_API_URL}_/ia/{guid}/done/",
            json={"ia_url": ia_item.urls.details},
        )
        app.logger.info(f"{ia_item} called back with {resp}")


def metadata_task_done(future):
    if future._result and not future._exception:
        ia_item, updated_metadata = future.result()
        app.logger.info(f"{ia_item} updated metadata {updated_metadata}")


@routes.get("/")
async def index(request):
    return web.json_response({"🐦": "👍"})


@routes.get("/logs")
async def logs(request):
    return web.FileResponse("pigeon.log")


@routes.get("/archive/{guid}")
@routes.post("/archive/{guid}")
async def archive(request):
    guid = request.match_info["guid"]
    future = pigeon_jobs.submit(pigeon.run, pigeon.archive(guid))
    future.add_done_callback(handle_exception)
    future.add_done_callback(archive_task_done)
    return web.json_response({guid: future._state})


@routes.post("/metadata/{guid}")
async def set_metadata(request):
    guid = request.match_info["guid"]
    metadata = await request.json()
    future = pigeon_jobs.submit(pigeon.sync_metadata, guid, metadata)
    future.add_done_callback(handle_exception)
    future.add_done_callback(metadata_task_done)
    return web.json_response({guid: future._state})


if __name__ == "__main__":
    app.add_routes(routes)
    web.run_app(app, host=settings.HOST, port=settings.PORT)
