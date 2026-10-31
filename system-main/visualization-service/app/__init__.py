from flask import Flask
from .config import Config
from .clients.storage_client import StorageClient
# from .clients.ml_client import MLClient
from .extensions import create_minio_client
from minio.error import S3Error


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["bucket_name"] = "ml-bucket"

    client = create_minio_client(app)
    try:
        if not client.bucket_exists(app.config["bucket_name"]):
            client.make_bucket(app.config["bucket_name"])
    except S3Error as error:
        raise RuntimeError("Не удалось подготовить bucket в MiniO") from error

    app.extensions["minio_client"] = client

    app.extensions["storage_client"] = StorageClient(
        base_url=app.config["STORAGE_MODULE_URL"],
        service_name="visualization-service",
        service_key=app.config["VIS_SERVICE_KEY"],
    )
    # app.extensions["ml_client"] = MLClient(
    #     base_url=app.config["ML_MODULE_URL"],
    #     service_name="collector-service",
    #     service_key=app.config["WEB_SERVICE_KEY"],
    # )
    from .charts.routes import bp as charts_bp
    app.register_blueprint(charts_bp)

    return app