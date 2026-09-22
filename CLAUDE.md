# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

This is a Django project. The project uses a virtual environment located at `.venv`.
To activate the virtual environment, run:
```bash
source .venv/bin/activate
```

Environment variables are stored in `.env` (see `.env.example` for required variables).

## Common Commands

### Running the Development Server
```bash
python manage.py runserver
```

### Running Tests
To run all tests:
```bash
python manage.py test
```

To run tests for a specific app (e.g., the risk app):
```bash
python manage.py test risk
```

To run a specific test case:
```bash
python manage.py risk.tests.TestClass.test_method
```

### Linting
There is no linting configuration found in the repository. However, you can use flake8 or pylint if installed.

### Database Migrations
To create migrations after model changes:
```bash
python manage.py makemigrations
```

To apply migrations:
```bash
python manage.py migrate
```

### Shell
To open a Django shell:
```bash
python manage.py shell
```

## Project Structure

The project follows a typical Django structure:

- `riskproject/`: The inner project directory containing settings and URLs.
  - `settings/`: Contains different settings for development, production, and testing.
  - `urls.py`: The root URL configuration.
- `risk/`: Main app for risk management (likely contains models, views, templates for risk-related functionality).
- `corporate_risk/`: App for corporate risk specifics.
- `awareness/`: App for risk awareness.
- `imports/`, `km/`, `kpmr/`, `masterdata/`, `reassessment/`: Other apps in the project.
- `templates/`: Contains HTML templates for the project.
- `static/`: Static files (CSS, JavaScript, images).
- `media/`: User-uploaded media files.

## Key Files

- `manage.py`: Django's command-line utility.
- `requirements.txt`: Python dependencies.
- `README_DEPLOY.md`: Instructions for deploying the executive risk dashboard patch.
- `.env.example`: Example environment variables.

## Notes

- The project uses Django 6.0.3.
- The database is SQLite by default (db.sqlite3).
- There are many patch files in the root directory (e.g., `*_local.patch`, `apply_*.py`) that are used to apply specific features or fixes.
- When working on new features, consider the existing apps and their responsibilities. Always run tests after making changes.