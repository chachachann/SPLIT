# SPLIT

SPLIT is a Flask-based internal operations platform that combines account management, internal communication, content publishing, profile management, and a dynamic forms workflow engine in a single application.

Current release: `v0.06.0a`

The project is structured as a server-rendered monolith using Jinja templates, browser-side JavaScript, SQLite for persistence, and filesystem-backed uploads for user-generated files.

## Features

- Role-based authentication with session and remember-me support
- Dashboard with quick actions, announcements, notifications, and workflow entry points
- Account and role administration
- Internal chat with channels, role rooms, direct messages, and favorites
- News posts, marquee items, and platform notifications
- User profile management, privacy controls, and password change review
- Dynamic form templates with drafts, autosave, approvals, comments, and tracking numbers
- Case-based workflow library with tabbed filed forms, pooled work claiming, assignment review, and multi-target promotions
- Separate template submit access and library visibility controls
- Field-level privacy for read-only library and case views
- SMTP settings storage for future outbound email support

## Tech Stack

- Python 3.10+
- Flask
- Werkzeug
- SQLite
- Jinja2 templates
- Vanilla JavaScript and CSS

## Project Structure

```text
SPLIT/
|- main.py                  # local development entrypoint
|- wsgi.py                  # WSGI entrypoint
|- logic.py                 # schema/bootstrap plus compatibility exports
|- forms_workflow.py        # workflow compatibility exports
|- split_app/
|  |- __init__.py           # app factory
|  |- config.py             # runtime configuration
|  |- web.py                # Flask app composition and route registration
|  |- support.py            # shared web-layer helpers and decorators
|  |- routes/               # route modules by feature area
|  |- services/             # extracted domain/service modules
|  |- workflow/             # workflow engine modules
|- templates/               # Jinja templates
|- static/                  # CSS, JS, images, uploads
|- tests/                   # smoke/regression tests
|- documentation.md         # generated architecture and schema documentation
|- FORM_WORKFLOW_SPEC.md    # workflow product specification
```

## Requirements

- Python 3.10 or newer
- `pip`

## Installation

1. Create and activate a virtual environment.
2. Install dependencies.
3. Copy `.env.example` to `.env` and adjust values as needed.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Configuration

The application reads configuration from environment variables.

Common settings:

- `SPLIT_SECRET_KEY`: Flask secret key
- `SPLIT_DEBUG`: enable debug mode
- `SPLIT_HOST`: bind host, default `0.0.0.0`
- `SPLIT_PORT`: bind port, default `777`
- `SPLIT_DB_PATH`: SQLite database path
- `SPLIT_REMEMBER_DAYS`: remember-me duration
- `SPLIT_SESSION_COOKIE_SECURE`: secure cookie toggle
- `SPLIT_PUBLIC_BASE_URL`: public base URL
- `SPLIT_SMTP_PASSWORD`: SMTP password

Example values are provided in [.env.example](/C:/Users/user/Desktop/Temp-Chan/SPLIT/.env.example:1).

## Running Locally

Start the application with:

```powershell
python main.py
```

This will initialize the database if needed and start the Flask development server using the configured host and port.

By default, the app runs on `http://localhost:777`.

## WSGI Entry Point

For WSGI deployments, use:

```python
from wsgi import app
```

`wsgi.py` also initializes the database on import.

## Database and Uploads

- The default SQLite path in `.env.example` is `C:\SPLIT\db\database.db`
- Schema creation and migration are handled by `logic.init_db()`
- Uploaded files are stored under `static/uploads/`

## Testing

The repository includes smoke tests under `tests/test_smoke.py`.

Run them with explicit discovery:

```powershell
python -m unittest discover -s tests -q
```

Note: plain `python -m unittest -q` does not currently discover the suite from the repo root.

## Main Modules

- [main.py](/C:/Users/user/Desktop/Temp-Chan/SPLIT/main.py:1): local launcher
- [wsgi.py](/C:/Users/user/Desktop/Temp-Chan/SPLIT/wsgi.py:1): WSGI entrypoint
- [split_app/web.py](/C:/Users/user/Desktop/Temp-Chan/SPLIT/split_app/web.py:1): route registration and Flask app composition
- [split_app/config.py](/C:/Users/user/Desktop/Temp-Chan/SPLIT/split_app/config.py:1): environment-backed config
- [logic.py](/C:/Users/user/Desktop/Temp-Chan/SPLIT/logic.py:1): database bootstrap and compatibility layer
- [documentation.md](/C:/Users/user/Desktop/Temp-Chan/SPLIT/documentation.md:1): detailed architecture and schema documentation
- [FORM_WORKFLOW_SPEC.md](/C:/Users/user/Desktop/Temp-Chan/SPLIT/FORM_WORKFLOW_SPEC.md:1): workflow system specification

## Current Status

The application code imports successfully, and the current smoke suite passes with:

```powershell
python -m unittest discover -s tests -q
```

## Release Notes

### v0.06.0a

- rebuilt the workflow library around case tracking and filed-form tabs
- added pooled promoted work with `Open`, `Pending Assignment`, and `Assigned` states
- added multi-target promotions under one case tracking number
- added builder support for submit access, library visibility, and private fields
- added force delete controls for templates in manager and builder screens
- removed obvious fake/test accounts from the live database

## Notes

- `requirements.txt` currently contains runtime dependencies only.
- The repository does not yet include formal packaging, CI, or containerization configuration.
