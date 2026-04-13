from logic import init_db
from split_app import create_app

app = create_app()

if __name__ == "__main__":
    init_db()
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
    )
