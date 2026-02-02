# Haydovchi joylashuvini jonli (live) yangilab turish uchun handler
@driver_dp.edited_message(F.location)
async def driver_live_location_update(message: types.Message):
    if message.location:
        lat = message.location.latitude
        lon = message.location.longitude
        
        async with aiosqlite.connect(DB_FILE) as db:
            # Faqat 'online' holatdagi haydovchining koordinatalarini yangilaymiz
            # Bu haydovchi harakatlanganda bazadagi ma'lumotini yangilab turadi
            await db.execute(
                "UPDATE drivers SET lat = ?, lon = ?, last_seen = ? WHERE user_id = ? AND status = 'online'",
                (lat, lon, datetime.now().isoformat(), message.from_user.id)
            )
            await db.commit()
