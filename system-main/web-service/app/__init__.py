from flask import Flask
from .config import Config
from .extensions import csrf, login_manager
from .clients.loader_client import CollectorClient
from .clients.storage_client import StorageClient
from .clients.ml_client import MLClient
from .clients.vis_client import VisClient


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Необходимо войти в систему"
    login_manager.login_message_category = "error"

    app.extensions["collector_client"] = CollectorClient(
        base_url=app.config["LOADER_MODULE_URL"],
        service_name="web-service",
        service_key=app.config["WEB_SERVICE_KEY"],
    )
    app.extensions["storage_client"] = StorageClient(
        base_url=app.config["STORAGE_MODULE_URL"],
        service_name="web-service",
        service_key=app.config["WEB_SERVICE_KEY"],
    )
    app.extensions["ml_client"] = MLClient(
        base_url=app.config["ML_MODULE_URL"],
        service_name="web-service",
        service_key=app.config["WEB_SERVICE_KEY"],
    )
    app.extensions["vis_client"] = VisClient(
        base_url=app.config["VIS_MODULE_URL"],
        service_name="web-service",
        service_key=app.config["WEB_SERVICE_KEY"],
    )
    
    
    from .auth.routes import bp as auth_bp
    from .main.routes import bp as main_bp
    from .models.routes import bp as models_bp
    from .datasets.routes import bp as datasets_bp
    from .results.routes import bp as res_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(datasets_bp)
    app.register_blueprint(res_bp)

    return app