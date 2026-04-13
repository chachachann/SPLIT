from flask import redirect, render_template, request, session, url_for

from split_app.services.chat_auth import (
    create_remember_me_token,
    delete_remember_me_token,
    record_user_login,
    validate_user,
)
from split_app.support import get_remember_cookie_name, get_remember_me_days, start_user_session


def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember")

        user = validate_user(username, password)
        if user:
            start_user_session(user, persistent=bool(remember))
            record_user_login(user["username"])
            response = redirect(url_for("dashboard"))

            if remember:
                remember_token = create_remember_me_token(user["username"])
                response.set_cookie(
                    get_remember_cookie_name(),
                    remember_token,
                    max_age=get_remember_me_days() * 24 * 60 * 60,
                    httponly=True,
                    samesite="Lax",
                )
            else:
                existing_remember_cookie = request.cookies.get(get_remember_cookie_name())
                if existing_remember_cookie:
                    delete_remember_me_token(existing_remember_cookie)
                response.delete_cookie(get_remember_cookie_name())

            return response

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


def logout():
    remember_cookie = request.cookies.get(get_remember_cookie_name())
    if remember_cookie:
        delete_remember_me_token(remember_cookie)
    session.clear()
    response = redirect(url_for("login"))
    response.delete_cookie(get_remember_cookie_name())
    return response
