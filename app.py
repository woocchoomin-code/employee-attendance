
import os
import csv
import io
from datetime import datetime, date

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Render / PostgreSQL 배포용
database_url = os.environ.get("DATABASE_URL", "sqlite:///attendance.db")
# 일부 서비스는 postgres:// 로 주므로 SQLAlchemy 호환 형식으로 보정
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")

class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    pin = db.Column(db.String(20), nullable=False, default="0000")
    active = db.Column(db.Boolean, nullable=False, default=True)

class Attendance(db.Model):
    __tablename__ = "attendance"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    work_date = db.Column(db.String(10), nullable=False)
    clock_in = db.Column(db.String(32))
    clock_out = db.Column(db.String(32))
    employee = db.relationship("Employee")

def init_db():
    db.create_all()
    if Employee.query.count() == 0:
        for i in range(1, 14):
            db.session.add(Employee(name=f"직원{i}", pin="0000"))
        db.session.commit()

def calc_minutes(clock_in, clock_out):
    if not clock_in or not clock_out:
        return 0
    a = datetime.fromisoformat(clock_in)
    b = datetime.fromisoformat(clock_out)
    return max(0, int((b - a).total_seconds() // 60))

@app.before_request
def ensure_db():
    init_db()

@app.route("/", methods=["GET", "POST"])
def employee_login():
    employees = Employee.query.filter_by(active=True).order_by(Employee.id).all()
    if request.method == "POST":
        emp_id = request.form.get("employee_id")
        pin = request.form.get("pin", "")
        emp = Employee.query.filter_by(id=emp_id, active=True).first()
        if emp and emp.pin == pin:
            session["employee_id"] = emp.id
            session["employee_name"] = emp.name
            return redirect(url_for("employee_home"))
        flash("이름 또는 PIN을 확인해 주세요.")
    return render_template("employee_login.html", employees=employees)

@app.route("/employee")
def employee_home():
    emp_id = session.get("employee_id")
    if not emp_id:
        return redirect(url_for("employee_login"))

    today = date.today().isoformat()
    row = (Attendance.query
           .filter_by(employee_id=emp_id, work_date=today)
           .order_by(Attendance.id.desc()).first())
    recent = (Attendance.query
              .filter_by(employee_id=emp_id)
              .order_by(Attendance.work_date.desc(), Attendance.id.desc())
              .limit(10).all())
    return render_template("employee_home.html", row=row, recent=recent, today=today)

@app.post("/clock-in")
def clock_in():
    emp_id = session.get("employee_id")
    if not emp_id:
        return redirect(url_for("employee_login"))

    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    existing = (Attendance.query
                .filter_by(employee_id=emp_id, work_date=today)
                .order_by(Attendance.id.desc()).first())

    if existing and existing.clock_in and not existing.clock_out:
        flash("이미 출근 처리되어 있습니다.")
    else:
        db.session.add(Attendance(employee_id=emp_id, work_date=today, clock_in=now))
        db.session.commit()
        flash("출근 처리되었습니다.")
    return redirect(url_for("employee_home"))

@app.post("/clock-out")
def clock_out():
    emp_id = session.get("employee_id")
    if not emp_id:
        return redirect(url_for("employee_login"))

    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    row = (Attendance.query
           .filter_by(employee_id=emp_id, work_date=today, clock_out=None)
           .filter(Attendance.clock_in.isnot(None))
           .order_by(Attendance.id.desc()).first())

    if not row:
        flash("퇴근 처리할 출근 기록이 없습니다.")
    else:
        row.clock_out = now
        db.session.commit()
        flash("퇴근 처리되었습니다.")
    return redirect(url_for("employee_home"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("employee_login"))

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("pin", "") == ADMIN_PIN:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("관리자 PIN이 올바르지 않습니다.")
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    month = request.args.get("month") or date.today().strftime("%Y-%m")
    employees = Employee.query.filter_by(active=True).order_by(Employee.id).all()
    rows = (Attendance.query.join(Employee)
            .filter(Attendance.work_date.like(f"{month}%"))
            .order_by(Attendance.work_date.desc(), Employee.id.asc())
            .all())

    totals = {e.id: {"name": e.name, "days": 0, "minutes": 0} for e in employees}
    seen_days = {e.id: set() for e in employees}

    for r in rows:
        totals[r.employee_id]["minutes"] += calc_minutes(r.clock_in, r.clock_out)
        if r.clock_in:
            seen_days[r.employee_id].add(r.work_date)

    for emp_id in totals:
        totals[emp_id]["days"] = len(seen_days[emp_id])

    return render_template(
        "admin_dashboard.html",
        month=month,
        rows=rows,
        totals=totals.values()
    )

@app.route("/admin/employees", methods=["GET", "POST"])
def admin_employees():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update":
            emp = Employee.query.get(request.form.get("employee_id"))
            if emp:
                name = request.form.get("name", "").strip()
                pin = request.form.get("pin", "").strip()
                if name and pin:
                    emp.name = name
                    emp.pin = pin
                    db.session.commit()
                    flash("직원 정보가 수정되었습니다.")

        elif action == "add":
            name = request.form.get("name", "").strip()
            pin = request.form.get("pin", "").strip() or "0000"
            if name:
                if Employee.query.filter_by(name=name).first():
                    flash("이미 같은 이름의 직원이 있습니다.")
                else:
                    db.session.add(Employee(name=name, pin=pin))
                    db.session.commit()
                    flash("직원이 추가되었습니다.")

        elif action == "deactivate":
            emp = Employee.query.get(request.form.get("employee_id"))
            if emp:
                emp.active = False
                db.session.commit()
                flash("직원이 비활성화되었습니다.")

    employees = Employee.query.filter_by(active=True).order_by(Employee.id).all()
    return render_template("admin_employees.html", employees=employees)

@app.route("/admin/export.csv")
def export_csv():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    month = request.args.get("month") or date.today().strftime("%Y-%m")
    rows = (Attendance.query.join(Employee)
            .filter(Attendance.work_date.like(f"{month}%"))
            .order_by(Attendance.work_date.asc(), Employee.id.asc())
            .all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["이름", "날짜", "출근", "퇴근", "근무시간"])

    for r in rows:
        mins = calc_minutes(r.clock_in, r.clock_out)
        hh, mm = divmod(mins, 60)
        writer.writerow([
            r.employee.name,
            r.work_date,
            r.clock_in[11:16] if r.clock_in else "",
            r.clock_out[11:16] if r.clock_out else "",
            f"{hh}:{mm:02d}" if r.clock_out else ""
        ])

    data = "\ufeff" + output.getvalue()
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="attendance_{month}.csv"'}
    )

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
