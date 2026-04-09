import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://accident-alert-system-18326-default-rtdb.firebaseio.com'
})

db.reference('/alerts').push({
    "lat": 11.0168,
    "lon": 76.9558,
    "description": "Test accident on Avinashi Road",
    "incident_id": "INC-TEST",
    "severity": "Major",
    "collision_type": "car vs car",
    "score": 0.75,
    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    "location": "Coimbatore",
    "status": "pending"
})

print("✅ Test alert sent! Check your friend's dashboard.")