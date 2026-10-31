from flask import Flask
from .config import Config
from .clients.storage_client import StorageClient
# from .clients.ml_client import MLClient
from .extensions import create_minio_client
from minio.error import S3Error
from minio import Minio
from .logging import configure_logging


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["bucket_name"] = "ml-bucket"

    configure_logging(app, service_name="collector-service")
    client = create_minio_client(app)
    try:
        if not client.bucket_exists(app.config["bucket_name"]):
            client.make_bucket(app.config["bucket_name"])
    except S3Error as error:
        raise RuntimeError("Не удалось подготовить bucket в MiniO") from error

    app.extensions["minio_client"] = client

    app.extensions["storage_client"] = StorageClient(
        base_url=app.config["STORAGE_MODULE_URL"],
        service_name="collector-service",
        service_key=app.config["COLLECTOR_SERVICE_KEY"],
    )
    app.extensions["minio_public_client"] = Minio(
        endpoint=app.config["MINIO_PUBLIC_ENDPOINT"],
        access_key=app.config["MINIO_ACCESS_KEY"],
        secret_key=app.config["MINIO_SECRET_KEY"],
        secure=False,
        region=app.config["MINIO_REGION"],
    )
    # app.extensions["ml_client"] = MLClient(
    #     base_url=app.config["ML_MODULE_URL"],
    #     service_name="collector-service",
    #     service_key=app.config["WEB_SERVICE_KEY"],
    # )

    from .datasets.routes import bp as datasets_bp
    app.register_blueprint(datasets_bp)

    return app