-- CloudBalance existing-database verification only. This file intentionally does not DROP,
-- DELETE, TRUNCATE, or recreate existing tables. Your existing DB has already been migrated.
USE cloudbalance;
SELECT server_id, server_name, scheduling_algorithm, status FROM Servers ORDER BY server_id;
SHOW COLUMNS FROM Jobs;
SHOW COLUMNS FROM Scheduling_History;
SHOW COLUMNS FROM Server4_Queue;
