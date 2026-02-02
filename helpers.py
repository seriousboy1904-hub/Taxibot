import math

def get_distance(lat1, lon1, lat2, lon2):
    # Haversine formulasi - ikki nuqta orasidagi masofani (km) hisoblaydi
    R = 6371.0 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def find_nearest_station(lat, lon, stations_geojson):
    features = stations_geojson.get('features', [])
    if not features: return "Noma'lum", 999
    
    min_dist = 999
    nearest_name = "Noma'lum"
    for st in features:
        s_lon, s_lat = st['geometry']['coordinates']
        dist = get_distance(lat, lon, s_lat, s_lon)
        if dist < min_dist:
            min_dist = dist
            nearest_name = st['properties']['name']
    return nearest_name, min_dist
