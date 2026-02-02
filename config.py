import os
from dotenv import load_dotenv
import json
with open("locations.json", "r", encoding="utf-8") as f:
    STATIONS = json.load(f)
load_dotenv()
CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_TOKEN")
