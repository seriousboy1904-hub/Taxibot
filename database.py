import sqlite3

class Database:
    def __init__(self, db_name):
        self.conn = sqlite3.connect(db_name)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            user_id INTEGER,
            station TEXT,
            status TEXT
        )
        """)
        self.conn.commit()

    def get_first_driver_in_queue(self, station):
        cur = self.conn.execute(
            "SELECT * FROM drivers WHERE station=? AND status='free' LIMIT 1",
            (station,)
        )
        row = cur.fetchone()
        return dict(row) if row else None