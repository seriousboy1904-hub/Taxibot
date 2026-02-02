import sqlite3

class Database:
    def __init__(self, db_file):
        self.connection = sqlite3.connect(db_file)
        self.cursor = self.connection.cursor()
        self.create_tables()

    def create_tables(self):
        # is_active - live location yoniqligi, status - band/bo'shligi
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            role TEXT, 
            status TEXT DEFAULT 'idle', 
            current_station TEXT,
            last_lat REAL,
            last_lon REAL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        self.connection.commit()

    def update_driver_status(self, user_id, lat, lon, station, status="idle"):
        with self.connection:
            # Haydovchi ma'lumotlarini yangilaymiz. 
            # INSERT OR REPLACE foydalanuvchi birinchi marta kirganda uni qo'shadi ham.
            return self.cursor.execute(
                """INSERT OR REPLACE INTO users 
                (user_id, last_lat, last_lon, current_station, status, role, joined_at) 
                VALUES (?, ?, ?, ?, ?, 'driver', CURRENT_TIMESTAMP)""",
                (user_id, lat, lon, station, status)
            )

    def get_first_driver_in_queue(self, station_name):
        self.cursor.execute(
            """SELECT user_id FROM users 
            WHERE current_station = ? AND status = 'idle' 
            ORDER BY joined_at ASC LIMIT 1""",
            (station_name,)
        )
        res = self.cursor.fetchone()
        return {"user_id": res[0]} if res else None
