import os
import json
from dotenv import load_dotenv

load_dotenv()

CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_TOKEN")

# JSON faylni o'qish qismini qo'shing
try:
    with open('locations.json', 'r', encoding='utf-8') as f:
        STATIONS = json.load(f)
except Exception as e:
    STATIONS = []
    print(f"Xato: locations.json yuklanmadi: {e}")
