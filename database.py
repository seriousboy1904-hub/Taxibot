import sqlite3

class Database:
    def __init__(self, db_file):
        self.connection = sqlite3.connect(db_file)
        self.cursor = self.connection.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            phone TEXT,
            car_model TEXT,
            car_number TEXT,
            role TEXT, 
            status TEXT DEFAULT 'offline', 
            current_station TEXT,
            joined_at TIMESTAMP
        )""")
        self.connection.commit()

    def register_driver(self, user_id, name, phone, car, number):
        with self.connection:
            return self.cursor.execute(
                "INSERT OR REPLACE INTO users (user_id, full_name, phone, car_model, car_number, role) VALUES (?, ?, ?, ?, ?, 'driver')",
                (user_id, name, phone, car, number)
            )

    def get_queue_info(self, station_name):
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE current_station = ? AND status = 'idle'", (station_name,))
        count = self.cursor.fetchone()[0]
        return count
