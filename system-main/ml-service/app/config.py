import os


class Config:
    SERVICE_KEYS = {
        "web-service": os.environ["WEB_SERVICE_KEY"],
        "collector-service": os.environ["COLLECTOR_SERVICE_KEY"],
        "ml-service": os.environ["ML_SERVICE_KEY"],
        "visualization-service": os.environ["VIS_SERVICE_KEY"],
        "storage-service": os.environ["STORAGE_SERVICE_KEY"],
    }
    STORAGE_MODULE_URL = os.environ.get("STORAGE_MODULE_URL", "http://storage-service:8000")
    ML_SERVICE_KEY = os.environ.get("ML_SERVICE_KEY", None)
    LOADER_MODULE_URL = os.environ.get("LOADER_MODULE_URL", "http://loader-service:8000")

    MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    MINIO_ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
    MINIO_SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
    MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "ml-platform")
    MINIO_SECURE = False