import math

def find_nearest_station(lat, lon, stations):
    def distance(lat1, lon1, lat2, lon2):
        return math.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2)

    nearest = None
    min_dist = float("inf")

    for s in stations:
        d = distance(lat, lon, s["lat"], s["lon"])
        if d < min_dist:
            min_dist = d
            nearest = s

    return nearest["name"], min_dist