from flask import Flask, render_template, request, redirect, session
from datetime import timedelta, datetime
from logic import init_db, validate_user

app = Flask(__name__)
app.secret_key = "supersecretkey"

# 7 days session lifetime
app.permanent_session_lifetime = timedelta(days=7)


# 🔴 REMOVED before_first_request (Flask 3.x incompatible)


@app.route("/", methods=["GET", "POST"])
def login():
    # If already logged in → go dashboard
    if "user" in session:
        return redirect("/dashboard")

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember")

        user = validate_user(username, password)

        if user:
            session["user"] = user[0]
            session["userlevel"] = user[1]
            session["fullname"] = user[2]
            session["login_time"] = datetime.now().isoformat()

            # 7-day session if remember checked
            session.permanent = bool(remember)

            return redirect("/dashboard")

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    return render_template(
        "dashboard.html",
        username=session.get("user"),
        userlevel=session.get("userlevel"),
        fullname=session.get("fullname")
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ✅ INIT DB SAFELY (Flask 3.x compatible)
if __name__ == "__main__":
    init_db()  # ← runs once on startup
    app.run(host="0.0.0.0", port=200, debug=True)