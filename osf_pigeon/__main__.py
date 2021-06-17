from osf_pigeon import settings
from osf_pigeon.app import app, routes
from aiohttp import web


if __name__ == "__main__":
    app.add_routes(routes)
    web.run_app(app, host=settings.HOST, port=settings.PORT)
