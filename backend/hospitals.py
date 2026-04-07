"""
Hospital Registry & Proximity Module
Stores hospital locations and provides utility to find nearby responders.
"""

import math
from typing import List, Dict, Any

# Mock hospitals in Coimbatore (based on the dashboard map markers)
HOSPITALS = [
    {
        "id": "HOSP-01",
        "name": "KMCH Speciality Hospital",
        "lat": 11.0416,
        "lng": 77.0427,
        "availability": "High",
        "ambulances": 5,
        "contact": "+91 422 4323333"
    },
    {
        "id": "HOSP-02",
        "name": "PSG Hospitals",
        "lat": 11.0254,
        "lng": 77.0016,
        "availability": "Medium",
        "ambulances": 3,
        "contact": "+91 422 2570170"
    },
    {
        "id": "HOSP-03",
        "name": "GKNM Hospital",
        "lat": 11.0112,
        "lng": 76.9749,
        "availability": "High",
        "ambulances": 4,
        "contact": "+91 422 2212121"
    },
    {
        "id": "HOSP-04",
        "name": "KG Hospital",
        "lat": 10.9987,
        "lng": 76.9647,
        "availability": "Low",
        "ambulances": 1,
        "contact": "+91 422 2212121"
    },
    {
        "id": "HOSP-05",
        "name": "Royal Care Hospital",
        "lat": 11.0654,
        "lng": 77.0516,
        "availability": "High",
        "ambulances": 6,
        "contact": "+91 422 2227000"
    }
]

def get_distance(lat1, lon1, lat2, lon2):
    """Haversine formula to calculate distance in km."""
    R = 6371  # Earth radius
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def find_nearby_hospitals(at_lat: float, at_lng: float, radius_km: float = 10.0) -> List[Dict[str, Any]]:
    nearby = []
    for h in HOSPITALS:
        dist = get_distance(at_lat, at_lng, h["lat"], h["lng"])
        if dist <= radius_km:
            h_copy = h.copy()
            h_copy["distance_km"] = round(dist, 2)
            nearby.append(h_copy)
            
    # Sort by distance
    nearby.sort(key=lambda x: x["distance_km"])
    return nearby
