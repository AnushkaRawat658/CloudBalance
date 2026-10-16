from database import get_connection

SERVER_CONFIG = {
    1: {"name": "Server 1", "algorithm": "Round Robin", "table": "Server1_Queue", "slice": 2},
    2: {"name": "Server 2", "algorithm": "SJF", "table": "Server2_Queue", "slice": 2},
    3: {"name": "Server 3", "algorithm": "Priority Scheduling", "table": "Server3_Queue", "slice": 2},
    4: {"name": "Server 4", "algorithm": "FCFS", "table": "Server4_Queue", "slice": None},
}

def load_queues_from_database():
    """Return current waiting/running queue counts without in-memory state."""
    conn = get_connection()
    if not conn:
        return {}
    result = {}
    try:
        cur = conn.cursor(dictionary=True)
        for sid, config in SERVER_CONFIG.items():
            cur.execute("SELECT COUNT(*) AS n FROM " + config["table"] + " WHERE queue_status='Waiting'")
            waiting = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM " + config["table"] + " WHERE queue_status='Running'")
            running = cur.fetchone()["n"]
            result[sid] = {"waiting": waiting, "running": running}
        return result
    finally:
        cur.close()
        conn.close()
