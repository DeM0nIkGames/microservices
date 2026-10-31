from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import login_user, UserMixin, login_required, current_user, logout_user
from dataclasses import dataclass
from app.extensions import login_manager
import httpx

bp = Blueprint("auth", __name__)


@dataclass
class User(UserMixin):
    id: int
    login: str
    role: str


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        storage = current_app.extensions["storage_client"]

        try:
            user_data = storage.authenticate(
                login=request.form["login"],
                password=request.form["password"],
            )
        except httpx.TimeoutException:
            flash("Сервис хранения временно не отвечает", "error")
            return render_template("login.html"), 503
        except httpx.RequestError:
            flash("Не удалось подключиться к сервису", "error")
            return render_template("login.html"), 502
        except httpx.HTTPStatusError:
            flash("Не удалось выполнить вход", "error")
            return render_template("login.html"), 502

        if user_data is None:
            flash("Неверный логин или пароль", "error")
            return render_template("login.html"), 401

        user = User(user_data["id"], user_data["login"], user_data["role"])

        login_user(user)

        next_url = request.args.get("next")
        return redirect(next_url or url_for("main.dashboard"))

    return render_template("login.html")


@login_manager.user_loader
def load_user(user_id):
    storage = current_app.extensions["storage_client"]

    try:
        user_data = storage.get_user_by_id(int(user_id))
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        current_app.logger.warning("Не удалось восстановить пользователя %s из Storage API", user_id)
        return None

    if user_data is None: return None

    return User(user_data["id"], user_data["login"], user_data["role"])


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли из системы", "success")
    return redirect(url_for("auth.login"))


@bp.post("/password/change")
@login_required
def change_password():
    current_password = request.form["current_password"]
    new_password = request.form["new_password"]
    new_password_repeat = request.form["new_password_repeat"]

    if new_password != new_password_repeat:
        flash("Новые пароли не совпадают", "error")
        return redirect(url_for("main.dashboard"))

    storage = current_app.extensions["storage_client"]

    try:
        storage.change_password(
            actor_id=current_user.id,
            user_id=current_user.id,
            current_password=current_password,
            new_password=new_password,
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 403:
            flash("Текущий пароль указан неверно", "error")
        else:
            flash("Не удалось изменить пароль", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.TimeoutException:
        flash("Сервис временно не отвечает", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.RequestError:
        flash("Не удалось подключиться к сервису", "error")
        return redirect(url_for("main.dashboard"))

    flash("Пароль успешно изменён", "success")
    return redirect(url_for("main.dashboard"))


@bp.get("/users")
@login_required
def users_index():
    users = []
    try:
        storage = current_app.extensions["storage_client"]
        users = storage.get_users(actor_id=current_user.id)
    except httpx.HTTPStatusError:
        flash("Возникла проблема с загрузкой пользователей", "error")
    except httpx.TimeoutException:
        flash("Сервис временно не отвечает", "error")
    except httpx.RequestError:
        flash("Не удалось подключиться к сервису", "error")

    return render_template("users.html", users=users)


@bp.post("/users")
@login_required
def create_user():
    if request.form["password"] != request.form["password_repeat"]:
        flash("Пароли не совпадают", "error")
        return redirect(url_for("auth.users_index"))
    
    try:
        storage = current_app.extensions["storage_client"]
        storage.add_user(
            actor_id=current_user.id,
            login=request.form["login"],
            password=request.form["password"],
            role=request.form["role"]
        )
    except httpx.HTTPStatusError:
        flash("Возникла проблема с созданием пользователя", "error")
        return redirect(url_for("auth.users_index"))
    except httpx.RequestError:
        flash("Не удалось подключиться к сервису", "error")
        return redirect(url_for("auth.users_index"))
    except httpx.TimeoutException:
        flash("Сервис временно не отвечает", "error")
        return redirect(url_for("auth.users_index"))

    
    flash("Пользователь успешно добавлен", "success")
    return redirect(url_for("auth.users_index"))


@bp.post("/users/<int:user_id>/edit")
@login_required
def update_user(user_id: int):
    if request.form["password"] and request.form["password"] != request.form["password_repeat"]:
        flash("Пароли не совпадают", "error")
        return redirect(url_for("auth.users_index"))
    
    try:
        storage = current_app.extensions["storage_client"]
        storage.update_user(
            actor_id=current_user.id,
            user_id=user_id,
            login=request.form["login"],
            password=request.form["password"] or None,
            role=request.form["role"]
        )
    except httpx.HTTPStatusError:
        flash("Возникла проблема с изменением пользователя", "error")
        return redirect(url_for("auth.users_index"))
    except httpx.TimeoutException:
        flash("Сервис временно не отвечает", "error")
        return redirect(url_for("auth.users_index"))
    except httpx.RequestError:
        flash("Не удалось подключиться к сервису", "error")
        return redirect(url_for("auth.users_index"))
    
    flash("Пользователь успешно изменен", "success")
    return redirect(url_for("auth.users_index"))


@bp.post("/<int:user_id>/delete")
@login_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash("Нельзя удалить самого себя", "error")
        return redirect(url_for("auth.users_index"))

    storage = current_app.extensions["storage_client"]

    try:
        storage.delete_user(actor_id=current_user.id,
                            user_id=user_id)
    except httpx.HTTPStatusError:
        flash("Не удалось удалить пользователя", "error")
    except httpx.TimeoutException:
        flash("Сервис временно не отвечает", "error")
    except httpx.RequestError:
        flash("Не удалось подключиться к сервису", "error")
    else:
        flash("Пользователь удалён", "success")

    return redirect(url_for("auth.users_index"))