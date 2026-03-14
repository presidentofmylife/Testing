import json
import os
import secrets
from datetime import datetime
from functools import lru_cache, wraps
from urllib.parse import urljoin, urlparse

import requests
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from oauthlib.oauth2 import WebApplicationClient
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
SQLITE_DB_PATH = os.path.join(INSTANCE_DIR, "el_raheem.db")
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

load_dotenv(os.path.join(BASE_DIR, ".env"))


if not os.environ.get("VERCEL"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def utc_now(timespec: str = "seconds") -> str:
    return datetime.utcnow().isoformat(timespec=timespec)


def build_database_uri() -> str:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        return f"sqlite:///{SQLITE_DB_PATH}"

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return database_url


app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
    instance_path=INSTANCE_DIR,
)
app.config["SECRET_KEY"] = os.environ.get("EL_RAHEEM_SECRET_KEY", "el-raheem-dev-key")
app.config["SQLALCHEMY_DATABASE_URI"] = build_database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "الرجاء تسجيل الدخول أولاً."
login_manager.init_app(app)

users_table = db.Table(
    "users",
    db.metadata,
    db.Column("id", db.Integer, primary_key=True),
    db.Column("full_name", db.String(255), nullable=False),
    db.Column("username", db.String(255), nullable=False, unique=True),
    db.Column("password_hash", db.String(255), nullable=False, server_default="google-oauth"),
    db.Column("email", db.String(255), unique=True, index=True),
    db.Column("google_sub", db.String(255), unique=True, index=True),
    db.Column("avatar_url", db.Text),
    db.Column("role", db.String(20), nullable=False, server_default="patient"),
    db.Column("created_at", db.String(32), nullable=False),
)

reservation_slots_table = db.Table(
    "reservation_slots",
    db.metadata,
    db.Column("id", db.Integer, primary_key=True),
    db.Column("start_time", db.String(32), nullable=False),
    db.Column("end_time", db.String(32), nullable=False),
    db.Column("capacity", db.Integer, nullable=False, server_default="1"),
    db.Column("is_active", db.Integer, nullable=False, server_default="1"),
    db.Column("created_by", db.Integer, db.ForeignKey("users.id")),
    db.Column("created_at", db.String(32), nullable=False),
)

reservations_table = db.Table(
    "reservations",
    db.metadata,
    db.Column("id", db.Integer, primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), nullable=False),
    db.Column("slot_id", db.Integer, db.ForeignKey("reservation_slots.id"), nullable=False),
    db.Column("notes", db.Text),
    db.Column("status", db.String(20), nullable=False, server_default="confirmed"),
    db.Column("created_at", db.String(32), nullable=False),
    db.UniqueConstraint("user_id", "slot_id", name="uq_user_slot"),
)

messages_table = db.Table(
    "messages",
    db.metadata,
    db.Column("id", db.Integer, primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), nullable=False),
    db.Column("body", db.Text, nullable=False),
    db.Column("response", db.Text),
    db.Column("status", db.String(20), nullable=False, server_default="pending"),
    db.Column("created_at", db.String(32), nullable=False),
    db.Column("responded_at", db.String(32)),
    db.Column("responded_by", db.Integer, db.ForeignKey("users.id")),
)


class User(UserMixin):
    def __init__(
        self,
        user_id: int,
        full_name: str,
        username: str,
        role: str,
        email: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        self.id = int(user_id)
        self.full_name = full_name
        self.username = username
        self.role = role
        self.email = email
        self.avatar_url = avatar_url

    @staticmethod
    def from_row(row) -> "User":
        return User(
            user_id=row["id"],
            full_name=row["full_name"],
            username=row["username"],
            role=row["role"],
            email=row.get("email"),
            avatar_url=row.get("avatar_url"),
        )

    @staticmethod
    def get(user_id: str) -> "User | None":
        row = fetch_one(
            """
            SELECT id, full_name, username, role, email, avatar_url
            FROM users
            WHERE id = :user_id
            """,
            user_id=user_id,
        )
        return User.from_row(row) if row else None

    @staticmethod
    def get_by_google_sub(google_sub: str):
        return fetch_one(
            "SELECT * FROM users WHERE google_sub = :google_sub",
            google_sub=google_sub,
        )

    @staticmethod
    def get_by_email(email: str):
        return fetch_one(
            "SELECT * FROM users WHERE LOWER(email) = :email",
            email=email.strip().lower(),
        )


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return User.get(user_id)


def fetch_one(query: str, **params):
    return db.session.execute(text(query), params).mappings().first()


def fetch_all(query: str, **params):
    return db.session.execute(text(query), params).mappings().all()


def execute_sql(query: str, **params):
    return db.session.execute(text(query), params)


def rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def ensure_user_columns() -> None:
    inspector = inspect(db.engine)
    if not inspector.has_table("users"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    column_definitions = {
        "email": "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
        "google_sub": "ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)",
        "avatar_url": "ALTER TABLE users ADD COLUMN avatar_url TEXT",
    }

    missing = [ddl for name, ddl in column_definitions.items() if name not in existing_columns]
    if not missing:
        return

    with db.engine.begin() as connection:
        for ddl in missing:
            connection.execute(text(ddl))


def init_db() -> None:
    db.create_all()
    ensure_user_columns()


@lru_cache(maxsize=1)
def get_google_provider_cfg():
    response = requests.get(GOOGLE_DISCOVERY_URL, timeout=5)
    response.raise_for_status()
    return response.json()


@lru_cache(maxsize=1)
def get_admin_emails() -> set[str]:
    raw_value = os.environ.get("EL_RAHEEM_ADMIN_EMAILS", "")
    return {email.strip().lower() for email in raw_value.split(",") if email.strip()}


def get_google_oauth_config() -> tuple[str, str]:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

    missing = []
    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

    return client_id, client_secret


def get_google_redirect_uri() -> str:
    configured_uri = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if configured_uri:
        return configured_uri
    return url_for("google_callback_canonical", _external=True)


def is_safe_redirect_target(target: str | None) -> bool:
    if not target:
        return False

    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in {"http", "https"} and ref_url.netloc == test_url.netloc


def get_requested_next_url() -> str | None:
    next_url = request.args.get("next", "").strip()
    return next_url if is_safe_redirect_target(next_url) else None


def build_unique_username(email: str, google_sub: str, exclude_user_id: int | None = None) -> str:
    email = email.strip().lower()
    local_part = email.split("@", 1)[0] or "google-user"
    candidates = [email, f"{local_part}-{google_sub[:8].lower()}", f"{local_part}-{google_sub.lower()}"]

    for candidate in candidates:
        if not candidate:
            continue
        params = {"username": candidate}
        query = "SELECT id FROM users WHERE username = :username"
        if exclude_user_id is not None:
            query += " AND id != :exclude_user_id"
            params["exclude_user_id"] = exclude_user_id
        if not fetch_one(query, **params):
            return candidate

    return f"google-user-{google_sub.lower()}"


def sync_google_user(*, google_sub: str, email: str, full_name: str, avatar_url: str | None) -> User:
    existing_row = User.get_by_google_sub(google_sub)
    if not existing_row:
        existing_row = User.get_by_email(email)

    role = "admin" if email in get_admin_emails() else "patient"
    username = build_unique_username(email, google_sub, existing_row["id"] if existing_row else None)

    if existing_row:
        execute_sql(
            """
            UPDATE users
            SET full_name = :full_name,
                username = :username,
                password_hash = :password_hash,
                email = :email,
                google_sub = :google_sub,
                avatar_url = :avatar_url,
                role = :role
            WHERE id = :user_id
            """,
            full_name=full_name,
            username=username,
            password_hash=existing_row.get("password_hash") or "google-oauth",
            email=email,
            google_sub=google_sub,
            avatar_url=avatar_url or existing_row.get("avatar_url"),
            role=role,
            user_id=existing_row["id"],
        )
    else:
        execute_sql(
            """
            INSERT INTO users (
                full_name,
                username,
                password_hash,
                email,
                google_sub,
                avatar_url,
                role,
                created_at
            )
            VALUES (
                :full_name,
                :username,
                :password_hash,
                :email,
                :google_sub,
                :avatar_url,
                :role,
                :created_at
            )
            """,
            full_name=full_name,
            username=username,
            password_hash="google-oauth",
            email=email,
            google_sub=google_sub,
            avatar_url=avatar_url,
            role=role,
            created_at=utc_now(),
        )

    db.session.commit()
    user_row = User.get_by_google_sub(google_sub) or User.get_by_email(email)
    if not user_row:
        raise RuntimeError("Failed to persist Google user.")
    return User.from_row(user_row)


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            flash("هذه الصفحة مخصصة للمشرفين فقط.", "error")
            return redirect(url_for("home"))
        return view_func(*args, **kwargs)

    return wrapped


@app.template_filter("dt_ar")
def dt_ar_filter(value) -> str:
    if not value:
        return "-"
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return dt.strftime("%Y/%m/%d - %H:%M")
    except ValueError:
        return str(value)


@app.route("/")
def home():
    upcoming_slots = rows_to_dicts(
        fetch_all(
            """
            SELECT
                s.id,
                s.start_time,
                s.end_time,
                s.capacity,
                s.is_active,
                COUNT(r.id) AS booked
            FROM reservation_slots s
            LEFT JOIN reservations r
                ON r.slot_id = s.id
                AND r.status = 'confirmed'
            WHERE s.is_active = 1
                AND s.start_time >= :now
            GROUP BY s.id, s.start_time, s.end_time, s.capacity, s.is_active
            ORDER BY s.start_time ASC
            LIMIT 4
            """,
            now=utc_now("minutes"),
        )
    )

    totals_row = fetch_one(
        """
        SELECT
            (SELECT COUNT(*) FROM users WHERE role = 'patient') AS patients_count,
            (SELECT COUNT(*) FROM reservation_slots WHERE is_active = 1) AS active_slots,
            (SELECT COUNT(*) FROM reservations WHERE status = 'confirmed') AS reservations_count
        """
    )
    totals = dict(totals_row) if totals_row else {
        "patients_count": 0,
        "active_slots": 0,
        "reservations_count": 0,
    }

    return render_template("home.html", upcoming_slots=upcoming_slots, totals=totals)


@app.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect(get_requested_next_url() or url_for("home"))

    return render_template(
        "login.html",
        google_auth_url=url_for("google_login", next=get_requested_next_url()),
    )


@app.route("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    return render_template(
        "register.html",
        google_auth_url=url_for("google_login", next=get_requested_next_url()),
    )


@app.route("/login/google")
@app.route("/auth/google")
def google_login():
    if current_user.is_authenticated:
        return redirect(get_requested_next_url() or url_for("home"))

    try:
        client_id, _client_secret = get_google_oauth_config()
        client = WebApplicationClient(client_id)
        google_provider_cfg = get_google_provider_cfg()
        authorization_endpoint = google_provider_cfg["authorization_endpoint"]

        state = secrets.token_urlsafe(32)
        session["google_oauth_state"] = state

        next_url = get_requested_next_url()
        if next_url:
            session["post_login_redirect"] = next_url
        else:
            session.pop("post_login_redirect", None)

        request_uri = client.prepare_request_uri(
            authorization_endpoint,
            redirect_uri=get_google_redirect_uri(),
            scope=["openid", "email", "profile"],
            state=state,
        )
        return redirect(request_uri)
    except Exception:
        app.logger.exception("Google login bootstrap failed")
        flash("تعذّر بدء تسجيل الدخول. حاول مرة أخرى لاحقاً.", "error")
        return redirect(url_for("login"))


@app.route("/login/callback", endpoint="google_callback")
@app.route("/auth/google/callback", endpoint="google_callback_canonical")
def google_callback():
    expected_state = session.pop("google_oauth_state", None)
    received_state = request.args.get("state")
    if not expected_state or received_state != expected_state:
        flash("تعذّر إتمام تسجيل الدخول. حاول مرة أخرى.", "error")
        return redirect(url_for("login"))

    code = request.args.get("code")
    if not code:
        flash("تعذّر إتمام تسجيل الدخول. حاول مرة أخرى.", "error")
        return redirect(url_for("login"))

    try:
        client_id, client_secret = get_google_oauth_config()
        client = WebApplicationClient(client_id)
        google_provider_cfg = get_google_provider_cfg()

        token_url, headers, body = client.prepare_token_request(
            google_provider_cfg["token_endpoint"],
            authorization_response=request.url,
            redirect_url=get_google_redirect_uri(),
            code=code,
        )
        token_response = requests.post(
            token_url,
            headers=headers,
            data=body,
            auth=(client_id, client_secret),
            timeout=10,
        )
        token_response.raise_for_status()
        client.parse_request_body_response(json.dumps(token_response.json()))

        uri, headers, body = client.add_token(google_provider_cfg["userinfo_endpoint"])
        userinfo_response = requests.get(uri, headers=headers, data=body, timeout=10)
        userinfo_response.raise_for_status()
        user_info = userinfo_response.json()

        if not user_info.get("email_verified"):
            flash("تعذّر إتمام تسجيل الدخول بهذا الحساب.", "error")
            return redirect(url_for("login"))

        email = user_info["email"].strip().lower()
        google_sub = user_info["sub"]
        full_name = (user_info.get("name") or user_info.get("given_name") or email.split("@", 1)[0]).strip()
        avatar_url = user_info.get("picture")

        user = sync_google_user(
            google_sub=google_sub,
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
        )
        login_user(user)
        flash(f"مرحباً {user.full_name}!", "success")

        next_url = session.pop("post_login_redirect", None)
        return redirect(next_url if is_safe_redirect_target(next_url) else url_for("home"))
    except Exception:
        db.session.rollback()
        app.logger.exception("Google callback failed")
        flash("فشل تسجيل الدخول. حاول مرة أخرى لاحقاً.", "error")
        return redirect(url_for("login"))


@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop("google_oauth_state", None)
    session.pop("post_login_redirect", None)
    flash("تم تسجيل الخروج.", "success")
    return redirect(url_for("home"))


@app.route("/reservations")
@login_required
def reservations():
    now = utc_now("minutes")

    slots = rows_to_dicts(
        fetch_all(
            """
            SELECT
                s.id,
                s.start_time,
                s.end_time,
                s.capacity,
                s.is_active,
                COUNT(r.id) AS booked
            FROM reservation_slots s
            LEFT JOIN reservations r
                ON r.slot_id = s.id
                AND r.status = 'confirmed'
            WHERE s.is_active = 1
                AND s.start_time >= :now
            GROUP BY s.id, s.start_time, s.end_time, s.capacity, s.is_active
            ORDER BY s.start_time ASC
            """,
            now=now,
        )
    )

    my_reservations = rows_to_dicts(
        fetch_all(
            """
            SELECT
                r.id,
                r.notes,
                r.status,
                r.created_at,
                s.start_time,
                s.end_time
            FROM reservations r
            JOIN reservation_slots s ON s.id = r.slot_id
            WHERE r.user_id = :user_id
            ORDER BY s.start_time ASC
            """,
            user_id=current_user.id,
        )
    )

    return render_template("reservations.html", slots=slots, my_reservations=my_reservations)


@app.route("/reservations/book/<int:slot_id>", methods=["POST"])
@login_required
def book_slot(slot_id: int):
    slot = fetch_one(
        "SELECT * FROM reservation_slots WHERE id = :slot_id AND is_active = 1",
        slot_id=slot_id,
    )
    if not slot:
        flash("هذا الموعد غير متاح.", "error")
        return redirect(url_for("reservations"))

    booked_count_row = fetch_one(
        """
        SELECT COUNT(*) AS c
        FROM reservations
        WHERE slot_id = :slot_id
            AND status = 'confirmed'
        """,
        slot_id=slot_id,
    )
    booked_count = booked_count_row["c"] if booked_count_row else 0

    if booked_count >= slot["capacity"]:
        flash("تم حجز هذا الموعد بالكامل.", "error")
        return redirect(url_for("reservations"))

    exists = fetch_one(
        "SELECT 1 AS found FROM reservations WHERE user_id = :user_id AND slot_id = :slot_id",
        user_id=current_user.id,
        slot_id=slot_id,
    )
    if exists:
        flash("لقد قمت بحجز هذا الموعد بالفعل.", "error")
        return redirect(url_for("reservations"))

    notes = request.form.get("notes", "").strip()
    execute_sql(
        """
        INSERT INTO reservations (user_id, slot_id, notes, status, created_at)
        VALUES (:user_id, :slot_id, :notes, 'confirmed', :created_at)
        """,
        user_id=current_user.id,
        slot_id=slot_id,
        notes=notes,
        created_at=utc_now(),
    )
    db.session.commit()
    flash("تم تأكيد الحجز بنجاح.", "success")
    return redirect(url_for("reservations"))


@app.route("/reservations/cancel/<int:reservation_id>", methods=["POST"])
@login_required
def cancel_reservation(reservation_id: int):
    reservation = fetch_one(
        "SELECT id FROM reservations WHERE id = :reservation_id AND user_id = :user_id",
        reservation_id=reservation_id,
        user_id=current_user.id,
    )
    if not reservation:
        flash("لم يتم العثور على الحجز.", "error")
        return redirect(url_for("reservations"))

    execute_sql("DELETE FROM reservations WHERE id = :reservation_id", reservation_id=reservation_id)
    db.session.commit()
    flash("تم إلغاء الحجز.", "success")
    return redirect(url_for("reservations"))


@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    if request.method == "POST" and current_user.role != "admin":
        body = request.form.get("message", "").strip()
        if len(body) < 5:
            flash("الرسالة قصيرة جداً.", "error")
            return redirect(url_for("chat"))

        pending = fetch_one(
            "SELECT id FROM messages WHERE user_id = :user_id AND status = 'pending'",
            user_id=current_user.id,
        )
        if pending:
            flash("لديك رسالة قيد الانتظار. انتظر الرد قبل إرسال رسالة جديدة.", "error")
            return redirect(url_for("chat"))

        execute_sql(
            """
            INSERT INTO messages (user_id, body, status, created_at)
            VALUES (:user_id, :body, 'pending', :created_at)
            """,
            user_id=current_user.id,
            body=body,
            created_at=utc_now(),
        )
        db.session.commit()
        flash("تم إرسال الرسالة إلى إدارة المركز.", "success")
        return redirect(url_for("chat"))

    if current_user.role == "admin":
        messages = rows_to_dicts(
            fetch_all(
                """
                SELECT
                    m.id,
                    m.body,
                    m.response,
                    m.status,
                    m.created_at,
                    m.responded_at,
                    u.full_name,
                    u.username
                FROM messages m
                JOIN users u ON u.id = m.user_id
                ORDER BY
                    CASE WHEN m.status = 'pending' THEN 0 ELSE 1 END,
                    m.created_at DESC
                """
            )
        )
        return render_template("chat.html", messages=messages, has_pending=False)

    messages = rows_to_dicts(
        fetch_all(
            """
            SELECT id, body, response, status, created_at, responded_at
            FROM messages
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            """,
            user_id=current_user.id,
        )
    )
    has_pending = any(message["status"] == "pending" for message in messages)
    return render_template("chat.html", messages=messages, has_pending=has_pending)


@app.route("/admin/messages/respond/<int:message_id>", methods=["POST"])
@admin_required
def respond_message(message_id: int):
    response_text = request.form.get("response", "").strip()
    if len(response_text) < 3:
        flash("الرد قصير جداً.", "error")
        return redirect(request.referrer or url_for("admin_dashboard"))

    message_row = fetch_one(
        "SELECT id, status FROM messages WHERE id = :message_id",
        message_id=message_id,
    )
    if not message_row:
        flash("الرسالة غير موجودة.", "error")
        return redirect(request.referrer or url_for("admin_dashboard"))

    if message_row["status"] == "answered":
        flash("تم الرد على هذه الرسالة بالفعل.", "error")
        return redirect(request.referrer or url_for("admin_dashboard"))

    execute_sql(
        """
        UPDATE messages
        SET response = :response_text,
            status = 'answered',
            responded_at = :responded_at,
            responded_by = :responded_by
        WHERE id = :message_id
        """,
        response_text=response_text,
        responded_at=utc_now(),
        responded_by=current_user.id,
        message_id=message_id,
    )
    db.session.commit()
    flash("تم إرسال الرد بنجاح.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    slots = rows_to_dicts(
        fetch_all(
            """
            SELECT
                s.id,
                s.start_time,
                s.end_time,
                s.capacity,
                s.is_active,
                COUNT(r.id) AS booked
            FROM reservation_slots s
            LEFT JOIN reservations r
                ON r.slot_id = s.id
                AND r.status = 'confirmed'
            GROUP BY s.id, s.start_time, s.end_time, s.capacity, s.is_active
            ORDER BY s.start_time ASC
            """
        )
    )

    pending_messages = rows_to_dicts(
        fetch_all(
            """
            SELECT
                m.id,
                m.body,
                m.created_at,
                u.full_name,
                u.username
            FROM messages m
            JOIN users u ON u.id = m.user_id
            WHERE m.status = 'pending'
            ORDER BY m.created_at ASC
            """
        )
    )

    recent_reservations = rows_to_dicts(
        fetch_all(
            """
            SELECT
                r.id,
                r.notes,
                r.created_at,
                u.full_name,
                s.start_time,
                s.end_time
            FROM reservations r
            JOIN users u ON u.id = r.user_id
            JOIN reservation_slots s ON s.id = r.slot_id
            ORDER BY r.created_at DESC
            LIMIT 12
            """
        )
    )

    return render_template(
        "admin.html",
        slots=slots,
        pending_messages=pending_messages,
        recent_reservations=recent_reservations,
    )


@app.route("/admin/slots/add", methods=["POST"])
@admin_required
def add_slot():
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()
    capacity = request.form.get("capacity", "1").strip()

    try:
        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)
        capacity_num = int(capacity)
    except ValueError:
        flash("بيانات الموعد غير صالحة.", "error")
        return redirect(url_for("admin_dashboard"))

    if end_dt <= start_dt:
        flash("وقت النهاية يجب أن يكون بعد وقت البداية.", "error")
        return redirect(url_for("admin_dashboard"))

    if capacity_num < 1 or capacity_num > 20:
        flash("السعة يجب أن تكون بين 1 و 20.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_sql(
        """
        INSERT INTO reservation_slots (
            start_time,
            end_time,
            capacity,
            is_active,
            created_by,
            created_at
        )
        VALUES (
            :start_time,
            :end_time,
            :capacity,
            1,
            :created_by,
            :created_at
        )
        """,
        start_time=start_dt.isoformat(timespec="minutes"),
        end_time=end_dt.isoformat(timespec="minutes"),
        capacity=capacity_num,
        created_by=current_user.id,
        created_at=utc_now(),
    )
    db.session.commit()
    flash("تمت إضافة الموعد بنجاح.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/slots/<int:slot_id>/toggle", methods=["POST"])
@admin_required
def toggle_slot(slot_id: int):
    slot = fetch_one(
        "SELECT id, is_active FROM reservation_slots WHERE id = :slot_id",
        slot_id=slot_id,
    )
    if not slot:
        flash("الموعد غير موجود.", "error")
        return redirect(url_for("admin_dashboard"))

    new_value = 0 if slot["is_active"] else 1
    execute_sql(
        "UPDATE reservation_slots SET is_active = :is_active WHERE id = :slot_id",
        is_active=new_value,
        slot_id=slot_id,
    )
    db.session.commit()
    flash("تم تحديث حالة الموعد.", "success")
    return redirect(url_for("admin_dashboard"))


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5050)),
        debug=os.environ.get("FLASK_ENV") != "production",
    )
