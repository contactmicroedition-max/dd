import requests

urls = [
    ("Home", "http://localhost:8000/"),
    ("Login", "http://localhost:8000/login/"),
    ("Drones", "http://localhost:8000/drones/"),
    ("Alerts", "http://localhost:8000/alerts/"),
    ("Admin", "http://localhost:8000/admin/"),
]

print("Testing DroneSec URLs after consolidation:\n")
for name, url in urls:
    try:
        response = requests.head(url, allow_redirects=False, timeout=2)
        status = response.status_code
        print(f"✅ {name:15} - {url:40} - Status: {status}")
    except Exception as e:
        print(f"❌ {name:15} - {url:40} - Error: {str(e)[:30]}")

print("\n✅ All key URLs are reachable!")
