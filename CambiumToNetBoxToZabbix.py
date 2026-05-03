import os
import sys
import json
import time
import requests
import pynetbox
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from pyzabbix import ZabbixAPI

# ==========================================
# Configuration & Credentials
# ==========================================
confighome = Path.home() / ".Acalanes" / "Acalanes.json"

try:
    with open(confighome, 'r') as f:
        configs = json.load(f)
        
    # Cambium Config
    CAMBIUM_BASE_URL = configs.get('CambiumAPI_URL') 
    CAMBIUM_CLIENT_ID = configs.get('CambiumAPI_ClientID')
    CAMBIUM_CLIENT_SECRET = configs.get('CambiumAPI_ClientSecret')

    # NetBox Config
    NETBOX_URL = configs.get('NetBox_URL')
    NETBOX_TOKEN = configs.get('NetBox_Token')
    
    # Zabbix Config
    ZABBIX_URL = configs.get('Zabbix_URL')
    ZABBIX_TOKEN = configs.get('Zabbix_Token')
    
except Exception as e:
    print(f"Config load error: {e}", file=sys.stderr)
    sys.exit(1)

# ==========================================
# Email Reporting Function
# ==========================================
def send_status_email(changes):
    """Sends an email report for every run, even if no changes were made."""
    print("\nPreparing status email (Heartbeat)...")
    
    smtp_server = configs.get('SMTPServerAddress')
    smtp_port = configs.get('SMTP_Port', 25) 
    email_from = configs.get('SMTPAddressFrom')
    email_to = configs.get('SendInfoEmailAddr')

    if not all([smtp_server, email_from, email_to]):
        print("🔴 [Warning] Email configuration incomplete in Acalanes.json. Cannot send report.")
        return

    # Create a dynamic subject line
    status_label = f"{len(changes)} Changes" if changes else "Heartbeat - No Changes"
    subject = f"🟢 Acalanes Event Log - Network Sync Report: {status_label}"
    
    # Build the body content
    if changes:
        body = "The Cambium integration script completed and made the following updates:\n\n"
        for change in changes:
            body += f" - {change}\n"
    else:
        body = "The Cambium integration script completed successfully. No changes were necessary at this time."
        
    body += "\n\nEnd of Report."

    msg = MIMEMultipart()
    msg['From'] = email_from
    msg['To'] = email_to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Connect strictly on port 25 with no TLS and no login
        server = smtplib.SMTP(smtp_server, int(smtp_port))
        server.send_message(msg)
        server.quit()
        print(f"  -> Heartbeat email successfully sent to {email_to}")
    except Exception as e:
        print(f"  -> Failed to send email: {e}")

# ==========================================
# Cambium Functions
# ==========================================

def get_access_token(base_url, client_id, client_secret):
    """Authenticates and retrieves the token and API redirect URI."""
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

def get_cambium_aps(base_url, client_id, client_secret, api_server_url, initial_token):
    """Fetches paginated APs from Cambium Cloud."""
    endpoint_url = f"{api_server_url}/api/v2/devices"
    
    token = initial_token
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    ap_list = []
    offset = 0
    limit = 100  
    
    print("Fetching APs from Cambium Cloud...", flush=True)

    while True:
        params = {"limit": limit, "offset": offset}
        
        print(f"  -> Pulling devices {offset} to {offset + limit}...", flush=True)
        response = requests.get(endpoint_url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 401:
            print("\n  --> Token expired! Re-authenticating on the fly...", flush=True)
            token, _ = get_access_token(base_url, client_id, client_secret)
            headers["Authorization"] = f"Bearer {token}"
            print("  --> Resuming download...\n", flush=True)
            continue  
            
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            print(f"  --> Rate limit hit! Pausing for {retry_after} seconds before retrying...", flush=True)
            time.sleep(retry_after)
            continue  
            
        response.raise_for_status()
        
        data = response.json()
        raw_devices = data.get("data", [])
        
        if not raw_devices:
            break
            
        for device in raw_devices:
            if "wifi" in device.get("type", ""): 
                ap_list.append({
                    "hostname": device.get("name"),
                    "ip_address": device.get("ip"),
                    "serial": device.get("msn"), 
                    "mac": device.get("mac"),    
                    "model": device.get("product"),
                    "site": device.get("site")   
                })
        
        total_devices = data.get("paging", {}).get("total", 0)
        if offset + limit >= total_devices:
            break
            
        offset += limit
        time.sleep(1.0) 
        
    print(f"Found {len(ap_list)} APs.")
    return ap_list

# ==========================================
# NetBox & Zabbix Functions
# ==========================================
def assign_ip_to_netbox_device(nb, device, ip_address):
    """Creates an interface, assigns the IP, and sets it as Primary IPv4."""
    if not ip_address:
        return

    ip_cidr = f"{ip_address}/24"
    interface_name = "wlan0"

    interface = nb.dcim.interfaces.get(device_id=device.id, name=interface_name)
    if not interface:
        interface = nb.dcim.interfaces.create(
            device=device.id, 
            name=interface_name, 
            type="other"
        )

    ip_obj = nb.ipam.ip_addresses.get(address=ip_cidr)
    if ip_obj:
        if getattr(ip_obj, 'assigned_object_id', None) != interface.id:
            ip_obj.assigned_object_type = "dcim.interface"
            ip_obj.assigned_object_id = interface.id
            ip_obj.save()
    else:
        ip_obj = nb.ipam.ip_addresses.create(
            address=ip_cidr,
            assigned_object_type="dcim.interface",
            assigned_object_id=interface.id
        )

    current_primary = getattr(device, 'primary_ip4', None)
    if not current_primary or current_primary.id != ip_obj.id:
        device.primary_ip4 = ip_obj.id
        device.save()
        print(f"    [NetBox] Assigned {ip_cidr} as Primary IPv4.")

def sync_to_netbox(aps, changes):
    """Syncs the extracted APs into NetBox, auto-creating Device Types as needed."""
    print("\nSyncing to NetBox...")
    nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)

    DEVICE_ROLE_ID = 2   

    print("  -> Caching NetBox Sites...")
    netbox_sites = {site.name: site.id for site in nb.dcim.sites.all()}
    
    print("  -> Caching Device Types...")
    netbox_device_types = {dt.model: dt.id for dt in nb.dcim.device_types.all()}

    manufacturer_name = "Cambium Networks"
    manuf = nb.dcim.manufacturers.get(name=manufacturer_name)
    if not manuf:
        print(f"  [NetBox] Creating Manufacturer: {manufacturer_name}...")
        manuf = nb.dcim.manufacturers.create(name=manufacturer_name, slug="cambium-networks")
        changes.append(f"[NetBox] Created new Manufacturer: {manufacturer_name}")
    manuf_id = manuf.id

    SITE_TRANSLATOR = {
        "Acalanes": "Acalanes High School",    
        "Miramonte": "Miramonte High School",
        "Las Lomas": "Las Lomas High School",
        "Campolindo": "Campolindo High School",
        "": "Unknown Site"                     
    }

    for ap in aps:
        if not ap["hostname"]:
            continue
            
        raw_cambium_site = ap.get("site", "")
        netbox_site_name = SITE_TRANSLATOR.get(raw_cambium_site, raw_cambium_site) 
        site_id = netbox_sites.get(netbox_site_name)

        if not site_id:
            print(f" [Warning] Skipping {ap['hostname']}: Translated Site '{netbox_site_name}' not found in NetBox.")
            continue

        model_name = ap.get("model", "Unknown Model")
        device_type_id = netbox_device_types.get(model_name)

        if not device_type_id:
            print(f"  [NetBox] Auto-creating new Device Type for model: {model_name}...")
            model_slug = re.sub(r'[^a-z0-9]+', '-', model_name.lower()).strip('-')
            
            new_dt = nb.dcim.device_types.create(
                manufacturer=manuf_id,
                model=model_name,
                slug=model_slug,
                u_height=0 
            )
            device_type_id = new_dt.id
            netbox_device_types[model_name] = device_type_id
            changes.append(f"[NetBox] Created new Device Type template: {model_name}")

        existing_device = nb.dcim.devices.get(name=ap["hostname"])

        if existing_device:
            print(f" [NetBox] {ap['hostname']} already exists. Updating...")
            existing_device.serial = ap["serial"]
            existing_device.site = site_id 
            existing_device.device_type = device_type_id
            existing_device.save()
            assign_ip_to_netbox_device(nb, existing_device, ap.get("ip_address"))
        else:
            print(f" [NetBox] Creating {ap['hostname']} ({model_name}) at {netbox_site_name}...")
            try:
                new_device = nb.dcim.devices.create( 
                    name=ap["hostname"],
                    site=site_id,
                    device_type=device_type_id,
                    role=DEVICE_ROLE_ID,
                    serial=ap["serial"]
                )
                assign_ip_to_netbox_device(nb, new_device, ap.get("ip_address"))
                changes.append(f"[NetBox] Created new AP: {ap['hostname']} at {netbox_site_name}")
            except pynetbox.RequestError as e:
                print(f"Failed to create {ap['hostname']} in NetBox: {e.error}")

def sync_to_zabbix(aps, changes):
    """Syncs the extracted APs into Zabbix 7, assigning main and site-specific host groups."""
    print("\nSyncing to Zabbix...")
    zapi = ZabbixAPI(ZABBIX_URL)
    zapi.login(api_token=ZABBIX_TOKEN) 

    TEMPLATE_ID = "11018" 
    MAIN_HOST_GROUP_ID = "74"

    ZABBIX_SITE_MAP = {
        "Acalanes": "75",
        "Campolindo": "68",
        "District Office": "70",
        "Del Valle": "67",
        "Service Center": "72",
        "Miramonte": "69",
        "Las Lomas": "71"
    }

    for ap in aps:
        if not ap["hostname"]:
            continue
            
        groups = [{"groupid": MAIN_HOST_GROUP_ID}] 
        
        raw_cambium_site = ap.get("site", "")
        site_group_id = ZABBIX_SITE_MAP.get(raw_cambium_site)
        
        if site_group_id:
            groups.append({"groupid": site_group_id}) 
        else:
            print(f"  [Zabbix Warning] Site '{raw_cambium_site}' not mapped. Assigning to Main Group 74 only.")

        existing_host = zapi.host.get(filter={"host": ap["hostname"]})

        if existing_host:
            print(f" [Zabbix] {ap['hostname']} already monitored. Updating groups/IP...")
            try:
                host_id = existing_host[0]["hostid"]
                interfaces = zapi.hostinterface.get(hostids=host_id)
                if interfaces:
                    interface_id = interfaces[0]["interfaceid"]
                    zapi.hostinterface.update(
                        interfaceid=interface_id, 
                        ip=ap["ip_address"] or "0.0.0.0"
                    )

                zapi.host.update(hostid=host_id, groups=groups)
            except Exception as e:
                print(f"Failed to update {ap['hostname']} in Zabbix: {e}")
        else:
            print(f" [Zabbix] Adding {ap['hostname']}...")
            try:
                zapi.host.create({
                    "host": ap["hostname"],
                    "interfaces": [{
                        "type": 2, 
                        "main": 1,
                        "useip": 1,
                        "ip": ap["ip_address"] or "0.0.0.0", 
                        "dns": "",
                        "port": "161",
                        "details": {
                            "version": 2, 
                            "community": "zabbixv2" 
                        }
                    }],
                    "groups": groups,
                    "templates": [{"templateid": TEMPLATE_ID}]
                })
                changes.append(f"[Zabbix] Added new AP to monitoring: {ap['hostname']}")
            except Exception as e:
                 print(f"Failed to add {ap['hostname']} to Zabbix: {e}")

def cleanup_orphaned_aps(aps, changes):
    """Marks APs as Offline/Disabled if they exist in NetBox/Zabbix but not in Cambium."""
    print("\nChecking for orphaned APs to clean up...")
    
    active_cambium_hostnames = {ap["hostname"] for ap in aps if ap["hostname"]}
    
    # ==========================================
    # NetBox Cleanup
    # ==========================================
    print("  -> Checking NetBox for missing APs...")
    nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
    DEVICE_ROLE_ID = 2 
    
    try:
        netbox_aps = nb.dcim.devices.filter(role_id=DEVICE_ROLE_ID)
        for nb_ap in netbox_aps:
            if nb_ap.name not in active_cambium_hostnames:
                if getattr(nb_ap.status, 'value', '') != 'offline':
                    print(f"    [NetBox] Marking {nb_ap.name} as OFFLINE (Missing from Cambium).")
                    nb_ap.status = 'offline'
                    nb_ap.save()
                    changes.append(f"[NetBox] Marked {nb_ap.name} OFFLINE (Missing from Cambium)")
            else:
                if getattr(nb_ap.status, 'value', '') == 'offline':
                    print(f"    [NetBox] Marking {nb_ap.name} as ACTIVE (Restored in Cambium).")
                    nb_ap.status = 'active'
                    nb_ap.save()
                    changes.append(f"[NetBox] Restored {nb_ap.name} to ACTIVE (Re-appeared in Cambium)")
                    
    except pynetbox.RequestError as e:
        print(f"Failed during NetBox cleanup: {e}")
        
    # ==========================================
    # Zabbix Cleanup
    # ==========================================
    print("  -> Checking Zabbix for missing APs...")
    zapi = ZabbixAPI(ZABBIX_URL)
    zapi.login(api_token=ZABBIX_TOKEN)
    
    ZABBIX_MASTER_GROUP_ID = "74"
    
    try:
        zabbix_aps = zapi.host.get(groupids=ZABBIX_MASTER_GROUP_ID, output=["hostid", "host", "status"])
        for z_ap in zabbix_aps:
            if z_ap["host"] not in active_cambium_hostnames:
                if z_ap["status"] == "0":
                    print(f"    [Zabbix] Disabling monitoring for {z_ap['host']} (Missing from Cambium).")
                    zapi.host.update(hostid=z_ap["hostid"], status=1)
                    changes.append(f"[Zabbix] Disabled monitoring for {z_ap['host']} (Missing from Cambium)")
            else:
                if z_ap["status"] == "1":
                    print(f"    [Zabbix] Re-enabling monitoring for {z_ap['host']} (Restored in Cambium).")
                    zapi.host.update(hostid=z_ap["hostid"], status=0)
                    changes.append(f"[Zabbix] Re-enabled monitoring for {z_ap['host']} (Re-appeared in Cambium)")
                    
    except Exception as e:
         print(f"Failed during Zabbix cleanup: {e}")

# ==========================================
# Main Execution
# ==========================================
if __name__ == "__main__":
    print("Starting integration script...\n")
    
    # Initialize our list to track modifications
    run_changes = []
    
    try:
        # 1. Authenticate
        print("Authenticating with Cambium...", flush=True)
        initial_token, api_server_url = get_access_token(CAMBIUM_BASE_URL, CAMBIUM_CLIENT_ID, CAMBIUM_CLIENT_SECRET)
        api_server_url = api_server_url.rstrip('/')
        
        # 2. Extract & Transform
        my_aps = get_cambium_aps(CAMBIUM_BASE_URL, CAMBIUM_CLIENT_ID, CAMBIUM_CLIENT_SECRET, api_server_url, initial_token)
        
        # 3. Load & Update (pass the tracking list)
        if my_aps:
            sync_to_netbox(my_aps, run_changes)
            sync_to_zabbix(my_aps, run_changes)
            
            # 4. Clean up orphans (pass the tracking list)
            cleanup_orphaned_aps(my_aps, run_changes)
            
            # 5. Report
            send_status_email(run_changes)
            
        print("\nIntegration complete!")
        
    except Exception as err:
        print(f"\nAn error occurred during execution: {err}", file=sys.stderr)
        sys.exit(1)