import os


class Config:
    SECRET_KEY = os.environ["FLASK_SECRET_KEY"]
    WEB_SERVICE_KEY = os.environ["WEB_SERVICE_KEY"]

    LOADER_MODULE_URL = os.environ.get("LOADER_MODULE_URL", "http://collector-service:8000")

    STORAGE_MODULE_URL = os.environ.get("STORAGE_MODULE_URL", "http://storage-service:8000")

    ML_MODULE_URL = os.environ.get("ML_MODULE_URL", "http://ml-service:8000")

    VIS_MODULE_URL = os.environ.get("VIS_MODULE_URL", "http://visualization-service:8000")

    HTTP_TIMEOUT_SECONDS = 10
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"