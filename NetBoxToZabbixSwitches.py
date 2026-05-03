import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import pynetbox
from pyzabbix import ZabbixAPI

# ==========================================
# Configuration & Credentials
# ==========================================
confighome = Path.home() / ".Acalanes" / "Acalanes.json"

try:
    with open(confighome, 'r') as f:
        configs = json.load(f)
        
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
# Script Constants (TODO: Update these)
# ==========================================
NETBOX_SWITCH_ROLE_SLUG = "switch"  

# Map Manufacturers to their specific Zabbix Template IDs
ZABBIX_TEMPLATE_MAP = {
    "HPE": "10250",      # e.g., "10093"
    "D-Link": "10223", # e.g., "10094"
    "Default": "10250" # Fallback template
}

ZABBIX_MASTER_SWITCH_GROUP_ID = "25" # e.g., "80"

# Reusing the site map from your AP script
ZABBIX_SITE_MAP = {
    "Acalanes": "26",
    "Campolindo": "27",
    "District Office": "32",
    "Del Valle": "30",
    "Service Center": "31",
    "Miramonte": "28",
    "Las Lomas": "29"
}

# ==========================================
# Email Reporting Function
# ==========================================
def send_status_email(changes):
    """Sends an email report detailing changes, or a confirmation if no changes occurred."""
    print("\nPreparing status email...")
    smtp_server = configs.get('SMTPServerAddress')
    smtp_port = configs.get('SMTP_Port', 25)
    email_from = configs.get('SMTPAddressFrom')
    email_to = configs.get('SendInfoEmailAddr')

    if not all([smtp_server, email_from, email_to]):
        print("  [Warning] Email configuration incomplete in Acalanes.json. Cannot send report.")
        return

    if changes:
        subject = f"Switch Sync Report: {len(changes)} Changes Detected"
        body = "The NetBox to Zabbix Switch integration script completed a run and made the following updates:\n\n"
        for change in changes:
            body += f" - {change}\n"
    else:
        subject = "Switch Sync Report: No Changes (Routine Check)"
        body = "The NetBox to Zabbix Switch integration script completed a run successfully. All switches are currently in sync. No changes were necessary.\n"
        print("  -> No major changes detected. Sending confirmation email.")
        
    body += "\n\nEnd of Report."

    msg = MIMEMultipart()
    msg['From'] = email_from
    msg['To'] = email_to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, int(smtp_port))
        server.send_message(msg)
        server.quit()
        print(f"  -> Email report successfully sent to {email_to}")
    except Exception as e:
        print(f"  -> Failed to send email: {e}")

# ==========================================
# Core Functions
# ==========================================
def get_netbox_switches():
    """Fetches all active switches, primary IPs, and manufacturer from NetBox."""
    print("\nFetching Switches from NetBox...")
    nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
    
    extracted_switches = []
    try:
        switches = list(nb.dcim.devices.filter(role=NETBOX_SWITCH_ROLE_SLUG))
        
        for switch in switches:
            ip_address = ""
            if switch.primary_ip4:
                ip_address = str(switch.primary_ip4.address).split('/')[0]
                
            # Safely extract manufacturer name
            manufacturer = ""
            if getattr(switch, 'device_type', None) and getattr(switch.device_type, 'manufacturer', None):
                manufacturer = switch.device_type.manufacturer.name
                
            extracted_switches.append({
                "hostname": switch.name,
                "ip_address": ip_address,
                "site": switch.site.name if switch.site else "",
                "manufacturer": manufacturer
            })
            
        print(f"  -> Found {len(extracted_switches)} switches in NetBox.")
        return extracted_switches
        
    except pynetbox.RequestError as e:
        print(f"Failed to fetch switches from NetBox: {e}")
        return []

def sync_to_zabbix(switches, changes):
    """Syncs the extracted NetBox switches into Zabbix with correct templates."""
    print("\nSyncing Switches to Zabbix...")
    zapi = ZabbixAPI(ZABBIX_URL)
    zapi.login(api_token=ZABBIX_TOKEN) 

    for switch in switches:
        if not switch["hostname"]:
            continue
            
        groups = [{"groupid": ZABBIX_MASTER_SWITCH_GROUP_ID}] 
        
        # Determine Site Group
        site_name = switch.get("site", "")
        site_group_id = None
        for key, z_id in ZABBIX_SITE_MAP.items():
            if key in site_name:
                site_group_id = z_id
                break
                
        if site_group_id:
            groups.append({"groupid": site_group_id}) 
        else:
            print(f"  [Zabbix Warning] Site '{site_name}' not mapped for {switch['hostname']}.")

        existing_host = zapi.host.get(filter={"host": switch["hostname"]})
        ip_to_assign = switch["ip_address"] or "0.0.0.0"

        if existing_host:
            # Update IP and Groups if Host already exists
            host_id = existing_host[0]["hostid"]
            
            interfaces = zapi.hostinterface.get(hostids=host_id)
            if interfaces:
                interface_id = interfaces[0]["interfaceid"]
                current_ip = interfaces[0]["ip"]
                if current_ip != ip_to_assign:
                    try:
                        zapi.hostinterface.update(
                            interfaceid=interface_id, 
                            ip=ip_to_assign
                        )
                        print(f" [Zabbix] Updated IP for {switch['hostname']} to {ip_to_assign}")
                        changes.append(f"[Zabbix] Updated IP for switch: {switch['hostname']} -> {ip_to_assign}")
                    except Exception as e:
                        print(f"Failed to update IP for {switch['hostname']}: {e}")

            try:
                zapi.host.update(hostid=host_id, groups=groups)
            except Exception as e:
                print(f"Failed to update groups for {switch['hostname']}: {e}")
                
        else:
            # Determine correct Template based on Manufacturer string
            manuf_name = switch.get("manufacturer", "").upper()
            template_id = ZABBIX_TEMPLATE_MAP["Default"]
            assigned_brand = "Default"
            
            if "HP" in manuf_name or "HEWLETT" in manuf_name:
                template_id = ZABBIX_TEMPLATE_MAP["HPE"]
                assigned_brand = "HPE"
            elif "D-LINK" in manuf_name or "DLINK" in manuf_name:
                template_id = ZABBIX_TEMPLATE_MAP["D-Link"]
                assigned_brand = "D-Link"

            print(f" [Zabbix] Adding new switch: {switch['hostname']} (Detected: {assigned_brand})...")
            try:
                zapi.host.create({
                    "host": switch["hostname"],
                    "interfaces": [{
                        "type": 2, # SNMP
                        "main": 1,
                        "useip": 1,
                        "ip": ip_to_assign, 
                        "dns": "",
                        "port": "161",
                        "details": {
                            "version": 2, 
                            "community": "zabbixv2" 
                        }
                    }],
                    "groups": groups,
                    "templates": [{"templateid": template_id}]
                })
                changes.append(f"[Zabbix] Added new switch to monitoring: {switch['hostname']} ({assigned_brand} Template)")
            except Exception as e:
                 print(f"Failed to add switch {switch['hostname']} to Zabbix: {e}")

def cleanup_orphaned_switches(switches, changes):
    """Marks switches as Disabled in Zabbix if they no longer exist in NetBox."""
    print("\nChecking for orphaned Switches to clean up in Zabbix...")
    
    active_netbox_hostnames = {sw["hostname"] for sw in switches if sw["hostname"]}
    
    zapi = ZabbixAPI(ZABBIX_URL)
    zapi.login(api_token=ZABBIX_TOKEN)
    
    try:
        zabbix_switches = zapi.host.get(groupids=ZABBIX_MASTER_SWITCH_GROUP_ID, output=["hostid", "host", "status"])
        
        for z_sw in zabbix_switches:
            if z_sw["host"] not in active_netbox_hostnames:
                if z_sw["status"] == "0":
                    print(f"    [Zabbix] Disabling monitoring for {z_sw['host']} (Missing from NetBox).")
                    zapi.host.update(hostid=z_sw["hostid"], status=1)
                    changes.append(f"[Zabbix] Disabled monitoring for switch {z_sw['host']} (Removed from NetBox)")
            else:
                if z_sw["status"] == "1":
                    print(f"    [Zabbix] Re-enabling monitoring for {z_sw['host']} (Restored in NetBox).")
                    zapi.host.update(hostid=z_sw["hostid"], status=0)
                    changes.append(f"[Zabbix] Re-enabled monitoring for switch {z_sw['host']} (Re-appeared in NetBox)")
                    
    except Exception as e:
         print(f"Failed during Zabbix cleanup: {e}")

# ==========================================
# Main Execution
# ==========================================
if __name__ == "__main__":
    print("Starting Switch integration script (NetBox -> Zabbix)...\n")
    
    run_changes = []
    
    try:
        netbox_switches = get_netbox_switches()
        
        if netbox_switches:
            sync_to_zabbix(netbox_switches, run_changes)
            cleanup_orphaned_switches(netbox_switches, run_changes)
            
            # Send the email regardless of changes made
            send_status_email(run_changes)
            
        print("\nSwitch integration complete!")
        
    except Exception as err:
        print(f"\nAn error occurred during execution: {err}", file=sys.stderr)
        sys.exit(1)