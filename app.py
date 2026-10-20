"""
Campus Notice Board v2 - Cloud Computing Mini Project (AWS EC2)
New in v2: categories, priority + pin, search/filter, edit, admin login,
dashboard stats, dark mode, CSV export, optional S3 backup.

Run:  python3 app.py   ->  http://<EC2-PUBLIC-IP>:5000
Env vars (all optional):
  ADMIN_PASSWORD  (default: admin123)   SECRET_KEY   (default: change-me)
  S3_BUCKET       (enables S3 backup)   DB_PATH, PORT
"""
import os, io, csv, json, sqlite3, urllib.request
from datetime import datetime
from functools import wraps
from flask import (Flask, request, redirect, render_template_string, jsonify,
                   Response, session, flash, url_for)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "data", "notices.db"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
CATEGORIES = ["General", "Exam", "Event", "Placement", "Holiday"]
COLORS = {"General": "#6c757d", "Exam": "#e63946", "Event": "#2a9d8f",
          "Placement": "#6a4c93", "Holiday": "#f4a261"}
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS notices(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, body TEXT NOT NULL, author TEXT NOT NULL,
            created_at TEXT NOT NULL)""")
        # upgrade older (v1) databases without losing data
        cols = [r["name"] for r in c.execute("PRAGMA table_info(notices)")]
        for name, ddl in [("category", "TEXT DEFAULT 'General'"),
                          ("priority", "TEXT DEFAULT 'Normal'"),
                          ("pinned", "INTEGER DEFAULT 0"),
                          ("updated_at", "TEXT")]:
            if name not in cols:
                c.execute(f"ALTER TABLE notices ADD COLUMN {name} {ddl}")


def instance_info():
    """Read EC2 metadata (IMDSv2); falls back gracefully on a laptop."""
    try:
        t = urllib.request.Request(
            "http://169.254.169.254/latest/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        token = urllib.request.urlopen(t, timeout=1).read().decode()
        def get(p):
            r = urllib.request.Request("http://169.254.169.254/latest/meta-data/" + p,
                                       headers={"X-aws-ec2-metadata-token": token})
            return urllib.request.urlopen(r, timeout=1).read().decode()
        return {"instance_id": get("instance-id"), "instance_type": get("instance-type"),
                "az": get("placement/availability-zone"), "public_ip": get("public-ipv4")}
    except Exception:
        return {"instance_id": "Local mode (not on EC2)", "instance_type": "-",
                "az": "-", "public_ip": "-"}


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            flash("Please log in as admin first.", "error")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


PAGE = """
<!doctype html><html data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Notice Board</title>
<style>
 :root{--bg:#f4f6fb;--card:#fff;--text:#222;--muted:#777;--line:#dde}
 [data-theme=dark]{--bg:#12151c;--card:#1e222d;--text:#e8e8e8;--muted:#9aa;--line:#333a48}
 body{font-family:system-ui,Arial;max-width:900px;margin:24px auto;padding:0 16px;background:var(--bg);color:var(--text)}
 .top{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
 h1{margin:0} .sub{color:var(--muted);margin:2px 0 12px}
 .card{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;box-shadow:0 1px 4px #0002}
 input,textarea,select{width:100%;padding:9px;margin:4px 0 10px;border:1px solid var(--line);border-radius:6px;box-sizing:border-box;font:inherit;background:var(--card);color:var(--text)}
 button,.btn{background:#ff9900;border:0;padding:8px 16px;border-radius:6px;font-weight:600;cursor:pointer;color:#111;text-decoration:none;font-size:14px;display:inline-block}
 .sec{background:#445}.sec{color:#fff} .del{background:#e55;color:#fff;padding:4px 10px;font-size:12px}
 .small{padding:4px 10px;font-size:12px}
 .meta{font-size:12px;color:var(--muted)} .ec2{background:#232f3e;color:#fff;font-size:13px}.ec2 b{color:#ff9900}
 .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
 .stat{text-align:center;padding:12px}.stat h2{margin:0;font-size:28px}.stat span{color:var(--muted);font-size:13px}
 .row{display:flex;gap:8px;flex-wrap:wrap}.row>*{flex:1;min-width:120px}
 .badge{color:#fff;border-radius:12px;padding:2px 10px;font-size:12px;margin-right:6px}
 .imp{border-left:5px solid #e63946}.pin{background:#fff8e1}[data-theme=dark] .pin{background:#2c2a1a}
 .bar{height:10px;border-radius:5px;margin:3px 0 8px}
 .flash{padding:10px;border-radius:6px;margin:8px 0}.ok{background:#d4edda;color:#155724}.error{background:#f8d7da;color:#721c24}
 @media(max-width:600px){.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<div class="top"><div><h1>📢 Campus Notice Board</h1>
<p class="sub">Cloud Computing Mini Project - hosted on AWS EC2</p></div>
<div>
 <button class="sec" onclick="toggleTheme()">🌓 Theme</button>
 {% if admin %}<a class="btn sec" href="/logout">Logout (admin)</a>
 {% else %}<a class="btn" href="/login">Admin Login</a>{% endif %}
</div></div>

{% for cat,msg in get_flashed_messages(with_categories=true) %}
 <div class="flash {{ 'ok' if cat=='ok' else 'error' }}">{{ msg }}</div>{% endfor %}

<div class="card ec2"><b>Server info (EC2 metadata)</b><br>
 Instance: {{ info.instance_id }} | Type: {{ info.instance_type }} | AZ: {{ info.az }} | IP: {{ info.public_ip }}<br>
 Database: {{ dbpath }}</div>

<div class="grid">
 <div class="card stat"><h2>{{ s.total }}</h2><span>Total notices</span></div>
 <div class="card stat"><h2>{{ s.important }}</h2><span>Important</span></div>
 <div class="card stat"><h2>{{ s.pinned }}</h2><span>Pinned</span></div>
 <div class="card stat"><h2>{{ s.today }}</h2><span>Posted today</span></div>
</div>

<div class="card"><b>Notices by category</b>
 {% for c in cats %}<div class="meta">{{ c }} ({{ s.by_cat.get(c,0) }})</div>
 <div class="bar" style="width:{{ (s.by_cat.get(c,0)/ (s.total or 1))*100 }}%;background:{{ colors[c] }};min-width:3px"></div>{% endfor %}
</div>

{% if admin %}
<div class="card"><b>{{ 'Edit notice' if edit else 'Post a new notice' }}</b>
 <form method="post" action="{{ '/edit/%d'%edit.id if edit else '/add' }}">
  <input name="title" placeholder="Title" required maxlength="100" value="{{ edit.title if edit else '' }}">
  <textarea name="body" rows="3" placeholder="Notice" required>{{ edit.body if edit else '' }}</textarea>
  <div class="row">
   <input name="author" placeholder="Posted by" required maxlength="50" value="{{ edit.author if edit else '' }}">
   <select name="category">{% for c in cats %}<option {{ 'selected' if edit and edit.category==c }}>{{ c }}</option>{% endfor %}</select>
   <select name="priority"><option>Normal</option><option {{ 'selected' if edit and edit.priority=='Important' }}>Important</option></select>
  </div>
  <button type="submit">{{ 'Save changes' if edit else 'Post Notice' }}</button>
  {% if edit %}<a class="btn sec" href="/">Cancel</a>{% endif %}
 </form></div>
{% endif %}

<div class="card"><form method="get" class="row">
 <input name="q" placeholder="🔍 Search notices..." value="{{ q }}">
 <select name="cat"><option value="">All categories</option>
  {% for c in cats %}<option {{ 'selected' if cat==c }}>{{ c }}</option>{% endfor %}</select>
 <button type="submit">Filter</button>
</form>
<div class="meta" style="margin-top:8px">Export:
 <a href="/api/notices">JSON API</a> | <a href="/export">JSON file</a> | <a href="/export.csv">CSV</a>
 {% if admin and s3 %}| <form method="post" action="/backup-s3" style="display:inline"><button class="small">☁ Backup to S3</button></form>{% endif %}
</div></div>

{% for n in notices %}
<div class="card {{ 'imp' if n.priority=='Important' }} {{ 'pin' if n.pinned }}">
 <span class="badge" style="background:{{ colors.get(n.category,'#666') }}">{{ n.category }}</span>
 {% if n.priority=='Important' %}<span class="badge" style="background:#e63946">❗ Important</span>{% endif %}
 {% if n.pinned %}📌{% endif %}
 <b>{{ n.title }}</b>
 {% if admin %}<span style="float:right">
  <form method="post" action="/pin/{{ n.id }}" style="display:inline"><button class="small">{{ 'Unpin' if n.pinned else 'Pin' }}</button></form>
  <a class="btn small sec" href="/?edit={{ n.id }}">Edit</a>
  <form method="post" action="/delete/{{ n.id }}" style="display:inline" onsubmit="return confirm('Delete this notice?')"><button class="del">Delete</button></form></span>{% endif %}
 <p>{{ n.body }}</p>
 <div class="meta">By {{ n.author }} • {{ n.created_at }}{% if n.updated_at %} • edited {{ n.updated_at }}{% endif %}</div>
</div>
{% else %}<div class="card">No notices found.</div>{% endfor %}

<script>
 const t=localStorage.getItem('theme'); if(t) document.documentElement.dataset.theme=t;
 function toggleTheme(){const d=document.documentElement;
  d.dataset.theme=d.dataset.theme==='dark'?'light':'dark';localStorage.setItem('theme',d.dataset.theme)}
</script></body></html>
"""

LOGIN = """
<!doctype html><html><head><meta charset="utf-8"><title>Admin Login</title>
<style>body{font-family:system-ui;background:#f4f6fb;display:flex;justify-content:center;padding-top:80px}
.c{background:#fff;padding:28px;border-radius:10px;box-shadow:0 1px 6px #0003;width:300px}
input{width:100%;padding:9px;margin:8px 0;box-sizing:border-box}button{background:#ff9900;border:0;padding:9px 18px;border-radius:6px;font-weight:600;width:100%}
.e{color:#c00;font-size:13px}</style></head><body><div class="c"><h3>🔐 Admin Login</h3>
{% for c,m in get_flashed_messages(with_categories=true) %}<p class="e">{{ m }}</p>{% endfor %}
<form method="post"><input type="password" name="password" placeholder="Admin password" autofocus required>
<button>Login</button></form><p><a href="/">← Back to board</a></p></div></body></html>
"""


def stats():
    with db() as c:
        total = c.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        imp = c.execute("SELECT COUNT(*) FROM notices WHERE priority='Important'").fetchone()[0]
        pin = c.execute("SELECT COUNT(*) FROM notices WHERE pinned=1").fetchone()[0]
        today = c.execute("SELECT COUNT(*) FROM notices WHERE created_at LIKE ?",
                          (datetime.now().strftime("%Y-%m-%d") + "%",)).fetchone()[0]
        by_cat = {r["category"]: r["n"] for r in
                  c.execute("SELECT category, COUNT(*) n FROM notices GROUP BY category")}
    return {"total": total, "important": imp, "pinned": pin, "today": today, "by_cat": by_cat}


@app.route("/")
def index():
    q, cat = request.args.get("q", "").strip(), request.args.get("cat", "")
    sql, args = "SELECT * FROM notices WHERE 1=1", []
    if q:
        sql += " AND (title LIKE ? OR body LIKE ? OR author LIKE ?)"
        args += [f"%{q}%"] * 3
    if cat:
        sql += " AND category=?"; args.append(cat)
    sql += " ORDER BY pinned DESC, id DESC"
    with db() as c:
        rows = c.execute(sql, args).fetchall()
        eid = request.args.get("edit", type=int)
        edit = c.execute("SELECT * FROM notices WHERE id=?", (eid,)).fetchone() \
            if (eid and session.get("admin")) else None
    return render_template_string(PAGE, notices=rows, info=instance_info(), dbpath=DB_PATH,
                                  admin=session.get("admin"), s=stats(), cats=CATEGORIES,
                                  colors=COLORS, q=q, cat=cat, edit=edit, s3=bool(S3_BUCKET))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            flash("Logged in as admin.", "ok")
            return redirect("/")
        flash("Wrong password.", "error")
    return render_template_string(LOGIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


def form_data():
    cat = request.form.get("category", "General")
    pri = request.form.get("priority", "Normal")
    return (request.form["title"].strip(), request.form["body"].strip(),
            request.form["author"].strip(),
            cat if cat in CATEGORIES else "General",
            pri if pri in ("Normal", "Important") else "Normal")


@app.route("/add", methods=["POST"])
@admin_required
def add():
    t, b, a, c, p = form_data()
    with db() as conn:
        conn.execute("INSERT INTO notices(title,body,author,category,priority,created_at) "
                     "VALUES(?,?,?,?,?,?)", (t, b, a, c, p, now()))
    flash("Notice posted.", "ok")
    return redirect("/")


@app.route("/edit/<int:nid>", methods=["POST"])
@admin_required
def edit(nid):
    t, b, a, c, p = form_data()
    with db() as conn:
        conn.execute("UPDATE notices SET title=?,body=?,author=?,category=?,priority=?,updated_at=? "
                     "WHERE id=?", (t, b, a, c, p, now(), nid))
    flash("Notice updated.", "ok")
    return redirect("/")


@app.route("/pin/<int:nid>", methods=["POST"])
@admin_required
def pin(nid):
    with db() as conn:
        conn.execute("UPDATE notices SET pinned = 1 - COALESCE(pinned,0) WHERE id=?", (nid,))
    return redirect("/")


@app.route("/delete/<int:nid>", methods=["POST"])
@admin_required
def delete(nid):
    with db() as conn:
        conn.execute("DELETE FROM notices WHERE id=?", (nid,))
    flash("Notice deleted.", "ok")
    return redirect("/")


def all_notices():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM notices ORDER BY id DESC")]


@app.route("/api/notices")
def api_list():
    return jsonify(all_notices())


@app.route("/export")
def export_json():
    return Response(json.dumps(all_notices(), indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=notices_backup.json"})


@app.route("/export.csv")
def export_csv():
    rows, buf = all_notices(), io.StringIO()
    w = csv.DictWriter(buf, fieldnames=rows[0].keys() if rows else ["id"])
    w.writeheader(); w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=notices.csv"})


@app.route("/backup-s3", methods=["POST"])
@admin_required
def backup_s3():
    """Upload a JSON backup to S3 (needs S3_BUCKET env var + IAM role on the EC2)."""
    try:
        import boto3
        key = f"backups/notices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        boto3.client("s3").put_object(Bucket=S3_BUCKET, Key=key,
                                      Body=json.dumps(all_notices(), indent=2).encode())
        flash(f"Backup saved to s3://{S3_BUCKET}/{key}", "ok")
    except Exception as e:
        flash(f"S3 backup failed: {e}", "error")
    return redirect("/")


@app.route("/health")
def health():
    return {"status": "ok", "version": 2}


init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
