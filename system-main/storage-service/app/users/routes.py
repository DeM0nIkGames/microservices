from flask import (
    Blueprint,
    request,
    current_app,
    jsonify,
    g,
)
from app.decorators import service_required, admin_required
from werkzeug.security import generate_password_hash, check_password_hash
from psycopg.errors import UniqueViolation
from app.logging import audit_event


bp = Blueprint("users", __name__)


def check_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict): return None
    else: return body


@bp.post("/auth/login")
@service_required("web-service")
def authenticate_user():
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть json-объектом"), 400

    login = body.get("login")
    password = body.get("password")
    if not login or not password: return jsonify(error="Поля не должны быть пустыми"), 400

    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            res = cur.execute(
                """
                SELECT id, password_hash, role
                FROM users
                WHERE login = %s
                """,
                (login, )
            ).fetchall()
            if not res: return jsonify(error="Неверный логин или пароль"), 401
            user_id, correct_hash, role = res[0]

    if check_password_hash(correct_hash, password):
        audit_event(
            "auth.login",
            entity_type="user",
            entity_id=user_id,
            details={
                "login": login,
                "role": role,
            },
        )
        return jsonify(id=user_id, login=login, role=role), 200
    else: 
        audit_event(
            "auth.login",
            entity_type="user",
            entity_id=user_id,
            outcome="failed",
            details={
                "login": login,
                "reason": "invalid_credentials",
            },
        )
        return jsonify(error="Неверный логин или пароль"), 401


@bp.get("/users/<int:user_id>")
@service_required("collector-service", "web-service", "ml-service")
def get_user_by_id(user_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            res = cur.execute(
                """
                SELECT login, role
                FROM users
                WHERE id = %s
                """,
                (user_id, )
            ).fetchall()
            if not res: return jsonify(error="Пользователь не найден"), 404
            login, role = res[0]
    return jsonify(id=user_id, login=login, role=role), 200


@bp.patch("/users/<int:user_id>/password")
@service_required("web-service")
def change_password(user_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть json-объектом"), 400

    password = body.get("current_password")
    new_password = body.get("new_password")
    if not new_password or not password: return jsonify(error="Поля не должны быть пустыми"), 400

    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            res = cur.execute(
                """
                SELECT password_hash
                FROM users
                WHERE id = %s
                """,
                (user_id, )
            ).fetchall()
            if not res: return jsonify(error="Пользователь не найден"), 404
            correct_hash = res[0][0]
        
    if check_password_hash(correct_hash, password):
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                    SET password_hash = %s
                    WHERE id = %s
                    """,
                        (generate_password_hash(new_password), user_id, )
                    )
        audit_event(
            "user.password_changed",
            entity_type="user",
            entity_id=user_id,
        )
        return "", 204
    else: return jsonify(error="Пароли не совпадают"), 403


@bp.get("/users")
@service_required("web-service")
@admin_required
def get_users():
    users = []
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            res = cur.execute(
                """
                SELECT id, login, role
                FROM users
                """,
            ).fetchall()
            for user in res:
                users.append({
                    "id": user[0],
                    "login": user[1],
                    "role": user[2],
                })
    return jsonify(users), 200


@bp.post("/users")
@service_required("web-service")
@admin_required
def add_user():
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть json-объектом"), 400

    login = body.get("login")
    password = body.get("password")
    role = body.get("role")

    if not login or not password or not role: 
        return jsonify(error="Поля не должны быть пустыми"), 400

    if role not in {"admin", "user"}: return jsonify(error="Допустимые роли: admin и user"), 400

    pool = current_app.extensions["db_pool"]
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                user_id = cur.execute(
                    """
                    INSERT 
                    INTO users
                    (login, password_hash, role)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (login, generate_password_hash(password), role)
                ).fetchone()[0]
    except UniqueViolation: return jsonify(error="Пользователь с таким логином уже существует"), 409
    audit_event(
        "user.created",
        entity_type="user",
        entity_id=user_id,
        details={
            "login": login,
            "role": role,
        },
    )
    return jsonify(id=user_id), 201


@bp.post("/users/<int:user_id>/edit")
@service_required("web-service")
@admin_required
def edit_user(user_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть json-объектом"), 400
    
    login = body.get("login")
    password = body.get("password")
    role = body.get("role")

    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            res = cur.execute(
                """
                SELECT login, password_hash, role
                FROM users
                WHERE id = %s
                """,
                (user_id, )
            ).fetchall()
            if not res: return jsonify("Пользователь не найден"), 404
            else: cur_login, cur_hash, cur_role = res[0]
    
            if not login: login = cur_login
            if not password: password_hash = cur_hash
            else: password_hash = generate_password_hash(password)
            if not role: role = cur_role
            if role not in {"admin", "user"}: return jsonify(error="Допустимые роли: admin и user"), 400
            cur.execute(
                """
                UPDATE users
                SET login = %s, password_hash = %s, role = %s
                WHERE id = %s
                """,
                (login, password_hash, role, user_id, )
            )
    audit_event(
        "user.updated",
        entity_type="user",
        entity_id=user_id,
        details={
            "login": login,
            "role": role,
            "password_changed": bool(password),
        },
    )
    return "", 204


@bp.post("/users/<int:user_id>/delete")
@service_required("web-service")
@admin_required
def delete_user(user_id):
    if g.caller_user == user_id: return jsonify(error="Запрещено удалять самого себя"), 400
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            res = cur.execute(
                """
                DELETE
                FROM users
                WHERE id = %s
                RETURNING id
                """, (user_id, )
            ).fetchone()
            if not res: return jsonify(error="Пользователь не найден"), 404
    audit_event(
        "user.deleted",
        entity_type="user",
        entity_id=user_id,
    )
    return "", 204