import pandas as pd
import requests, json, os, sys
from pathlib import Path
import requests
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning

#load configs
def getConfigs():
  # Function to get passwords and API keys for Acalanes Canvas and stuff
  confighome = Path.home() / ".Acalanes" / "Acalanes.json"
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

    # The API might also use a 'next' URL in the response body instead of offset/limit
    # This example assumes limit/offset or similar parameters work.
    # If the API returns a 'next' link, you would update current_url from the response.
    warnings.simplefilter('ignore', InsecureRequestWarning)
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
    all_records.drop(columns=['index','link','isDesktopNotifier'], inplace=True)
    #drop unnecessary columns if they exist
    return all_records

def discover(url, token, limit):
    """Converts DataFrame rows into Zabbix LLD JSON format"""
    df = fetch_all_informa_cast_data(url, token, limit)
    
    # Convert DataFrame to list of dictionaries for discovery
    lld_data = []
    for _, row in df.iterrows():
        lld_data.append({
            "{#ITEMNAME}": str(row["name"]),
            "{#ITEMIP}":   str(row["ip"]),
            "{#ITEMMAC}":  str(row["mac"]),
            "{#ITEMID}":   str(row["id"])
        })
    print(json.dumps(lld_data))

def get_value(target_name, attribute, url, token, limit):
    """Uses Pandas to find a specific value based on the item name"""
    df = fetch_all_informa_cast_data(url, token, limit)
    
    try:
        # Filter where name matches, then grab the specific column
        result = df.loc[df['name'] == target_name, attribute].values[0]
        print(result)
    except (IndexError, KeyError):
        print("Not Found")


if __name__ == "__main__":
    configs = getConfigs()
    token = configs['InformaCastToken']
    url = configs['InformaCastURL'] + 'IPSpeakers'
    if len(sys.argv) == 1:
        discover(url, token, limit=100)
    elif len(sys.argv) == 3:
        get_value(sys.argv[1], sys.argv[2], url, token, limit=100)