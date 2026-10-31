from flask import Flask
from .config import Config
from .clients.storage_client import StorageClient
from .clients.loader_client import CollectorClient
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
        service_name="ml-service",
        service_key=app.config["ML_SERVICE_KEY"],
    )
    app.extensions["collector_client"] = CollectorClient(
        base_url=app.config["LOADER_MODULE_URL"],
        service_name="ml-service",
        service_key=app.config["ML_SERVICE_KEY"],
    )
    
    from .models.routes import bp as models_bp
    app.register_blueprint(models_bp)
    

    return app