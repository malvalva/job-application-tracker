"""Job Application Tracker: Flask routes, table definitions, validation and job matching."""
import hmac
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from math import ceil
from urllib.parse import urlsplit

from flask import (
    Flask, abort, flash, redirect, render_template, render_template_string,
    request, session, url_for,
)
from mysql.connector import Error
from mysql.connector import errorcode as ec
from werkzeug.exceptions import HTTPException
from werkzeug.routing import BaseConverter

import database as db

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Table and form definitions. SQL identifiers come from this section only.
# ---------------------------------------------------------------------------


class FieldError(ValueError):
    """A validation problem whose message is shown to the user."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"
    limit: int = 0
    required: bool = False
    choices: tuple = ()
    hint: str = ""
    check: object = None  # optional extra check for parsed JSON values


@dataclass(frozen=True)
class Entity:
    title: str
    singular: str
    pk: str
    fields: tuple
    columns: tuple   # (key, heading) pairs shown on the list page
    select: str      # SELECT list; the main table is always aliased "t"
    source: str      # FROM ... JOINs
    order: str
    search: tuple    # columns searched by the list page's search box
    label: object    # row -> short name, used on the delete confirmation


def check_requirements(parsed):
    skills = parsed if isinstance(parsed, list) else (
        parsed.get("skills", []) if isinstance(parsed, dict) else None
    )
    if not isinstance(skills, list) or any(
        not isinstance(skill, str) or not skill.strip() for skill in skills
    ):
        raise FieldError('Use a JSON object with a skills list, such as {"skills":["SQL"]}.')


COMPANY = Field("company_id", "Company", "company", required=True)
JOB_TYPES = ("Full-time", "Part-time", "Contract", "Internship")
STATUSES = ("Applied", "Screening", "Interview", "Offer", "Rejected", "Withdrawn")

# Limits are at or below the VARCHAR sizes in schema.sql.
ENTITIES = {
    "companies": Entity(
        "Companies", "Company", "company_id",
        (Field("company_name", "Company name", limit=100, required=True),
         Field("industry", "Industry", limit=50),
         Field("website", "Website", "url", 200),
         Field("city", "City", limit=50),
         Field("state", "State", limit=50),
         Field("notes", "Notes", "textarea")),
        (("company_name", "Company"), ("industry", "Industry"), ("city", "City"),
         ("state", "State")),
        "t.*",
        "FROM companies t",
        "ORDER BY t.company_name, t.company_id",
        ("t.company_name", "t.industry", "t.city", "t.state"),
        lambda row: row["company_name"],
    ),
    "jobs": Entity(
        "Jobs", "Job", "job_id",
        (COMPANY, Field("job_title", "Job title", limit=100, required=True),
         Field("job_type", "Job type", "select", choices=JOB_TYPES),
         Field("salary_min", "Minimum salary", "money"),
         Field("salary_max", "Maximum salary", "money"),
         Field("posting_url", "Posting URL", "url", 300),
         Field("date_posted", "Date posted", "date"),
         Field("requirements", "Requirements (JSON)", "json",
               hint='For Job Match, use {"skills": ["Python", "SQL"]}.',
               check=check_requirements)),
        (("job_title", "Job title"), ("company_name", "Company"),
         ("job_type", "Type"), ("date_posted", "Date posted")),
        "t.*, c.company_name",
        "FROM jobs t LEFT JOIN companies c ON t.company_id = c.company_id",
        "ORDER BY t.job_title, t.job_id",
        ("t.job_title", "c.company_name", "t.job_type"),
        lambda row: row["job_title"],
    ),
    "applications": Entity(
        "Applications", "Application", "application_id",
        (Field("job_id", "Job", "job", required=True),
         Field("application_date", "Application date", "date", required=True),
         Field("status", "Status", "select", choices=STATUSES),
         Field("resume_version", "Resume version", limit=50),
         Field("cover_letter_sent", "Cover letter sent", "boolean"),
         Field("interview_data", "Interview data (JSON)", "json",
               hint='Example {"round": 1, "notes": "Phone interview"}')),
        (("job_title", "Job"), ("company_name", "Company"),
         ("application_date", "Date applied"), ("status", "Status")),
        "t.*, j.job_title, c.company_name",
        "FROM applications t LEFT JOIN jobs j ON t.job_id = j.job_id "
        "LEFT JOIN companies c ON j.company_id = c.company_id",
        "ORDER BY t.application_date DESC, t.application_id DESC",
        ("j.job_title", "c.company_name", "t.status", "t.resume_version"),
        lambda row: f"{row.get('job_title') or 'Unknown job'}, applied {row['application_date']}",
    ),
    "contacts": Entity(
        "Contacts", "Contact", "contact_id",
        (COMPANY, Field("first_name", "First name", limit=50, required=True),
         Field("last_name", "Last name", limit=50, required=True),
         Field("job_title", "Job title", limit=100),
         Field("email", "Email", "email", 100),
         Field("phone", "Phone", "tel", 20),
         Field("linkedin_url", "LinkedIn URL", "url", 200),
         Field("notes", "Notes", "textarea")),
        (("first_name", "First name"), ("last_name", "Last name"),
         ("company_name", "Company"), ("job_title", "Job title"), ("email", "Email")),
        "t.*, c.company_name",
        "FROM contacts t LEFT JOIN companies c ON t.company_id = c.company_id",
        "ORDER BY t.last_name, t.first_name, t.contact_id",
        ("t.first_name", "t.last_name", "c.company_name", "t.email"),
        lambda row: f"{row['first_name']} {row['last_name']}",
    ),
}

# One query for all four dashboard counts. Table names come from ENTITIES only.
COUNT_SQL = " UNION ALL ".join(
    f"SELECT '{table}' AS name, COUNT(*) AS total FROM {table}" for table in ENTITIES
)
PER_PAGE = 25

# MySQL error numbers used below (see the MySQL error reference).
ER_BAD_NULL_ERROR = 1048
ER_DATA_TOO_LONG = 1406
ER_WARN_DATA_OUT_OF_RANGE = 1264
ER_CHECK_CONSTRAINT_VIOLATED = 3819

# Friendly messages for database errors a user can fix (shown instead of "MySQL is down").
DB_USER_ERRORS = {
    ec.ER_NO_REFERENCED_ROW_2: "A selected company or job no longer exists. Choose another.",
    ER_BAD_NULL_ERROR: "A required value was missing.",
    ER_DATA_TOO_LONG: "A value is too long for its column.",
    ER_WARN_DATA_OUT_OF_RANGE: "A number is outside the allowed range.",
    ER_CHECK_CONSTRAINT_VIOLATED: "A value breaks a rule set by the database "
                                  "(for example a salary range or a status).",
}

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------


class TableConverter(BaseConverter):
    """Only accepts the four known table names, so other paths simply 404."""
    regex = "|".join(ENTITIES)


app = Flask(__name__)
app.url_map.converters["table"] = TableConverter

# A new random key each start is fine for local use (a form left open across a
# restart just needs reloading). Set FLASK_SECRET_KEY to keep one fixed key.
secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SECRET_KEY=secret_key,
    MAX_CONTENT_LENGTH=1024 * 1024,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
)


@app.before_request
def check_form_token():
    if request.method == "POST":
        expected = session.get("form_token")
        supplied = request.form.get("form_token", "")
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            abort(400, "This form expired. Reload the page and try again.")


@app.context_processor
def form_context():
    if "form_token" not in session:
        session["form_token"] = secrets.token_hex(24)
    return {"form_token": session["form_token"]}


# ---------------------------------------------------------------------------
# Validation: one small function per field kind
# ---------------------------------------------------------------------------


def check_company(raw, field):
    if not re.fullmatch(r"[0-9]{1,10}", raw) or not db.fetch_one(
        "SELECT 1 AS found FROM companies WHERE company_id = %s", (int(raw),)
    ):
        raise FieldError("Choose a record from the list.")
    return int(raw)


def check_job(raw, field):
    if not re.fullmatch(r"[0-9]{1,10}", raw) or not db.fetch_one(
        "SELECT 1 AS found FROM jobs WHERE job_id = %s", (int(raw),)
    ):
        raise FieldError("Choose a record from the list.")
    return int(raw)


def check_money(raw, field):
    if not re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,2})?", raw):
        raise FieldError("Enter an amount from 0 to 99,999,999.99 with at most two decimals.")
    return Decimal(raw)


def check_date(raw, field):
    message = "Enter a valid date in YYYY-MM-DD format."
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        raise FieldError(message) from None
    if value.isoformat() != raw or value.year < 1000:
        raise FieldError(message)
    return value


def check_select(raw, field):
    if raw not in field.choices:
        raise FieldError("Choose a value from the list.")
    return raw


def check_boolean(raw, field):
    if raw not in ("0", "1"):
        raise FieldError("Choose Yes, No, or Not recorded.")
    return int(raw)


def check_json(raw, field):
    try:
        parsed = json.loads(raw)
        text = json.dumps(parsed, allow_nan=False)
    except (ValueError, RecursionError):
        raise FieldError("Enter valid JSON.") from None
    if field.check:
        field.check(parsed)
    return text


def check_url(raw, field):
    url = urlsplit(raw)
    if url.scheme not in ("http", "https") or not url.hostname or re.search(r"\s", raw):
        raise FieldError("Enter a full URL beginning with https:// or http://.")
    return raw


def check_email(raw, field):
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", raw):
        raise FieldError("Enter a valid email address.")
    return raw


def check_tel(raw, field):
    if not re.fullmatch(r"[0-9+().\-\s]+", raw):
        raise FieldError("Enter a phone number using digits, spaces, + ( ) . or -.")
    return raw


def check_textarea(raw, field):
    if len(raw.encode("utf-8")) > 65_535:
        raise FieldError("These notes are too long.")
    return raw


def check_text(raw, field):
    return raw


VALIDATORS = {
    "company": check_company, "job": check_job, "money": check_money,
    "date": check_date, "select": check_select, "boolean": check_boolean,
    "json": check_json, "url": check_url, "email": check_email, "tel": check_tel,
    "textarea": check_textarea, "text": check_text,
}


def validate_form(entity, submitted):
    values, errors = {}, {}
    for field in entity.fields:
        raw = submitted.get(field.name, "").strip()
        values[field.name] = None
        if not raw:
            if field.required:
                errors[field.name] = f"{field.label} is required."
            continue
        if field.limit and len(raw) > field.limit:
            errors[field.name] = f"Use at most {field.limit} characters."
            continue
        try:
            values[field.name] = VALIDATORS[field.kind](raw, field)
        except FieldError as error:
            errors[field.name] = str(error)
    lower, upper = values.get("salary_min"), values.get("salary_max")
    if lower is not None and upper is not None and lower > upper:
        errors["salary_max"] = "Maximum salary must be at least the minimum salary."
    return values, errors


# ---------------------------------------------------------------------------
# Job matching (deterministic, no network calls)
# ---------------------------------------------------------------------------


def required_skills(requirements):
    """Read the project format, or an existing job's plain JSON array."""
    if isinstance(requirements, (str, bytes)):
        try:
            requirements = json.loads(requirements)
        except (ValueError, UnicodeError, RecursionError):
            return []
    if isinstance(requirements, dict):
        requirements = requirements.get("skills")
    if not isinstance(requirements, list):
        return []
    return [skill.strip() for skill in requirements
            if isinstance(skill, str) and skill.strip()]


def skill_key(skill):
    """Ignore case, spacing and . _ - so 'Node.js', 'nodejs' and 'node js' match."""
    return re.sub(r"[\s._-]+", "", skill.casefold())


def rank_jobs(jobs, skill_text):
    """Return (ranked results, number of jobs skipped for having no skill list)."""
    user_skills = {skill_key(part) for part in re.split(r"[,\n]", skill_text)
                   if skill_key(part)}
    results, skipped = [], 0
    for job in jobs:
        unique_required = {}
        for skill in required_skills(job["requirements"]):
            if skill_key(skill):
                unique_required.setdefault(skill_key(skill), skill)
        if not unique_required:
            skipped += 1
            continue
        matched = sum(key in user_skills for key in unique_required)
        total = len(unique_required)
        results.append({
            "job_id": job["job_id"],
            "job_title": job["job_title"],
            "company_name": job["company_name"],
            "matched": matched,
            "total": total,
            "percent": round(100 * matched / total),
            "missing": [label for key, label in unique_required.items()
                        if key not in user_skills],
        })
    results.sort(key=lambda result: (
        -Fraction(result["matched"], result["total"]),
        result["job_title"].casefold(),
        result["job_id"],
    ))
    return results, skipped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_record(entity, record_id):
    row = db.fetch_one(
        f"SELECT {entity.select} {entity.source} WHERE t.{entity.pk} = %s", (record_id,)
    )
    if row is None:
        abort(404)
    return row


def load_choices(entity):
    options = {}
    for field in entity.fields:
        if field.kind == "company":
            options[field.name] = db.fetch_all(
                "SELECT company_id AS id, company_name AS label FROM companies "
                "ORDER BY company_name, company_id"
            )
        elif field.kind == "job":
            options[field.name] = db.fetch_all(
                "SELECT j.job_id AS id, j.job_title AS label, c.company_name "
                "FROM jobs j LEFT JOIN companies c ON j.company_id = c.company_id "
                "ORDER BY j.job_title, j.job_id"
            )
    return options


def for_display(field, value):
    if value is None:
        return ""
    if field.kind == "json":
        try:
            parsed = json.loads(value) if isinstance(value, (str, bytes)) else value
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except (ValueError, TypeError, RecursionError):
            return str(value)
    return value


def handle_form(table, record_id=None):
    entity = ENTITIES[table]
    row = get_record(entity, record_id) if record_id is not None else {}
    errors = {}
    if request.method == "POST":
        submitted = request.form
        values, errors = validate_form(entity, submitted)
        if not errors:
            columns = tuple(values)
            params = tuple(values.values())
            try:
                if record_id is None:
                    placeholders = ", ".join(["%s"] * len(columns))
                    record_id = db.execute(
                        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                        params,
                    )
                else:
                    assignments = ", ".join(f"{column} = %s" for column in columns)
                    db.execute(
                        f"UPDATE {table} SET {assignments} WHERE {entity.pk} = %s",
                        (*params, record_id),
                    )
                flash(f"{entity.singular} saved.")
                return redirect(url_for("detail_record", table=table, record_id=record_id))
            except Error as error:
                message = DB_USER_ERRORS.get(error.errno)
                if message is None:
                    raise
                errors["_form"] = message
    else:
        submitted = {field.name: for_display(field, row.get(field.name))
                     for field in entity.fields}
    heading = ("Edit " if record_id is not None else "Add ") + entity.singular.lower()
    return render_template(
        f"{table}.html", mode="form", page_title=heading, entity=entity, table=table,
        record_id=record_id, values=submitted, errors=errors,
        options=load_choices(entity),
    ), 400 if errors else 200


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
def dashboard():
    totals = {row["name"]: row["total"] for row in db.fetch_all(COUNT_SQL)}
    counts = [(entity.title, table, totals.get(table, 0)) for table, entity in ENTITIES.items()]
    by_status = {row["status"]: row["total"] for row in db.fetch_all(
        "SELECT status, COUNT(*) AS total FROM applications GROUP BY status"
    )}
    statuses = {status: by_status.pop(status, 0) for status in STATUSES}
    statuses["Not recorded"] = by_status.pop(None, 0)
    if by_status:  # statuses stored in the database that this app does not list
        statuses["Other"] = sum(by_status.values())
    return render_template("dashboard.html", counts=counts, statuses=statuses)


@app.route("/job-match", methods=["GET", "POST"])
def job_match():
    skills, results, skipped, error = "", None, 0, None
    if request.method == "POST":
        skills = request.form.get("skills", "").strip()
        if not any(value.strip() for value in re.split(r"[,\n]", skills)):
            error = "Enter at least one skill."
        elif len(skills) > 2000:
            error = "Enter no more than 2,000 characters."
        else:
            jobs = db.fetch_all(
                "SELECT t.job_id, t.job_title, t.requirements, c.company_name "
                "FROM jobs t LEFT JOIN companies c ON t.company_id = c.company_id"
            )
            results, skipped = rank_jobs(jobs, skills)
    return render_template(
        "job_match.html", skills=skills, results=results, skipped=skipped, error=error
    ), (400 if error else 200)


@app.get("/<table:table>")
def list_records(table):
    entity = ENTITIES[table]
    q = request.args.get("q", "").strip()[:100]
    where, params = "", ()
    if q:
        pattern = "%" + re.sub(r"([\\%_])", r"\\\1", q) + "%"
        where = " WHERE (" + " OR ".join(f"{column} LIKE %s" for column in entity.search) + ")"
        params = (pattern,) * len(entity.search)
    total = db.fetch_one(f"SELECT COUNT(*) AS total {entity.source}{where}", params)["total"]
    pages = max(ceil(total / PER_PAGE), 1)
    page = min(max(request.args.get("page", 1, type=int), 1), pages)
    rows = db.fetch_all(
        f"SELECT {entity.select} {entity.source}{where} {entity.order} LIMIT %s OFFSET %s",
        (*params, PER_PAGE, (page - 1) * PER_PAGE),
    )
    return render_template(
        f"{table}.html", mode="list", page_title=entity.title, entity=entity, table=table,
        rows=rows, q=q, page=page, pages=pages, total=total,
    )


@app.route("/<table:table>/add", methods=["GET", "POST"])
def add_record(table):
    return handle_form(table)


@app.get("/<table:table>/<int:record_id>")
def detail_record(table, record_id):
    entity = ENTITIES[table]
    row = get_record(entity, record_id)
    fields = []
    for field in entity.fields:
        value = row[field.name]
        if field.kind == "company" and value is not None:
            value = row.get("company_name") or value
        elif field.kind == "job" and value is not None:
            value = row.get("job_title") or value
        elif field.kind == "boolean" and value is not None:
            value = "Yes" if value else "No"
        fields.append((field, for_display(field, value)))
    return render_template(
        f"{table}.html", mode="detail", page_title=f"{entity.singular} #{record_id}",
        entity=entity, table=table, record_id=record_id, fields=fields,
    )


@app.route("/<table:table>/<int:record_id>/edit", methods=["GET", "POST"])
def edit_record(table, record_id):
    return handle_form(table, record_id)


@app.route("/<table:table>/<int:record_id>/delete", methods=["GET", "POST"])
def delete_record(table, record_id):
    entity = ENTITIES[table]
    row = get_record(entity, record_id)
    if request.method == "GET":
        return render_template(
            f"{table}.html", mode="delete", page_title="Confirm deletion", entity=entity,
            table=table, record_id=record_id, name=entity.label(row),
        )
    try:
        db.execute(f"DELETE FROM {table} WHERE {entity.pk} = %s", (record_id,))
        flash(f"{entity.singular} deleted.")
    except Error as error:
        if error.errno != ec.ER_ROW_IS_REFERENCED_2:
            raise
        flash("This record is still in use. Remove or reassign related records first.", "error")
        return redirect(url_for("detail_record", table=table, record_id=record_id))
    return redirect(url_for("list_records", table=table))


# ---------------------------------------------------------------------------
# Error pages (rendered through base.html, so no separate error template)
# ---------------------------------------------------------------------------

ERROR_PAGE = """{% extends "base.html" %}
{% block title %}{{ title }}{% endblock %}
{% block content %}
<h1>{{ title }}</h1>
<p>{{ message }}</p>
<p><a href="{{ url_for('dashboard') }}">Back to dashboard</a></p>
{% endblock %}"""


def error_page(title, message, status):
    return render_template_string(ERROR_PAGE, title=title, message=message), status


@app.errorhandler(Error)
def database_error(error):
    app.logger.exception("MySQL request failed (error code %s)", error.errno)
    message = DB_USER_ERRORS.get(error.errno)
    if message:
        return error_page("Could not save", message, 400)
    return error_page(
        "Database request failed",
        "Check that MySQL is running and that your database settings are correct.", 503,
    )


@app.errorhandler(HTTPException)
def http_error(error):
    return error_page(error.name, error.description, error.code)


@app.errorhandler(Exception)
def unexpected_error(error):
    app.logger.exception("Unhandled error")
    return error_page("Something went wrong", "An unexpected error occurred. Please try again.", 500)


if __name__ == "__main__":
    app.run()  # development server; use a production server such as waitress if deploying
