from .config import Config


def create_app():
    from .web import app as web_app

    app = web_app
    app.config.from_object(Config)
    return app
