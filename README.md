# CloudBalance — Four-server scheduling version

## Included files
- `backend/app.py`: Flask routes and job submission/dashboard APIs
- `backend/database.py`: MySQL connection
- `backend/load_balancer.py`: random initial assignment to Servers 1–3
- `backend/server_manager.py`: server/queue configuration
- `backend/scheduler.py`: forward-only staged execution and history writes
- `backend/migration.py`: intentionally deferred legacy module (not called by app)
- `frontend/index.html`, `style.css`, `script.js`: complete dashboard and two history views

## Execution rules
- Server 1: Round Robin, max 2 units per visit
- Server 2: SJF, max 2 units per visit; shortest remaining time first
- Server 3: Priority, max 2 units per visit; larger priority number first
- Server 4: FCFS, finishes all remaining work
- An unfinished job advances only to the next server; completed jobs do not move again.
- Burst time is supplied at submission. No user-provided script is executed.

## Database
This version expects your existing `cloudbalance` database and the tables already shown in your Workbench. Required additions already made in your screenshots: `Jobs.burst_time`, `Jobs.remaining_time`, `Jobs.selected_server_id`; `Scheduling_History.remaining_time_before`, `remaining_time_after`; and `Server4_Queue`.

**No tables or records are dropped.** Old jobs whose burst/remaining time are NULL are displayed but skipped by the scheduler until you decide how to handle them. Existing migration history is preserved. The scheduler writes new forward transitions to `Migration_History` as part of execution, but the old auto-migration module is not invoked.

## Run
1. Unzip this folder and open it in VS Code.
2. Check `backend/database.py` connection values. The defaults match the previous project; preferably set `CLOUDBALANCE_DB_PASSWORD` as an environment variable if you change credentials.
3. From project root run `pip install -r requirements.txt`.
4. Run `python backend/app.py`.
5. Open `http://127.0.0.1:5000`.

## Important behavior
Clicking **Run Scheduler** processes all currently waiting queue stages in one simulation cycle. A job can traverse multiple servers in that cycle until it completes or the cycle's next stage is no longer eligible. The server-wise history is ordered per server; the job-wise path is ordered by history insertion ID.
