import secrets
from functools import wraps
from flask import abort, current_app, request, g


def service_required(*allowed_services):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            service_name = request.headers.get("X-Service-Name")
            provided_key = request.headers.get("X-Service-Key")

            if not service_name or not provided_key: abort(401, description="Не переданы данные сервисной аутентификации")
            service_keys = current_app.config["SERVICE_KEYS"]
            expected_key = service_keys.get(service_name)

            if (expected_key is None or not secrets.compare_digest(provided_key, expected_key)): abort(401, description="Недействительные данные сервисной аутентификации.")
            if allowed_services and service_name not in allowed_services: abort(403, description="У сервиса нет доступа к этому ресурсу.")
            g.caller_service = service_name
            return view(*args, **kwargs)
        return wrapped_view
    return decorator


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user_id = request.headers.get("X-Acting-User-Id", type=int)
        if user_id is None: abort(400, "Не передан корректный actor_id")

        pool = current_app.extensions["db_pool"]
        with pool.connection() as conn:
            with conn.cursor() as cur:
                res = cur.execute(
                    """
                    SELECT role
                    FROM users
                    WHERE id = %s
                    """, (user_id, )
                    ).fetchall()
                if not res: abort(400, "Не передан корректный actor_id")
                role = res[0][0]
        g.caller_user = user_id        
        if role != "admin": abort(403, description="Пользователь должен быть администратором")
        return view(*args, **kwargs)
    return wrapped_view