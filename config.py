import os
import json
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv()

CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_TOKEN")

with open(os.path.join(BASE_DIR, "locations.json"), "r", encoding="utf-8") as f:
    STATIONS = json.load(f)