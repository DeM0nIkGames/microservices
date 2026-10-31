import os


class Config:
    SERVICE_KEYS = {
        "web-service": os.environ["WEB_SERVICE_KEY"],
        "collector-service": os.environ["COLLECTOR_SERVICE_KEY"],
        "ml-service": os.environ["ML_SERVICE_KEY"],
        "visualization-service": os.environ["VIS_SERVICE_KEY"],
        "storage-service": os.environ["STORAGE_SERVICE_KEY"],
    }
    LOADER_MODULE_URL = os.environ.get("LOADER_MODULE_URL", "http://loader-service:8000")

    STORAGE_SERVICE_KEY = os.environ["STORAGE_SERVICE_KEY"]

    DATABASE_URL = os.environ.get("DATABASE_URL")
    if DATABASE_URL is None:
        DATABASE_URL = os.environ.get("DATABASE_URL", (f"postgresql://ml_platform:{os.environ['POSTGRES_PASSWORD']}@postgres:5432/ml_platform"))

    DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "1"))

    DB_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "10"))