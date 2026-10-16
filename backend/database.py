import os
import mysql.connector
from mysql.connector import Error

# Defaults match the connection settings in your previous project.
# Override with CLOUDBALANCE_DB_HOST, CLOUDBALANCE_DB_USER,
# CLOUDBALANCE_DB_PASSWORD, and CLOUDBALANCE_DB_NAME if needed.
def get_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv("CLOUDBALANCE_DB_HOST", "localhost"),
            user=os.getenv("CLOUDBALANCE_DB_USER", "root"),
            password=os.getenv("CLOUDBALANCE_DB_PASSWORD", "anushkarawat2005#"),
            database=os.getenv("CLOUDBALANCE_DB_NAME", "cloudbalance"),
            autocommit=False,
        )
    except Error as exc:
        print(f"Database connection failed: {exc}")
        return None
