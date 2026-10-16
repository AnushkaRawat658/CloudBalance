import os
from flask import Flask, request, jsonify, send_from_directory
from database import get_connection
from load_balancer import select_server
from server_manager import SERVER_CONFIG
from scheduler import run_scheduling_cycle

app = Flask(__name__)
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

@app.route("/")
def home(): return send_from_directory(FRONTEND_DIR, "index.html")
@app.route("/<path:filename>")
def frontend_files(filename):
    if filename in ("style.css", "script.js"):
        return send_from_directory(FRONTEND_DIR, filename)
    return jsonify({"error":"Not found"}), 404

@app.post("/submit-job")
def submit_job():
    data = request.get_json(silent=True) or {}
    name = data.get("job_name", "")
    if not isinstance(name, str) or not name.strip(): return jsonify({"error":"Job name is required."}), 400
    try:
        burst = int(data.get("burst_time"))
        priority = int(data.get("priority", 2))
        if burst < 1 or burst > 100000: raise ValueError
        if priority < 1 or priority > 10: raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error":"Burst time must be a positive integer and priority must be between 1 and 10."}), 400
    conn = get_connection()
    if not conn: return jsonify({"error":"Database connection failed. Check backend/database.py settings."}), 500
    cur = conn.cursor()
    sid = select_server(); cfg = SERVER_CONFIG[sid]
    try:
        cur.execute("INSERT INTO Jobs(job_name,priority,status,burst_time,remaining_time,selected_server_id) VALUES(%s,%s,'Pending',%s,%s,%s)", (name.strip(),priority,burst,burst,sid))
        job_id = cur.lastrowid
        table = cfg["table"]
        cur.execute(f"SELECT COALESCE(MAX(queue_position),0)+1 FROM {table}")
        position = cur.fetchone()[0]
        cur.execute(f"INSERT INTO {table}(job_id,queue_position,remaining_time,queue_status) VALUES(%s,%s,%s,'Waiting')", (job_id,position,burst))
        cur.execute("INSERT INTO Job_Execution_Log(job_id,server_id,event_type,details) VALUES(%s,%s,'Submitted',%s)", (job_id,sid,f"Random initial assignment to {cfg['name']}"))
        conn.commit()
        return jsonify({"job_id":job_id,"server":cfg["name"],"algorithm":cfg["algorithm"],"burst_time":burst,"remaining_time":burst}), 201
    except Exception as exc:
        conn.rollback(); app.logger.exception("Job submission failed")
        return jsonify({"error":str(exc)}), 500
    finally:
        cur.close(); conn.close()

@app.get("/api/jobs")
def get_jobs():
    conn=get_connection()
    if not conn: return jsonify({"error":"Database connection failed."}),500
    cur=conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT j.job_id,j.job_name,j.priority,j.status,j.submitted_at,j.burst_time,j.remaining_time,
            j.selected_server_id,s.server_name AS selected_server,s.scheduling_algorithm
            FROM Jobs j LEFT JOIN Servers s ON s.server_id=j.selected_server_id ORDER BY j.job_id DESC""")
        rows=cur.fetchall()
        for r in rows:
            if r.get("submitted_at"): r["submitted_at"]=r["submitted_at"].strftime("%Y-%m-%d %H:%M:%S")
        return jsonify(rows)
    except Exception as exc:
        app.logger.exception("Jobs query failed"); return jsonify({"error":str(exc)}),500
    finally: cur.close(); conn.close()

@app.get("/api/servers")
def get_servers():
    conn=get_connection()
    if not conn: return jsonify({"error":"Database connection failed."}),500
    cur=conn.cursor(dictionary=True)
    try:
        result=[]
        for sid,cfg in SERVER_CONFIG.items():
            cur.execute("SELECT server_id,server_name,scheduling_algorithm,status FROM Servers WHERE server_id=%s",(sid,))
            row=cur.fetchone()
            if not row: continue
            table=cfg['table']
            cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE queue_status='Waiting'"); row['pending_jobs']=cur.fetchone()['n']
            cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE queue_status='Running'"); row['running_jobs']=cur.fetchone()['n']
            row['current_load']=row['pending_jobs']+row['running_jobs']; result.append(row)
        return jsonify(result)
    except Exception as exc: app.logger.exception("Servers query failed"); return jsonify({"error":str(exc)}),500
    finally: cur.close(); conn.close()

@app.post("/api/run-scheduler")
def run_scheduler():
    try:
        results=run_scheduling_cycle()
        return jsonify({"message":"Scheduling cycle finished.","results":results})
    except Exception as exc:
        app.logger.exception("Scheduler failed"); return jsonify({"error":str(exc)}),500

@app.get("/api/scheduling-history")
def scheduling_history():
    conn=get_connection()
    if not conn: return jsonify({"error":"Database connection failed."}),500
    cur=conn.cursor(dictionary=True)
    try:
        sid=request.args.get('server_id',type=int)
        query="""SELECT h.history_id,h.job_id,j.job_name,h.server_id,s.server_name,s.scheduling_algorithm,
          h.execution_order,h.start_time,h.end_time,h.cpu_time_used,h.remaining_time_before,h.remaining_time_after
          FROM Scheduling_History h JOIN Jobs j ON j.job_id=h.job_id JOIN Servers s ON s.server_id=h.server_id"""
        params=()
        if sid in SERVER_CONFIG: query += " WHERE h.server_id=%s"; params=(sid,)
        query += " ORDER BY h.server_id,h.execution_order,h.history_id"
        cur.execute(query,params); rows=cur.fetchall()
        for r in rows:
            for k in ('start_time','end_time'):
                if r.get(k): r[k]=r[k].strftime('%Y-%m-%d %H:%M:%S')
        return jsonify(rows)
    except Exception as exc: app.logger.exception("History query failed"); return jsonify({"error":str(exc)}),500
    finally: cur.close(); conn.close()

@app.get("/api/job-path/<int:job_id>")
def job_path(job_id):
    conn=get_connection()
    if not conn: return jsonify({"error":"Database connection failed."}),500
    cur=conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT h.history_id,h.job_id,j.job_name,h.server_id,s.server_name,s.scheduling_algorithm,
          h.execution_order,h.cpu_time_used,h.remaining_time_before,h.remaining_time_after,h.start_time,h.end_time
          FROM Scheduling_History h JOIN Jobs j ON j.job_id=h.job_id JOIN Servers s ON s.server_id=h.server_id
          WHERE h.job_id=%s ORDER BY h.history_id""",(job_id,))
        rows=cur.fetchall()
        for r in rows:
            for k in ('start_time','end_time'):
                if r.get(k): r[k]=r[k].strftime('%Y-%m-%d %H:%M:%S')
        return jsonify(rows)
    except Exception as exc: app.logger.exception("Job path query failed"); return jsonify({"error":str(exc)}),500
    finally: cur.close(); conn.close()

if __name__ == '__main__':
    app.run(debug=True)
