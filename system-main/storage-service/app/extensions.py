from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def create_db_pool(app):
    pool = ConnectionPool(
        conninfo=app.config["DATABASE_URL"],
        min_size=app.config.get("DB_POOL_MIN_SIZE", 1),
        max_size=app.config.get("DB_POOL_MAX_SIZE", 10),
        # kwargs={
            # "row_factory": dict_row,
        # }, 
        open=False)
    
    pool.open()
    pool.wait(timeout=10)
    return pool