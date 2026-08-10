import requests
import logging
import json
import sys
import time
from pathlib import Path
import pandas as pd
from timeit import default_timer as timer
from logging.handlers import SysLogHandler
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

# ---------------------------------------------------------
# CORE API FUNCTIONS
# ---------------------------------------------------------

def get_access_token(base_url, client_id, client_secret):
    token_url = f"{base_url}/api/v2/access/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    response = requests.post(token_url, data=payload, headers=headers, timeout=10)
    response.raise_for_status() 
    
    data = response.json()
    return data.get("access_token"), data.get("redirect_uri", base_url)

def add_onboarding_user(api_server_url, token, portal_name, new_user_data):
    endpoint_url = f"{api_server_url}/api/v2/easypass/{portal_name}/onboarding/users"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    response = requests.post(endpoint_url, headers=headers, json=new_user_data, timeout=10)
    response.raise_for_status()
    return response.json()

def update_user_passphrase(api_server_url, token, portal_name, user_id, new_passphrase):
    endpoint_url = f"{api_server_url}/api/v2/easypass/{portal_name}/onboarding/users/{user_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    update_payload = {
        "passphrase": new_passphrase,
        "managed_account": "Acalanes Union High School"
    }
    response = requests.put(endpoint_url, headers=headers, json=update_payload, timeout=10)
    response.raise_for_status()
    
    if response.status_code == 204:
        return {"status": "success", "message": "Passphrase updated successfully"}
    return response.json()

def delete_user(api_server_url, token, portal_name, user_id):
    """
    Sends a DELETE request to remove a user from Onboarding.
    """
    endpoint_url = f"{api_server_url}/api/v2/easypass/{portal_name}/onboarding/users/{user_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    response = requests.delete(endpoint_url, headers=headers, timeout=10)
    
    # Handle rate limiting during bulk deletes
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        print(f"--> Rate limit hit! Pausing for {retry_after} seconds before retrying...", flush=True)
        time.sleep(retry_after)
        return delete_user(api_server_url, token, portal_name, user_id)
        
    response.raise_for_status()
    return response.status_code

def get_all_paginated_users(base_url, client_id, client_secret, api_server_url, initial_token, portal_name):
    endpoint_url = f"{api_server_url}/api/v2/easypass/{portal_name}/onboarding/users"
    token = initial_token
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    all_users = []
    offset = 0
    limit = 100  
    
    while True:
        params = {
            "limit": limit,
            "offset": offset,
            "managed_account": "Acalanes Union High School",
            "fields": "username,user_id,email,group,passphrase,expiration"
        }
        
        print(f"Fetching users {offset} to {offset + limit}...", flush=True)
        response = requests.get(endpoint_url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 401:
            print("\n--> Token expired! Re-authenticating on the fly...", flush=True)
            token, _ = get_access_token(base_url, client_id, client_secret)
            headers["Authorization"] = f"Bearer {token}"
            continue
            
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            print(f"--> Rate limit hit! Pausing for {retry_after} seconds...", flush=True)
            time.sleep(retry_after)
            continue  
            
        response.raise_for_status()
        data = response.json()
        users_batch = data.get("data", [])
        
        if not users_batch:
            break
            
        all_users.extend(users_batch)
        
        total_users = data.get("paging", {}).get("total", 0)
        if offset + limit >= total_users:
            break
            
        offset += limit
        time.sleep(1.0) 
        
    return all_users

def store_users_in_db(df, db_connection_string):
    if 'expiration' in df.columns:
       df['expiration'] = pd.to_datetime(df['expiration'], errors='coerce')

    connection_url = URL.create("mssql+pyodbc", query={"odbc_connect": db_connection_string})
    sql_engine = create_engine(connection_url)
    try:
       df.to_sql('Current_Passwords', con=sql_engine, if_exists='replace', index=False, method='multi')
       print("\n✅ Users stored in the database successfully!")
    except Exception as e:
       print(f"\n❌ Error occurred while storing users in the database: {e}")

# ---------------------------------------------------------
# MAIN MENU EXECUTION
# ---------------------------------------------------------

if __name__ == '__main__':
    # --- Configuration Load ---
    confighome = Path.home() / ".Acalanes" / "Acalanes.json"
    with open(confighome) as f:
        configs = json.load(f)
        
    thelogger = logging.getLogger('MyLogger')
    thelogger.setLevel(logging.DEBUG)
    handler = logging.handlers.SysLogHandler(address=(configs['logserveraddress'], 514))
    thelogger.addHandler(handler)

    CLIENT_ID = configs['CambiumAPI_ClientID']
    CLIENT_SECRET = configs['CambiumAPI_ClientSecret']
    PORTAL_NAME = configs['CambiumAPI_PortalName']
    BASE_URL = configs['CambiumAPI_URL']
    aeries_local_conn_str = f"DRIVER={{SQL Server}};SERVER=aerieslink.acalanes.k12.ca.us\\LOCAL_AUHSD;DATABASE={configs.get('LocalAERIES_Cambium_DB', '')};UID={configs.get('LocalAERIES_Username', '')};PWD={configs.get('LocalAERIES_Password', '')};"

    print("\nAuthenticating with Cambium API...", flush=True)
    try:
        token, api_server_url = get_access_token(BASE_URL, CLIENT_ID, CLIENT_SECRET)
        api_server_url = api_server_url.rstrip('/')
        print("✅ Authentication successful.")
    except Exception as e:
        print(f"❌ Failed to authenticate: {e}")
        sys.exit(1)

    while True:
        print("\n" + "="*40)
        print(" CAMBIUM API MANAGER ")
        print("="*40)
        print("1. Add a new user")
        print("2. Update an existing user's passphrase")
        print("3. Sync all users to local Database")
        print("4. DELETE ALL USERS (Danger Zone)")
        print("5. Quit")
        print("="*40)
        
        choice = input("Select an option (1-5): ").strip()

        try:
            if choice == '1':
                print("\n--- ADD USER ---")
                username = input("Enter Full Name: ")
                user_id = input("Enter User ID (e.g., Student ID): ")
                email = input("Enter Email Address: ")
                passphrase = input("Enter Passphrase (leave blank to auto-generate): ")
                
                new_student = {
                    "username": username,
                    "user_id": user_id,
                    "email": email,
                    "device_limit": 2,
                    "managed_account": "Acalanes Union High School",
                    "expire": False
                }
                if passphrase:
                    new_student["passphrase"] = passphrase
                    
                result = add_onboarding_user(api_server_url, token, PORTAL_NAME, new_student)
                print(f"✅ Successfully added! API Response: {result}")

            elif choice == '2':
                print("\n--- UPDATE PASSPHRASE ---")
                user_id = input("Enter the User ID to update: ")
                new_passphrase = input("Enter the new passphrase: ")
                
                result = update_user_passphrase(api_server_url, token, PORTAL_NAME, user_id, new_passphrase)
                print(f"✅ Successfully updated! API Response: {result}")

            elif choice == '3':
                print("\n--- SYNC USERS TO DB ---")
                master_user_list = get_all_paginated_users(BASE_URL, CLIENT_ID, CLIENT_SECRET, api_server_url, token, PORTAL_NAME)
                print(f"\n✅ Downloaded {len(master_user_list)} users. Saving to database...")
                store_users_in_db(pd.DataFrame(master_user_list), aeries_local_conn_str)

            elif choice == '4':
                print("\n--- ⚠️ DELETE ALL USERS ⚠️ ---")
                confirm = input("Are you absolutely sure you want to delete ALL users? Type 'YES' to confirm: ")
                
                if confirm == 'YES':
                    print("Fetching current user list to begin deletion...")
                    users_to_delete = get_all_paginated_users(BASE_URL, CLIENT_ID, CLIENT_SECRET, api_server_url, token, PORTAL_NAME)
                    
                    if not users_to_delete:
                        print("No users found to delete.")
                        continue
                        
                    print(f"Found {len(users_to_delete)} users. Beginning deletion loop...")
                    deleted_count = 0
                    
                    for u in users_to_delete:
                        u_id = u.get("user_id") or u.get("id") # Using ID depending on payload format
                        if u_id:
                            delete_user(api_server_url, token, PORTAL_NAME, u_id)
                            deleted_count += 1
                            # Brief pause to respect API speed limits
                            time.sleep(0.1) 
                            
                    print(f"✅ Wiped {deleted_count} users from Cambium Onboarding.")
                else:
                    print("Deletion canceled.")

            elif choice == '5':
                print("Exiting...")
                break
                
            else:
                print("Invalid choice. Please select 1-5.")
                
        except requests.exceptions.HTTPError as http_err:
            print(f"\n❌ HTTP error occurred: {http_err}", file=sys.stderr)
            if http_err.response is not None:
                print(f"Response Body: {http_err.response.text}", file=sys.stderr)
        except Exception as err:
            print(f"\n❌ An unexpected error occurred: {err}", file=sys.stderr)

            