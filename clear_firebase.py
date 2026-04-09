import firebase_admin
from firebase_admin import credentials, db

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://accident-alert-system-18326-default-rtdb.firebaseio.com/'
})

print("Clearing /alerts...")
db.reference('/alerts').delete()
print("✅ Firebase /alerts cleared! All prior incidents removed.")
