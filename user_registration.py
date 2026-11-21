"""
User Registration - backend (Flask blueprint + PostgreSQL).

Routes
    GET  /user-registration        -> registration page
    POST /api/user-registration    -> validate + store a registration (JSON)

Database credentials are read from environment variables (or a local .env
file that is git-ignored):
    DATABASE_URL                       (optional, takes precedence) or
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSLMODE
"""
import os
import re
import threading
import time
from collections import defaultdict, deque

import psycopg2
from psycopg2 import errors as pg_errors
from dotenv import load_dotenv
from flask import Blueprint, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

user_reg_bp = Blueprint("user_registration", __name__)

TABLE_NAME = "customer_registrations"
GENDERS = ("Male", "Female", "Other", "Prefer not to say")

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,99}$")
MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")          # valid Indian mobile numbers
PLACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'\-/()]{1,99}$")

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id                 BIGSERIAL PRIMARY KEY,
    full_name          VARCHAR(100) NOT NULL,
    country_code       VARCHAR(5)   NOT NULL DEFAULT '+91',
    mobile_number      VARCHAR(10)  NOT NULL,
    gender             VARCHAR(20)  NOT NULL,
    age                SMALLINT     NOT NULL,
    place              VARCHAR(100) NOT NULL,
    terms_accepted     BOOLEAN      NOT NULL,
    terms_accepted_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ip_address         VARCHAR(45),
    user_agent         VARCHAR(300),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT {TABLE_NAME}_mobile_uq    UNIQUE (country_code, mobile_number),
    CONSTRAINT {TABLE_NAME}_mobile_chk   CHECK (mobile_number ~ '^[6-9][0-9]{{9}}$'),
    CONSTRAINT {TABLE_NAME}_age_chk      CHECK (age BETWEEN 1 AND 120),
    CONSTRAINT {TABLE_NAME}_gender_chk   CHECK (gender IN ('Male','Female','Other','Prefer not to say')),
    CONSTRAINT {TABLE_NAME}_terms_chk    CHECK (terms_accepted IS TRUE)
);
CREATE INDEX IF NOT EXISTS {TABLE_NAME}_created_at_idx
    ON {TABLE_NAME} (created_at DESC);
"""

_table_ready = False
_table_lock = threading.Lock()


# ── Database helpers ─────────────────────────────────────────
def _env(*names, default=""):
    for name in names:
        val = os.environ.get(name)
        if val is not None and val.strip():
            return val.strip()
    return default


def _db_config():
    url = _env("DATABASE_URL")
    if url:
        return {"url": url, "sslmode": _env("DB_SSLMODE", "PGSSLMODE", default="require")}, []

    cfg = {
        "host": _env("DB_HOST", "PGHOST"),
        "port": _env("DB_PORT", "PGPORT", default="5432"),
        "dbname": _env("DB_NAME", "DB_DATABASE", "PGDATABASE"),
        "user": _env("DB_USER", "DB_USERNAME", "PGUSER"),
        "password": _env("DB_PASSWORD", "PGPASSWORD"),
        "sslmode": _env("DB_SSLMODE", "PGSSLMODE", default="require"),
    }
    missing = [k for k, env_name in (
        ("host", "DB_HOST"), ("dbname", "DB_NAME"),
        ("user", "DB_USER"), ("password", "DB_PASSWORD"),
    ) if not cfg[k]]
    missing_names = [env_name for k, env_name in (
        ("host", "DB_HOST"), ("dbname", "DB_NAME"),
        ("user", "DB_USER"), ("password", "DB_PASSWORD"),
    ) if k in missing]
    return cfg, missing_names


def get_connection():
    cfg, missing = _db_config()
    if missing:
        raise RuntimeError(f"Missing database environment variables: {', '.join(missing)}")
    if "url" in cfg:
        kwargs = {"connect_timeout": 10}
        if "sslmode=" not in cfg["url"]:
            kwargs["sslmode"] = cfg["sslmode"]
        return psycopg2.connect(cfg["url"], **kwargs)
    return psycopg2.connect(
        host=cfg["host"],
        port=int(cfg["port"]),
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        sslmode=cfg["sslmode"],
        connect_timeout=10,
    )


def ensure_table(conn=None):
    """Create the registrations table if it does not exist yet."""
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        own = conn is None
        conn = conn or get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLE_SQL)
            conn.commit()
            _table_ready = True
        finally:
            if own:
                conn.close()


# ── Validation ───────────────────────────────────────────────
def validate_payload(data):
    """Return (clean_dict, errors_dict)."""
    errors = {}

    full_name = re.sub(r"\s+", " ", str(data.get("fullName", "") or "")).strip()
    if not full_name:
        errors["fullName"] = "Full name is required."
    elif not NAME_RE.match(full_name):
        errors["fullName"] = "Enter a valid name (letters only, 2-100 characters)."

    mobile = re.sub(r"[\s\-]", "", str(data.get("mobile", "") or ""))
    if mobile.startswith("+91"):
        mobile = mobile[3:]
    if not mobile:
        errors["mobile"] = "Mobile number is required."
    elif not MOBILE_RE.match(mobile):
        errors["mobile"] = "Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9."

    gender = str(data.get("gender", "") or "").strip()
    if not gender:
        errors["gender"] = "Please select your gender."
    elif gender not in GENDERS:
        errors["gender"] = "Please select a valid option."

    age_raw = data.get("age", "")
    age_str = "" if age_raw is None else str(age_raw).strip()
    age = None
    if age_str == "":
        errors["age"] = "Age is required."
    else:
        try:
            if isinstance(age_raw, (bool, float)) or not re.fullmatch(r"\d{1,3}", age_str):
                raise ValueError
            age = int(age_str)
            if not 1 <= age <= 120:
                raise ValueError
        except ValueError:
            age = None
            errors["age"] = "Enter a valid age between 1 and 120."

    place = re.sub(r"\s+", " ", str(data.get("place", "") or "")).strip()
    if not place:
        errors["place"] = "Place is required."
    elif not PLACE_RE.match(place):
        errors["place"] = "Enter a valid place (2-100 characters)."

    if data.get("terms") is not True:
        errors["terms"] = "You must accept the Terms and Conditions and Privacy Policy."

    clean = {
        "full_name": full_name,
        "mobile_number": mobile,
        "gender": gender,
        "age": age,
        "place": place,
    }
    return clean, errors


# ── Simple in-memory rate limiter (per IP) ───────────────────
_hits = defaultdict(deque)
_hits_lock = threading.Lock()
RATE_LIMIT, RATE_WINDOW = 10, 60  # 10 submissions / minute / IP


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""


def _rate_limited(ip):
    now = time.time()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(now)
    return False


# ── Routes ───────────────────────────────────────────────────
@user_reg_bp.route("/user-registration")
def user_registration_page():
    return send_from_directory(BASE_DIR, "user_registration.html")


@user_reg_bp.route("/api/user-registration/health")
def user_registration_health():
    _, missing = _db_config()
    if missing:
        return jsonify({
            "ok": False,
            "status": "missing_db_env",
            "missing": missing,
        }), 503
    conn = None
    try:
        conn = get_connection()
        ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return jsonify({"ok": True, "status": "connected", "table": TABLE_NAME}), 200
    except Exception as exc:  # noqa: BLE001
        print(f"[UserRegistration] Health check DB error: {exc}")
        return jsonify({
            "ok": False,
            "status": "db_connection_failed",
            "error_type": type(exc).__name__,
        }), 503
    finally:
        if conn:
            conn.close()


@user_reg_bp.route("/api/user-registration", methods=["POST"])
def user_registration_submit():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Invalid request."}), 400

    # Honeypot: real users never fill this hidden field.
    if str(data.get("website", "")).strip():
        return jsonify({"success": True, "message": "Registration successful."}), 200

    ip = _client_ip()
    if _rate_limited(ip):
        return jsonify({"success": False,
                        "message": "Too many attempts. Please wait a minute and try again."}), 429

    clean, errors = validate_payload(data)
    if errors:
        return jsonify({"success": False, "message": "Please correct the highlighted fields.",
                        "errors": errors}), 400

    conn = None
    try:
        conn = get_connection()
        ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {TABLE_NAME}
                    (full_name, country_code, mobile_number, gender, age, place,
                     terms_accepted, ip_address, user_agent)
                    VALUES (%s, '+91', %s, %s, %s, %s, TRUE, %s, %s)
                    RETURNING id""",
                (clean["full_name"], clean["mobile_number"], clean["gender"],
                 clean["age"], clean["place"], ip[:45],
                 (request.headers.get("User-Agent", "") or "")[:300]),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({
            "success": True,
            "message": "Thank you! Your registration has been completed successfully.",
            "referenceId": f"REG-{new_id:06d}",
        }), 201
    except pg_errors.UniqueViolation:
        if conn:
            conn.rollback()
        return jsonify({
            "success": False,
            "message": "This mobile number is already registered.",
            "errors": {"mobile": "This mobile number is already registered."},
        }), 409
    except Exception as exc:  # noqa: BLE001 - never leak DB details to the client
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"[UserRegistration] DB error: {exc}")
        return jsonify({"success": False,
                        "message": "We couldn't save your registration right now. Please try again shortly."}), 500
    finally:
        if conn:
            conn.close()
