import secrets
from functools import wraps
from flask import abort, current_app, g, request
import httpx


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
        storage = current_app.extensions["storage_client"]
        user_id = request.headers.get("X-Acting-User-Id", type=int)
        
        if user_id is None: abort(400, "Не передан корректный actor_id")

        try:
            is_admin = storage.check_admin(user_id)
        except httpx.TimeoutException:
            abort(503, description="Сервис хранилища временно недоступен")
        except httpx.RequestError:
            abort(503, description="Не удалось подключиться к сервису хранилища")
        except httpx.HTTPStatusError:
            abort(403, description="Не удалось подтвердить права пользователя")
        
        if not is_admin: abort(403, description="Пользователь должен быть администратором")
        g.caller_user = user_id
        return view(*args, **kwargs)
    return wrapped_view


def actor_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user_id = request.headers.get("X-Acting-User-Id", type=int)

        if user_id is None:
            abort(400, description="Не передан корректный actor_id")

        g.caller_user = user_id
        return view(*args, **kwargs)

    return wrapped_view