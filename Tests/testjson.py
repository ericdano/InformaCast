import json

# Your source data
raw_items = [
    {"name": "WebSrv-01", "ip": "192.168.1.10", "status": 1, "mac": "00:1A:2B:3C:4D:5E", "id": "101"},
    {"name": "DB-01", "ip": "192.168.1.20", "status": 0, "mac": "00:1A:2B:3C:4D:5F", "id": "102"}
]

output = []
for item in raw_items:
    output.append({
        "{#ITEMNAME}": item["name"],
        "{#ITEMIP}": item["ip"],
        "{#ITEMMAC}": item["mac"],
        "{#ITEMID}": item["id"]
    })

print(json.dumps(output))