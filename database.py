    def update_driver_status(self, user_id, lat, lon, station, status="idle"):
        with self.connection:
            # Agar haydovchi allaqachon bo'lsa, faqat ma'lumotlarini yangilaymiz (vaqtni emas!)
            self.cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            if self.cursor.fetchone():
                return self.cursor.execute(
                    "UPDATE users SET last_lat=?, last_lon=?, current_station=?, status=? WHERE user_id=?",
                    (lat, lon, station, status, user_id)
                )
            else:
                # Birinchi marta kirganda qo'shamiz
                return self.cursor.execute(
                    "INSERT INTO users (user_id, last_lat, last_lon, current_station, status) VALUES (?, ?, ?, ?, ?)",
                    (user_id, lat, lon, station, status)
                )
