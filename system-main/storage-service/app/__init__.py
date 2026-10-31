from flask import Flask
from .config import Config
from .clients.collector_client import CollectorClient
from .extensions import create_db_pool
from .logging import configure_logging


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    configure_logging(app, service_name="storage-service")

    app.extensions["db_pool"] = create_db_pool(app)
    app.extensions["collector_client"] = CollectorClient(
        base_url=app.config["LOADER_MODULE_URL"],
        service_name="storage-service",
        service_key=app.config["STORAGE_SERVICE_KEY"],
    )

    from .users.routes import bp as users_bp
    from .datasets.routes import bp as datasets_bp
    from .models.routes import bp as models_bp
    from .models.routes import internal_bp as models_bp_internal
    from .results.routes import bp as runs_bp
    from .results.routes import internal_bp as runs_bp_internal
    from .results.routes import results_bp as runs_bp_results
    app.register_blueprint(users_bp)
    app.register_blueprint(datasets_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(models_bp_internal)
    app.register_blueprint(runs_bp)
    app.register_blueprint(runs_bp_internal)
    app.register_blueprint(runs_bp_results)

    return app