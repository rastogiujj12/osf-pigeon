import os
import logging
import argparse
import requests
from sanic import Sanic
from sanic.response import json, file, text
from osf_pigeon import pigeon
from concurrent.futures import ThreadPoolExecutor
from sanic.log import logger
from osf_pigeon import settings
from raven import Client


app = Sanic("osf_pigeon")
logging.basicConfig(filename="pigeon.log", level=logging.DEBUG)
pigeon_jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pigeon_jobs")

if settings.SENTRY_DSN:
    sentry = Client(dsn=settings.SENTRY_DSN)


@app.route("/logs")
async def logs(request):
    try:
        return await file("pigeon.log")
    except FileNotFoundError:
        return text("pigeon.log not found")


def handle_exception(future):
    exception = future.exception()
    if exception:
        if settings.SENTRY_DSN:
            sentry = Client(dsn=settings.SENTRY_DSN)
            sentry.captureMessage(str(exception))
        logger.debug(exception)


def archive_task_done(future):
    if future._result and not future._exception:
        ia_item, guid = future.result()
        resp = requests.post(
            f"{settings.OSF_API_URL}_/ia/{guid}/done/",
            json={"ia_url": ia_item.urls.details},
        )
        logger.debug(f"{ia_item.urls.details} Callback status:{resp}")


def metadata_task_done(future):
    if future._result and not future._exception:
        ia_item, updated_metadata = future.result()
        logger.debug(f"{ia_item.urls.details} Updated:{updated_metadata}")


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


@app.route("/")
async def index(request):
    return json({"🐦": "👍"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Set the environment to run OSF pigeon in."
    )
    parser.add_argument(
        "--env", dest="env", help="what environment are you running this for"
    )
    args = parser.parse_args()
    if args.env:
        os.environ["ENV"] = args.env

    if args.env == "production":
        app.run(host=settings.HOST, port=settings.PORT, access_log=False)
    else:
        app.run(
            host=settings.HOST,
            port=settings.PORT,
            auto_reload=True,
            debug=True,
            access_log=False,
        )
