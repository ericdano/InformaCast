from ldap3 import Server, Connection, ALL, SUBTREE
import os, sys, shlex, subprocess, json, logging, logging.handlers, gam, smtplib, datetime, socket
import getpass
from pathlib import Path
import pandas as pd

# 1. Configuration
# First Domain Settings
SERVER_1 = "paris"
SOURCE_1 = "STAFF"

# Second Domain Settings
SERVER_2 = "zeus"
SOURCE_2 = "AUHSD"

# List of schools to query and generate CSVs for [School Name, Google Sheet URL]
SCHOOLS = [
    ["LLHS", "https://docs.google.com/spreadsheets/d/1zIFKJCTMHUMiyHS7bChh8f6_bkRmm6FArwsgnA19KIk"],
    ["MHS", "https://docs.google.com/spreadsheets/d/1X_BU4StsQ2mYXezm4FACQOVJn32eUb8wYUh4X3pa0AM"],
    ["AHS", "https://docs.google.com/spreadsheets/d/1nqv9N6i84rX7G5-ACRARRQPIcMmTmk4BLeIxiM23s5c"],
    ["CHS", "https://docs.google.com/spreadsheets/d/1XSgGu9j4BWtJZUFaLmq5MR7UyoeqTL6ETQH-kqFUNdg"]
]


def getConfigs():
    # Function to get passwords and API keys for Acalanes Canvas and stuff
    confighome = Path.home() / ".Acalanes" / "Acalanes.json"
    with open(confighome) as f:
        configs = json.load(f)
    return configs


def query_ad(server_name, search_base, source_label, configs):
    server_uri = 'LDAP://' + server_name
    domain_name = 'AUHSD'
    user_name = 'tech'
    password = configs['ADPassword']
    
    logger.info(f"Querying {search_base} on {server_uri} as {domain_name}\\{user_name}...")
    users_list = []
    
    try:
        with Connection(Server(server_uri),
                        user='{0}\\{1}'.format(domain_name, user_name), 
                        password=password, 
                        auto_bind=True) as conn:
            
            results = conn.extend.standard.paged_search(
                search_base=search_base, 
                search_filter='(&(objectCategory=person)(objectClass=user))', 
                search_scope=SUBTREE,
                attributes=['name', 'description', 'ipPhone', 'pager'],
                get_operational_attributes=False, 
                paged_size=1000
            )
            
            def get_val(attrs_dict, key):
                val = attrs_dict.get(key, "")
                if isinstance(val, list):
                    return ", ".join(str(v) for v in val)
                return str(val)

            for entry in results:
                if entry.get('type') == 'searchResEntry':
                    attrs = entry.get('attributes', {})
                    # Updated keys to match your Pandas DataFrame requirements
                    users_list.append({
                        "Name": get_val(attrs, 'name'),
                        "Description": get_val(attrs, 'description'),
                        "Phone": get_val(attrs, 'ipPhone'),
                        "Copier Code": get_val(attrs, 'pager'),
                        "Domain": source_label
                    })
                    
        return users_list
        
    except Exception as e:
        logger.error(f"Failed to query {server_uri} for {search_base}: {e}")
        return []


if __name__ == "__main__":
    global msgbody, logger, gstatus
    configs = getConfigs()
    gstatus = ''
    
    # Setup Logging
    logger = logging.getLogger('Expire AD Accounts Script')
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    syslog_handler = logging.handlers.SysLogHandler(address=(configs['logserveraddress'], 514))
    formatter = logging.Formatter('%(name)s: %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    syslog_handler.setFormatter(formatter)
    logger.addHandler(syslog_handler)
    logger.addHandler(console_handler)
    
    # Optional: Define your GAM admin account here if required by your GAM setup
    gam_admin = "edannewitz@auhsdschools.org"
    
    # Loop through each school and generate a separate CSV
    for school_data in SCHOOLS:
        school = school_data[0]
        sheet_url = school_data[1]
        
        logger.info(f"--- Processing data for {school} ---")
        
        # Define dynamic search bases for the current school
        search_base_1 = f"OU={school},OU=Acad Staff,DC=staff,DC=acalanes,DC=k12,DC=ca,DC=us"
        search_base_2 = f"OU={school},OU=AUHSD Staff,DC=acalanes,DC=k12,DC=ca,DC=us"
        
        # Execute queries 
        users_1 = query_ad(SERVER_1, search_base_1, SOURCE_1, configs)
        users_2 = query_ad(SERVER_2, search_base_2, SOURCE_2, configs)
        
        # Combine both sets of users into one list
        combined_users = users_1 + users_2
        
        if not combined_users:
            logger.warning(f"No users found or authentication failed for {school}. Skipping CSV creation.")
        else:
            logger.info(f"Converting data to Pandas DataFrame and exporting to CSV for {school}...")
            
            # Use Pandas to create the DataFrame and export it
            df = pd.DataFrame(combined_users)
            df = df[["Name", "Description", "Phone", "Copier Code", "Domain"]]
            
            export_path = f"Combined_{school}_Staff.csv"
            df.to_csv(export_path, index=False, encoding='utf-8-sig')
            logger.info(f"Successfully exported {len(df)} users to: {export_path}")
            
            # --- GAM UPLOAD SECTION ---
            # Extract just the Sheet ID from the URL
            sheet_id = sheet_url.split('/d/')[1].split('/')[0]
            
            # Build the GAM command. (Adjust standard vs GAMADV syntax if needed)
            gam_cmd = f"gam user {gam_admin} update drivefile {sheet_id} localfile {export_path}"
            
            logger.info(f"Uploading {export_path} to Google Sheet via GAM...")
            try:
                # Use subprocess to fire the GAM command
                subprocess.run(gam_cmd, shell=True, check=True, capture_output=True, text=True)
                logger.info(f"Successfully updated Google Sheet for {school}.")
            except subprocess.CalledProcessError as e:
                logger.error(f"GAM upload failed for {school}. Error: {e.stderr}")