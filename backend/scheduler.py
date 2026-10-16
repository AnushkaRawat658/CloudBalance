from datetime import datetime
from database import get_connection
from server_manager import SERVER_CONFIG


# This function determines the next execution-order number for a particular server.
def _next_order(cursor, server_id):
    """Get the next execution order for a server."""
    cursor.execute(
        """
        SELECT COALESCE(MAX(execution_order), 0) + 1 AS next_order
        FROM Scheduling_History
        WHERE server_id = %s
        """,
        (server_id,)
    )
    return cursor.fetchone()["next_order"]


def _next_queue_position(cursor, table):
    """Get the next queue position for a server."""
    cursor.execute(
        f"""
        SELECT COALESCE(MAX(queue_position), 0) + 1 AS next_position
        FROM {table}
        """
    )
    return cursor.fetchone()["next_position"]

#This function determines the highest-numbered(last konse server pe chali thi) server on which a job has already executed.
def _get_server_history(cursor, job_id):
    """Get the highest-numbered server previously visited by a job."""
    cursor.execute(
        """
        SELECT MAX(server_id) AS last_server
        FROM Scheduling_History
        WHERE job_id = %s
        """,
        (job_id,)
    )
    return cursor.fetchone()["last_server"]


def _log_event(cursor, job_id, server_id, event_type, details):
    """Record an execution event."""
    cursor.execute(
        """
        INSERT INTO Job_Execution_Log
            (job_id, server_id, event_type, details)
        VALUES (%s, %s, %s, %s)
        """,
        (job_id, server_id, event_type, details)
    )


def run_scheduling_cycle():
    """
    Execute jobs through the four servers in forward order.

    Server 1: Round Robin, 2 units per job.
    Server 2: SJF, 2 units per job.
    Server 3: Priority Scheduling, 2 units per job.
              Higher numeric priority means higher priority.
    Server 4: FCFS, executes all remaining units.

    Incomplete jobs move only to the next server.
    Completed jobs never move again.
    """

    conn = get_connection()

    if conn is None:
        raise RuntimeError(
            "Could not connect to the cloudbalance database."
        )

#create a cursor that executes SQL statements
    cur = conn.cursor(dictionary=True)
    outcomes = []

    try:
        server_ids = sorted(SERVER_CONFIG.keys())

        # Process servers in ascending order so jobs forwarded from
        # an earlier server can run on a later server in this cycle.
        for sid in server_ids:
            cfg = SERVER_CONFIG[sid]
            table = cfg["table"]

            # Choose the scheduling order for the current server.
            if sid == 2:
                ordering = (
                    "COALESCE(j.remaining_time, j.burst_time) ASC, "
                    "q.queue_position ASC, q.added_at ASC, j.job_id ASC"
                )
            elif sid == 3:
                ordering = (
                    "j.priority DESC, "
                    "q.queue_position ASC, q.added_at ASC, j.job_id ASC"
                )
            else:
                ordering = (
                    "q.queue_position ASC, "
                    "q.added_at ASC, j.job_id ASC"
                )

            # Retrieve valid waiting jobs in scheduling order.
            cur.execute(
                f"""
                SELECT
                    j.job_id,
                    j.job_name,
                    j.priority,
                    j.burst_time,
                    j.remaining_time,
                    j.status,
                    q.queue_id,
                    q.queue_position
                FROM Jobs j
                JOIN {table} q ON q.job_id = j.job_id
                WHERE q.queue_status = 'Waiting'
                  AND j.status IN ('Pending', 'Running')
                  AND COALESCE(j.remaining_time, j.burst_time) > 0
                ORDER BY {ordering}
                FOR UPDATE
                """
            )

            fetched_jobs = cur.fetchall()

            # Process each job only once per server, even if duplicate
            # waiting entries exist in that server's queue.
            jobs = []
            seen_job_ids = set()

            for job in fetched_jobs:
                jid = job["job_id"]

                if jid not in seen_job_ids:
                    seen_job_ids.add(jid)
                    jobs.append(job)

            for job in jobs:
                jid = job["job_id"]

                remaining_value = job["remaining_time"]

                if remaining_value is None:
                    remaining_value = job["burst_time"]

                # Do not modify legacy jobs without a burst time.
                if remaining_value is None or int(remaining_value) <= 0:
                    continue

                # Prevent a stale queue entry from making a job revisit
                # a server it has already visited.
                last_server = _get_server_history(cur, jid)

                if last_server is not None and sid <= last_server:
                    cur.execute(
                        f"""
                        UPDATE {table}
                        SET queue_status = 'Completed',
                            remaining_time = %s
                        WHERE job_id = %s
                          AND queue_status = 'Waiting'
                        """,
                        (int(remaining_value), jid)
                    )
                    continue

                before = int(remaining_value)

                # Server 4 finishes the job. Servers 1-3 execute
                # at most two units before forwarding an incomplete job.
                if sid == 4:
                    used = before
                else:
                    used = min(2, before)

                after = before - used

                started = datetime.now()
                finished = datetime.now()
                execution_order = _next_order(cur, sid)

                # Mark every duplicate waiting entry for this job as
                # processed so it cannot execute again accidentally.
                cur.execute(
                    f"""
                    UPDATE {table}
                    SET queue_status = 'Completed',
                        remaining_time = %s
                    WHERE job_id = %s
                      AND queue_status = 'Waiting'
                    """,
                    (after, jid)
                )

                # Save this execution step in scheduling history.
                cur.execute(
                    """
                    INSERT INTO Scheduling_History (
                        job_id,
                        server_id,
                        execution_order,
                        start_time,
                        end_time,
                        cpu_time_used,
                        remaining_time_before,
                        remaining_time_after
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        jid,
                        sid,
                        execution_order,
                        started,
                        finished,
                        used,
                        before,
                        after
                    )
                )

                _log_event(
                    cur,
                    jid,
                    sid,
                    "Executed",
                    (
                        f"{cfg['algorithm']}: executed {used} units; "
                        f"remaining {after}"
                    )
                )

                # Case 1: The job has finished.
                if after == 0:
                    cur.execute(
                        """
                        UPDATE Jobs
                        SET remaining_time = 0,
                            status = 'Completed'
                        WHERE job_id = %s
                        """,
                        (jid,)
                    )

                    _log_event(
                        cur,
                        jid,
                        sid,
                        "Completed",
                        "Job finished"
                    )

                    outcome_status = "Completed"

                # Case 2: The job is incomplete and can move forward.
                elif sid < 4:
                    next_sid = sid + 1
                    next_cfg = SERVER_CONFIG[next_sid]
                    next_table = next_cfg["table"]

                    cur.execute(
                        """
                        UPDATE Jobs
                        SET remaining_time = %s,
                            status = 'Pending'
                        WHERE job_id = %s
                        """,
                        (after, jid)
                    )

                    # Reuse an existing waiting entry if available.
                    cur.execute(
                        f"""
                        SELECT queue_id
                        FROM {next_table}
                        WHERE job_id = %s
                          AND queue_status = 'Waiting'
                        ORDER BY queue_position ASC
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (jid,)
                    )

                    existing_queue = cur.fetchone()

                    if existing_queue:
                        cur.execute(
                            f"""
                            UPDATE {next_table}
                            SET remaining_time = %s
                            WHERE queue_id = %s
                            """,
                            (after, existing_queue["queue_id"])
                        )
                    else:
                        position = _next_queue_position(
                            cur, next_table
                        )

                        cur.execute(
                            f"""
                            INSERT INTO {next_table} (
                                job_id,
                                queue_position,
                                remaining_time,
                                queue_status
                            )
                            VALUES (%s, %s, %s, 'Waiting')
                            """,
                            (jid, position, after)
                        )

                    # Record the forward-only transition.
                    cur.execute(
                        """
                        INSERT INTO Migration_History (
                            job_id,
                            from_server_id,
                            to_server_id,
                            reason
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            jid,
                            sid,
                            next_sid,
                            f"Remaining burst time: {after}"
                        )
                    )

                    _log_event(
                        cur,
                        jid,
                        sid,
                        "Forwarded",
                        (
                            f"Forwarded to Server {next_sid}; "
                            f"remaining {after}"
                        )
                    )

                    outcome_status = f"Forwarded to Server {next_sid}"

                # An incomplete job on Server 4 indicates an error.
                else:
                    raise RuntimeError(
                        f"Job {jid} unexpectedly remained incomplete "
                        "on Server 4."
                    )

                outcomes.append({
                    "job_id": jid,
                    "job_name": job["job_name"],
                    "server": cfg["name"],
                    "algorithm": cfg["algorithm"],
                    "executed": used,
                    "remaining": after,
                    "status": outcome_status
                })

        # Keep remaining-time values in waiting queues synchronized
        # with the Jobs table.
        for sid in server_ids:
            table = SERVER_CONFIG[sid]["table"]

            cur.execute(
                f"""
                UPDATE {table} q
                JOIN Jobs j ON j.job_id = q.job_id
                SET q.remaining_time =
                    COALESCE(j.remaining_time, j.burst_time, 0)
                WHERE q.queue_status = 'Waiting'
                """
            )

        conn.commit()
        return outcomes

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()
