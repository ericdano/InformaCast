import requests
import json
import pandas as pd

has_next_key = False
nextKey =""
startIndex = 100
jsonData = requests.get('https://172.16.227.7:443/InformaCast/RESTServices/V1/Devices/?includeAttributes=yes', verify=False, auth=('edannewitz', ''))
#print(r.status_code)
if "next" in jsonData:
    has_next_key = True
while has_next_key:
       

results = pd.json_normalize(r.json(),record_path="data", max_level=1)
#results = pd.concat([pd.json_normalize(r.json()), pd.json_normalize(r.json(),record_path="data", max_level=2)],axis=1).drop(columns=['data'])
print(results)
results.to_csv('phones.csv')
#print(r.content)
#contentstr = r.content
#json_str = json.dumps(contentstr,indent=4)
#print(json_str)