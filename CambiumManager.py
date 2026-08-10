import requests
import logging
import logging.handlers
import json
import sys
import time
from pathlib import Path
import pandas as pd
from timeit import default_timer as timer
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

def delete_users_action(api_server_url, token, portal_name, user_ids):
    """
    Sends a PUT request to Cambium's action endpoint to bulk delete users.
    'user_ids' should be a list of user_id strings, e.g., ["1013477", "1013478"]
    """
    endpoint_url = f"{api_server_url}/api/v2/easypass/{portal_name}/onboarding/users/action"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    payload = {
        "action": "delete",
        "user_ids": user_ids if isinstance(user_ids, list) else [user_ids],
        "managed_account": "Acalanes Union High School"
    }
    
    # CRITICAL FIX: Changed requests.post to requests.put
    response = requests.put(endpoint_url, headers=headers, json=payload, timeout=30)
    
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        logger.warning(f"Rate limit hit! Pausing for {retry_after} seconds before retrying...")
        time.sleep(retry_after)
        return delete_users_action(api_server_url, token, portal_name, user_ids)
        
    response.raise_for_status()
    
    # A successful PUT often returns a 204 No Content (meaning no text body to parse)
    if response.status_code == 204:
        return True
        
    return response.json() if response.text else response.status_code


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
        
        logger.info(f"Fetching users {offset} to {offset + limit}...")
        response = requests.get(endpoint_url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 401:
            logger.warning("Token expired! Re-authenticating on the fly...")
            token, _ = get_access_token(base_url, client_id, client_secret)
            headers["Authorization"] = f"Bearer {token}"
            continue
            
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning(f"Rate limit hit! Pausing for {retry_after} seconds...")
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
       logger.info("Users stored in the local database successfully!")
    except Exception as e:
       logger.error(f"Error occurred while storing users in the database: {e}")

# ---------------------------------------------------------
# MAIN MENU EXECUTION
# ---------------------------------------------------------

if __name__ == '__main__':
    # --- Configuration Load ---
    confighome = Path.home() / ".Acalanes" / "Acalanes.json"
    with open(confighome) as f:
        configs = json.load(f)
        
    # --- Custom Logging Setup ---
    logger = logging.getLogger('Cambium Manager')
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    syslog_handler = logging.handlers.SysLogHandler(address=(configs['logserveraddress'], 514))
    formatter = logging.Formatter('%(name)s: %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    syslog_handler.setFormatter(formatter)
    logger.addHandler(syslog_handler)
    logger.addHandler(console_handler)

    # --- Variables & Database Connections ---
    CLIENT_ID = configs['CambiumAPI_ClientID']
    CLIENT_SECRET = configs['CambiumAPI_ClientSecret']
    PORTAL_NAME = configs['CambiumAPI_PortalName']
    BASE_URL = configs['CambiumAPI_URL']
    
    # Local Sync DB Connection
    aeries_local_conn_str = f"DRIVER={{SQL Server}};SERVER=aerieslink.acalanes.k12.ca.us\\LOCAL_AUHSD;DATABASE={configs.get('LocalAERIES_Cambium_DB', '')};UID={configs.get('LocalAERIES_Username', '')};PWD={configs.get('LocalAERIES_Password', '')};"
    
    # AERIES Live Database Connection
    aeries_live_conn_str = "DRIVER={SQL Server};SERVER=" + configs['AERIESSQLServer'] + ";DATABASE=" + configs['AERIESDatabase'] + ";UID=" + configs['AERIESUsername'] + ";PWD=" + configs['AERIESPassword'] + ";"
    aeries_connection_url = URL.create("mssql+pyodbc", query={"odbc_connect": aeries_live_conn_str})
    aeries_engine = create_engine(aeries_connection_url)

    logger.info("Authenticating with Cambium API...")
    try:
        token, api_server_url = get_access_token(BASE_URL, CLIENT_ID, CLIENT_SECRET)
        api_server_url = api_server_url.rstrip('/')
        logger.info("Authentication successful.")
    except Exception as e:
        logger.error(f"Failed to authenticate: {e}")
        sys.exit(1)

    while True:
        print("\n" + "="*50)
        print(" CAMBIUM API MANAGER ".center(50))
        print("="*50)
        print("1. Add a new user")
        print("2. Update an existing user's passphrase")
        print("3. Sync Cambium users to local Database")
        print("4. DELETE ALL USERS in Cambium (Danger Zone)")
        print("5. WIPE Cambium AND Sync from AERIES Live")
        print("6. Quit")
        print("="*50)
        
        choice = input("Select an option (1-6): ").strip()

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
                logger.info(f"Successfully added! API Response: {result}")

            elif choice == '2':
                print("\n--- UPDATE PASSPHRASE ---")
                user_id = input("Enter the User ID to update: ")
                new_passphrase = input("Enter the new passphrase: ")
                
                result = update_user_passphrase(api_server_url, token, PORTAL_NAME, user_id, new_passphrase)
                logger.info(f"Successfully updated! API Response: {result}")

            elif choice == '3':
                print("\n--- SYNC USERS TO LOCAL DB ---")
                master_user_list = get_all_paginated_users(BASE_URL, CLIENT_ID, CLIENT_SECRET, api_server_url, token, PORTAL_NAME)
                logger.info(f"Downloaded {len(master_user_list)} users. Saving to database...")
                store_users_in_db(pd.DataFrame(master_user_list), aeries_local_conn_str)

            elif choice == '4':
                print("\n--- ⚠️ DELETE ALL USERS ⚠️ ---")
                confirm = input("Are you absolutely sure you want to delete ALL users? Type 'YES' to confirm: ")
                
                if confirm == 'YES':
                    logger.info("Fetching current user list to begin deletion...")
                    users_to_delete = get_all_paginated_users(BASE_URL, CLIENT_ID, CLIENT_SECRET, api_server_url, token, PORTAL_NAME)
                    
                    if not users_to_delete:
                        logger.info("No users found to delete.")
                        continue
                    
                    # Extract IDs
                    all_ids = [str(u.get("user_id") or u.get("id")) for u in users_to_delete if u.get("user_id") or u.get("id")]
                    logger.info(f"Found {len(all_ids)} users. Beginning batch deletion...")
                    
                    # Process in chunks of 50 to avoid payload size limits
                    chunk_size = 50
                    for i in range(0, len(all_ids), chunk_size):
                        batch = all_ids[i:i + chunk_size]
                        delete_users_action(api_server_url, token, PORTAL_NAME, batch)
                        logger.info(f"Deleted batch {i // chunk_size + 1} ({len(batch)} users)...")
                        time.sleep(0.5)
                            
                    logger.info(f"✅ Successfully wiped all users from Cambium Onboarding.")
                else:
                    logger.info("Deletion canceled.")

            elif choice == '5':
                print("\n--- ⚠️ WIPE CAMBIUM AND SYNC FROM AERIES ⚠️ ---")
                confirm = input("This will DELETE ALL USERS in Cambium and pull a fresh list from AERIES. Type 'YES' to confirm: ")
                
                if confirm == 'YES':
                    logger.info("Starting bulk wipe and AERIES sync process.")
                    
                    # --- 1. Delete all existing Cambium users in batches ---
                    users_to_delete = get_all_paginated_users(BASE_URL, CLIENT_ID, CLIENT_SECRET, api_server_url, token, PORTAL_NAME)
                    all_ids = [str(u.get("user_id") or u.get("id")) for u in users_to_delete if u.get("user_id") or u.get("id")]
                    
                    if all_ids:
                        logger.info(f"Wiping {len(all_ids)} existing users from Cambium...")
                        chunk_size = 50
                        for i in range(0, len(all_ids), chunk_size):
                            batch = all_ids[i:i + chunk_size]
                            delete_users_action(api_server_url, token, PORTAL_NAME, batch)
                            time.sleep(0.5)
                        logger.info("✅ Bulk wipe complete.")
                    
                    # --- 2. Query AERIES Live ---
                    query = "SELECT ln, fn, ID, SEM, NID FROM STU WHERE DEL = 0 AND SEM IS NOT NULL AND SEM != ''"
                    logger.info("Querying AERIES Live Database for active students...")
                    df_aeries = pd.read_sql(query, aeries_engine)
                    
                    logger.info(f"Found {len(df_aeries)} students in AERIES. Beginning import to Cambium...")
                    
                    # --- 3. Import to Cambium ---
                    added_count = 0
                    for index, row in df_aeries.iterrows():
                        if pd.isna(row['ID']) or pd.isna(row['SEM']):
                            continue
                            
                        new_student = {
                            "username": f"{str(row['ln']).strip()}, {str(row['fn']).strip()}",
                            "user_id": str(row['ID']).strip(),
                            "email": str(row['SEM']).strip(),
                            "passphrase": str(row['NID']).strip(),
                            "device_limit": 2,
                            "managed_account": "Acalanes Union High School",
                            "expire": False
                        }
                        
                        try:
                            add_onboarding_user(api_server_url, token, PORTAL_NAME, new_student)
                            added_count += 1
                            if added_count % 100 == 0:
                                logger.info(f"Import progress: {added_count} users added...")
                        except Exception as e:
                            logger.error(f"Failed to add student {row['SEM']}: {e}")
                            
                    logger.info(f"✅ Successfully imported {added_count} users from AERIES Live to Cambium.")
                else:
                    logger.info("Wipe & Sync canceled.") 

            elif choice == '6':
                logger.info("Exiting Cambium API Manager.")
                break
                
            else:
                logger.warning("Invalid choice. Please select 1-6.")
                
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err}")
            if http_err.response is not None:
                logger.error(f"Response Body: {http_err.response.text}")
        except Exception as err:
            logger.error(f"An unexpected error occurred: {err}")