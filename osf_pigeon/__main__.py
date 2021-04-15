import os
import argparse
import requests
from sanic import Sanic
from sanic.response import json
from osf_pigeon import pigeon
from concurrent.futures import ThreadPoolExecutor
from sanic.log import logger
from osf_pigeon import settings
from raven.contrib.sanic import Sentry


app = Sanic("osf_pigeon")
pigeon_jobs = ThreadPoolExecutor(max_workers=10, thread_name_prefix="pigeon_jobs")

if settings.SENTRY_DSN:
    sentry = Sentry(app, dsn=settings.SENTRY_DSN)


def handle_exception(future):
    exception = future.exception()
    if exception:
        if settings.SENTRY_DSN:
            sentry.captureMessage(exception)
        logger.error(exception)


def archive_task_done(future):
    if future.result():
        ia_item, guid = future.result()
        resp = requests.post(
            f"{settings.OSF_API_URL}_/ia/{guid}/done/",
            json={"ia_url": ia_item.urls.details},
        )
        logger.debug(f"{ia_item.urls.details} Callback status:{resp}")


def metadata_task_done(future):
    if future.result():
        ia_item, updated_metadata = future.result()
        logger.debug(f"{ia_item.urls.details} Updated:{updated_metadata}")


@app.route("/")
async def index(request):
    return json({"🐦": "👍"})


@app.route("/archive/<guid>", methods=["GET", "POST"])
async def archive(request, guid):
    future = pigeon_jobs.submit(pigeon.run, pigeon.archive(guid))
    future.add_done_callback(handle_exception)
    future.add_done_callback(archive_task_done)
    return json({guid: future._state})


@app.route("/metadata/<guid>", methods=["POST"])
async def set_metadata(request, guid):
    future = pigeon_jobs.submit(pigeon.sync_metadata, guid, request.json)
    future.add_done_callback(handle_exception)
    future.add_done_callback(metadata_task_done)
    return json({guid: future._state})


parser = argparse.ArgumentParser(
    description="Set the environment to run OSF pigeon in."
)
parser.add_argument(
    "--env", dest="env", help="what environment are you running this for"
)


if __name__ == "__main__":
    args = parser.parse_args()
    if args.env:
        os.environ["ENV"] = args.env

    if args.env == "production":
        app.run(host=settings.HOST, port=settings.PORT)
    else:
        app.run(host=settings.HOST, port=settings.PORT, auto_reload=True, debug=True)
