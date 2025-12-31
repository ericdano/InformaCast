import pandas as pd
import requests, json, os, sys
from pathlib import Path
import requests
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from pyzabbix import ZabbixAPI, ZabbixAPIException

#load configs
def getConfigs():
  # Function to get passwords and API keys for Acalanes Canvas and stuff
  confighome = Path('/opt/.Acalanes/Acalanes.json')
  with open(confighome) as f:
    configs = json.load(f)
  return configs

def fetch_all_informa_cast_data(base_url, token, limit=100):
    """
    Fetches all paginated data from an InformaCast API endpoint.

    Args:
        base_url (str): The initial API endpoint URL (e.g., 'api.icmobile.singlewire.com').
        api_key_or_token (str): Your API key or Bearer token for authorization.
        limit (int): The number of items to retrieve per request (optional).

    Returns:
        list: A list containing all retrieved records from all pages.
    """
    all_records = pd.DataFrame()
    current_url = f"{base_url}" # Start with offset 0
    warnings.simplefilter('ignore', InsecureRequestWarning)
    # The API might also use a 'next' URL in the response body instead of offset/limit
    # This example assumes limit/offset or similar parameters work.
    # If the API returns a 'next' link, you would update current_url from the response.

    while current_url:
        headers = {
            "Authorization": f"Basic {token}" # Use "Bearer" for cloud API
        }
        try:
            response = requests.get(current_url, headers=headers, verify=False)
            response.raise_for_status() # Raise an exception for bad status codes
            data = response.json()
            results = pd.json_normalize(response.json(),record_path="data", max_level=1)
            all_records = pd.concat([all_records,results], ignore_index=True)
            # Assuming the main data is in a key like 'results' or 'content'
            # Adjust 'results' based on actual API response structure
            # Check for pagination info in the response
            # The structure for the 'next' URL or 'offset' needs to be confirmed 
            # from the specific API documentation (e.g., InformaCast Fusion API explorer).
            
            # Placeholder for updating the next URL or parameters
            # You would need to check the API response for the specific field name
            # e.g., 'nextPageUrl', 'next', or calculate the next offset.
            # For demonstration, this loop would need logic to stop. 
            # Since an exact Singlewire API response structure isn't available, 
            # you'd implement specific logic here.
            
            # Example logic if it uses a 'next' link
            current_url = data.get('next') # Replace 'nextPageUrl' with actual key

            # Example logic if using manual offset calculation (remove 'break' statement if so)
            if not data.get('next'): # or other condition
                 break 

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            break
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            break
    all_records.drop(columns=['index','link'], inplace=True)
    #drop unnecessary columns if they exist
    return all_records
 
 def get_host_id(zapi, host_name):
    """Retrieves the internal Host ID based on the visible name."""
    host_search = zapi.host.get(filter={"name": host_name}, selectInterfaces=["interfaceid"])
    if not host_search:
        print(f"[-] Error: Host '{host_name}' not found.")
        return None, None
    
    host_id = host_search[0]['hostid']
    # Grab the first available interface ID (needed for item creation)
    interface_id = host_search[0]['interfaces'][0]['interfaceid']
    return host_id, interface_id

def sync_data_to_zabbix(configs, informacast_item, host_name):
    zapi = ZabbixAPI(configs['ZabbixURL'])
    try:
        zapi.login(configs['ZabbixUser'], configs['ZabbixPass'])
        print(f"[+] Connected to Zabbix. Looking up host: {host_name}")

        host_id, interface_id = get_host_id(zapi, host_name)
        if not host_id:
            return

        # Convert DataFrame to list of dictionaries
        items_to_process = informacast_item.to_dict('records')

        for item in items_to_process:
            item_name = item['name']
            # Standardizing the key (no spaces, lowercase)
            item_key = item_name.lower().replace(" ", ".")
            full_desc = f"IP: {item['attributes.ReportedIPv4Address']} | {item['description']}"

            # Check if item exists ON THIS HOST
            existing = zapi.item.get(filter={"name": item_name}, hostids=host_id)

            if existing:
                # UPDATE logic
                zapi.item.update(
                    itemid=existing[0]['itemid'],
                    status=int(item['status']),
                    description=full_desc
                )
                print(f"[OK] Updated existing item: {item_name}")
            else:
                # CREATE logic
                zapi.item.create(
                    name=item_name,
                    key_=item_key,
                    hostid=host_id,
                    type=2,         # Zabbix Trapper
                    value_type=4,   # Text
                    interfaceid=interface_id,
                    status=int(item['status']),
                    description=full_desc
                )
                print(f"[+] Created new item: {item_name}")

    except ZabbixAPIException as e:
        print(f"[-] Zabbix API Error: {e}")
    finally:
        zapi.logout()

if __name__ == "__main__":
    configs = getConfigs()
    token = configs['InformaCastToken']
    url = configs['InformaCastURL'] + '/Devices/?includeAttributes=true'
    results = fetch_all_informa_cast_data(url, token, limit=100)  
    # Pass the DataFrame to the sync function
    for host_name in results['description'].unique():
        subset_df = results[results['description'] == host_name]
        sync_data_to_zabbix(configs, subset_df, host_name)