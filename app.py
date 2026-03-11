import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DB_PATH = os.path.join(INSTANCE_DIR, "el_raheem.db")

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
    instance_path=INSTANCE_DIR,
)
app.config["SECRET_KEY"] = os.environ.get("EL_RAHEEM_SECRET_KEY", "el-raheem-dev-key")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "الرجاء تسجيل الدخول أولاً."
login_manager.init_app(app)


class User(UserMixin):
    def __init__(self, user_id: int, full_name: str, username: str, role: str) -> None:
        self.id = str(user_id)
        self.full_name = full_name
        self.username = username
        self.role = role

    @staticmethod
    def from_row(row: sqlite3.Row) -> "User":
        return User(
            user_id=row["id"],
            full_name=row["full_name"],
            username=row["username"],
            role=row["role"],
        )

    @staticmethod
    def get(user_id: str) -> "User | None":
        db = get_db()
        row = db.execute(
            "SELECT id, full_name, username, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return User.from_row(row) if row else None

    @staticmethod
    def get_by_username(username: str) -> sqlite3.Row | None:
        db = get_db()
        return db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return User.get(user_id)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('patient', 'admin')),
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reservation_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            capacity INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slot_id INTEGER NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'confirmed',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, slot_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (slot_id) REFERENCES reservation_slots(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            response TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'answered')),
            created_at TEXT NOT NULL,
            responded_at TEXT,
            responded_by INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (responded_by) REFERENCES users(id)
        )
        """
    )

    db.commit()

    seed_user(cursor, "مدير المركز", "admin", "Admin@123", "admin")
    seed_user(cursor, "مراجع تجريبي", "user", "User@123", "patient")

    db.commit()
    db.close()


def seed_user(cursor: sqlite3.Cursor, full_name: str, username: str, password: str, role: str) -> None:
    exists = cursor.execute(
        "SELECT 1 FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if exists:
        return

    cursor.execute(
        """
        INSERT INTO users (full_name, username, password_hash, role, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            full_name,
            username,
            generate_password_hash(password),
            role,
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )


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
def dt_ar_filter(value: str) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y/%m/%d - %H:%M")
    except ValueError:
        return value


@app.route("/")
def home():
    db = get_db()
    upcoming_slots = db.execute(
        """
        SELECT
            s.id,
            s.start_time,
            s.end_time,
            s.capacity,
            s.is_active,
            COUNT(r.id) AS booked
        FROM reservation_slots s
        LEFT JOIN reservations r ON r.slot_id = s.id AND r.status = 'confirmed'
        WHERE s.is_active = 1 AND s.start_time >= ?
        GROUP BY s.id
        ORDER BY s.start_time ASC
        LIMIT 4
        """,
        (datetime.utcnow().isoformat(timespec="minutes"),),
    ).fetchall()

    totals = db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM users WHERE role = 'patient') AS patients_count,
            (SELECT COUNT(*) FROM reservation_slots WHERE is_active = 1) AS active_slots,
            (SELECT COUNT(*) FROM reservations WHERE status = 'confirmed') AS reservations_count
        """
    ).fetchone()

    return render_template(
        "home.html",
        upcoming_slots=upcoming_slots,
        totals=totals,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        row = User.get_by_username(username)
        if not row or not check_password_hash(row["password_hash"], password):
            flash("بيانات الدخول غير صحيحة.", "error")
            return render_template("login.html")

        login_user(User.from_row(row))
        flash(f"مرحباً {row['full_name']}!", "success")

        next_url = request.args.get("next")
        if next_url:
            return redirect(next_url)
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        if len(full_name) < 3:
            flash("الاسم يجب أن يكون 3 أحرف على الأقل.", "error")
            return render_template("register.html")

        if len(username) < 3 or " " in username:
            flash("اسم المستخدم غير صالح.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("كلمة المرور يجب أن تكون 6 أحرف على الأقل.", "error")
            return render_template("register.html")

        db = get_db()
        exists = db.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if exists:
            flash("اسم المستخدم مستخدم بالفعل.", "error")
            return render_template("register.html")

        db.execute(
            """
            INSERT INTO users (full_name, username, password_hash, role, created_at)
            VALUES (?, ?, ?, 'patient', ?)
            """,
            (
                full_name,
                username,
                generate_password_hash(password),
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        db.commit()

        user_row = User.get_by_username(username)
        login_user(User.from_row(user_row))
        flash("تم إنشاء الحساب بنجاح.", "success")
        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("تم تسجيل الخروج.", "success")
    return redirect(url_for("home"))


@app.route("/reservations")
@login_required
def reservations():
    db = get_db()
    now = datetime.utcnow().isoformat(timespec="minutes")

    slots = db.execute(
        """
        SELECT
            s.id,
            s.start_time,
            s.end_time,
            s.capacity,
            s.is_active,
            COUNT(r.id) AS booked
        FROM reservation_slots s
        LEFT JOIN reservations r ON r.slot_id = s.id AND r.status = 'confirmed'
        WHERE s.is_active = 1 AND s.start_time >= ?
        GROUP BY s.id
        ORDER BY s.start_time ASC
        """,
        (now,),
    ).fetchall()

    my_reservations = db.execute(
        """
        SELECT r.id, r.notes, r.status, r.created_at, s.start_time, s.end_time
        FROM reservations r
        JOIN reservation_slots s ON s.id = r.slot_id
        WHERE r.user_id = ?
        ORDER BY s.start_time ASC
        """,
        (current_user.id,),
    ).fetchall()

    return render_template(
        "reservations.html",
        slots=slots,
        my_reservations=my_reservations,
    )


@app.route("/reservations/book/<int:slot_id>", methods=["POST"])
@login_required
def book_slot(slot_id: int):
    db = get_db()
    slot = db.execute(
        "SELECT * FROM reservation_slots WHERE id = ? AND is_active = 1",
        (slot_id,),
    ).fetchone()

    if not slot:
        flash("هذا الموعد غير متاح.", "error")
        return redirect(url_for("reservations"))

    booked_count = db.execute(
        "SELECT COUNT(*) AS c FROM reservations WHERE slot_id = ? AND status = 'confirmed'",
        (slot_id,),
    ).fetchone()["c"]

    if booked_count >= slot["capacity"]:
        flash("تم حجز هذا الموعد بالكامل.", "error")
        return redirect(url_for("reservations"))

    exists = db.execute(
        "SELECT 1 FROM reservations WHERE user_id = ? AND slot_id = ?",
        (current_user.id, slot_id),
    ).fetchone()
    if exists:
        flash("لقد قمت بحجز هذا الموعد بالفعل.", "error")
        return redirect(url_for("reservations"))

    notes = request.form.get("notes", "").strip()

    db.execute(
        """
        INSERT INTO reservations (user_id, slot_id, notes, status, created_at)
        VALUES (?, ?, ?, 'confirmed', ?)
        """,
        (
            current_user.id,
            slot_id,
            notes,
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    db.commit()
    flash("تم تأكيد الحجز بنجاح.", "success")
    return redirect(url_for("reservations"))


@app.route("/reservations/cancel/<int:reservation_id>", methods=["POST"])
@login_required
def cancel_reservation(reservation_id: int):
    db = get_db()
    reservation = db.execute(
        "SELECT id FROM reservations WHERE id = ? AND user_id = ?",
        (reservation_id, current_user.id),
    ).fetchone()

    if not reservation:
        flash("لم يتم العثور على الحجز.", "error")
        return redirect(url_for("reservations"))

    db.execute("DELETE FROM reservations WHERE id = ?", (reservation_id,))
    db.commit()
    flash("تم إلغاء الحجز.", "success")
    return redirect(url_for("reservations"))


@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    db = get_db()

    if request.method == "POST" and current_user.role != "admin":
        body = request.form.get("message", "").strip()
        if len(body) < 5:
            flash("الرسالة قصيرة جداً.", "error")
            return redirect(url_for("chat"))

        pending = db.execute(
            "SELECT id FROM messages WHERE user_id = ? AND status = 'pending'",
            (current_user.id,),
        ).fetchone()
        if pending:
            flash("لديك رسالة قيد الانتظار. انتظر الرد قبل إرسال رسالة جديدة.", "error")
            return redirect(url_for("chat"))

        db.execute(
            """
            INSERT INTO messages (user_id, body, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (
                current_user.id,
                body,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        db.commit()
        flash("تم إرسال الرسالة إلى إدارة المركز.", "success")
        return redirect(url_for("chat"))

    if current_user.role == "admin":
        messages = db.execute(
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
        ).fetchall()
        return render_template("chat.html", messages=messages, has_pending=False)

    messages = db.execute(
        """
        SELECT id, body, response, status, created_at, responded_at
        FROM messages
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (current_user.id,),
    ).fetchall()

    has_pending = any(msg["status"] == "pending" for msg in messages)
    return render_template("chat.html", messages=messages, has_pending=has_pending)


@app.route("/admin/messages/respond/<int:message_id>", methods=["POST"])
@admin_required
def respond_message(message_id: int):
    response_text = request.form.get("response", "").strip()
    if len(response_text) < 3:
        flash("الرد قصير جداً.", "error")
        return redirect(request.referrer or url_for("admin_dashboard"))

    db = get_db()
    message_row = db.execute(
        "SELECT id, status FROM messages WHERE id = ?",
        (message_id,),
    ).fetchone()

    if not message_row:
        flash("الرسالة غير موجودة.", "error")
        return redirect(request.referrer or url_for("admin_dashboard"))

    if message_row["status"] == "answered":
        flash("تم الرد على هذه الرسالة بالفعل.", "error")
        return redirect(request.referrer or url_for("admin_dashboard"))

    db.execute(
        """
        UPDATE messages
        SET response = ?,
            status = 'answered',
            responded_at = ?,
            responded_by = ?
        WHERE id = ?
        """,
        (
            response_text,
            datetime.utcnow().isoformat(timespec="seconds"),
            current_user.id,
            message_id,
        ),
    )
    db.commit()
    flash("تم إرسال الرد بنجاح.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()

    slots = db.execute(
        """
        SELECT
            s.id,
            s.start_time,
            s.end_time,
            s.capacity,
            s.is_active,
            COUNT(r.id) AS booked
        FROM reservation_slots s
        LEFT JOIN reservations r ON r.slot_id = s.id AND r.status = 'confirmed'
        GROUP BY s.id
        ORDER BY s.start_time ASC
        """
    ).fetchall()

    pending_messages = db.execute(
        """
        SELECT m.id, m.body, m.created_at, u.full_name, u.username
        FROM messages m
        JOIN users u ON u.id = m.user_id
        WHERE m.status = 'pending'
        ORDER BY m.created_at ASC
        """
    ).fetchall()

    recent_reservations = db.execute(
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
    ).fetchall()

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

    db = get_db()
    db.execute(
        """
        INSERT INTO reservation_slots (start_time, end_time, capacity, is_active, created_by, created_at)
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        (
            start_dt.isoformat(timespec="minutes"),
            end_dt.isoformat(timespec="minutes"),
            capacity_num,
            current_user.id,
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    db.commit()

    flash("تمت إضافة الموعد بنجاح.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/slots/<int:slot_id>/toggle", methods=["POST"])
@admin_required
def toggle_slot(slot_id: int):
    db = get_db()
    slot = db.execute(
        "SELECT id, is_active FROM reservation_slots WHERE id = ?",
        (slot_id,),
    ).fetchone()

    if not slot:
        flash("الموعد غير موجود.", "error")
        return redirect(url_for("admin_dashboard"))

    new_value = 0 if slot["is_active"] else 1
    db.execute(
        "UPDATE reservation_slots SET is_active = ? WHERE id = ?",
        (new_value, slot_id),
    )
    db.commit()
    flash("تم تحديث حالة الموعد.", "success")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=True)
else:
    init_db()
