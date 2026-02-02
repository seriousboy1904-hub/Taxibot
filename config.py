import os
import json
from dotenv import load_dotenv

load_dotenv()

CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_TOKEN")

# JSON faylni xavfsiz o'qish
STATIONS = []
if os.path.exists('locations.json'):
    with open('locations.json', 'r', encoding='utf-8') as f:
        try:
            STATIONS = json.load(f)
        except:
            STATIONS = []
