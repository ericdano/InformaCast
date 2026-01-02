import pandas as pd
import requests, json, logging, smtplib, datetime, gam, arrow, os
from pathlib import Path
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from logging.handlers import SysLogHandler
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
    
    all_records.drop(columns=['index'], inplace=True)
    #print(all_records)
    return all_records

def send_status_email(problem_speakers,total_speakers, total_phones,configs):
    html_table_problems = problem_speakers.to_html(index=False, justify='left', classes='red-table')
    html_body = f"""
        <html>
        <head>
        <style>
            table {{ 
                border-collapse: collapse; 
                width: 100%; 
                font-family: sans-serif; 
                margin-bottom: 20px;
            }}
            th {{ 
                background-color: #f2f2f2; 
                font-weight: bold; 
                padding: 8px; 
                border: 1px solid #ddd; 
                color: black;
            }}
            td {{ 
                padding: 8px; 
                border: 1px solid #ddd; 
            }}
            
            /* Target only the table with the 'red-table' class */
            .red-table td {{ 
                color: #FF0000; 
            }}
            
            /* Target only the table with the 'black-table' class */
            .black-table td {{ 
                color: #000000; 
            }}
        </style>
        </head>
        <body>
            <p>There are {total_phones} Cisco Phones and {total_speakers} IP Speakers registered in InformaCast.
            <p>
            <p>Current IP Speakers that are NOT registered:</p>
            {html_table_problems}
            <p><p>
        </body>
        </html>
    """
    s = smtplib.SMTP(configs['SMTPServerAddress'])
    msg = MIMEMultipart()
    msg['Subject'] = str("InformaCast Speaker Statuses "  + datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"))
    msg['From'] = configs['SMTPAddressFrom']
    #msg['To'] = 'alltechnicians@auhsdschools.org'
    msg['To'] = 'edannewitz@auhsdschools.org'
    msg.attach(MIMEText(html_body,'html'))
    s.send_message(msg)

def send_status_email_details(problem_speakers,all_speakers,configs):
    html_table_problems = problem_speakers.to_html(index=False, justify='left', classes='red-table')
    html_all = all_speakers.to_html(index=False, justify='left', classes='black-table')
    html_body = f"""
        <html>
        <head>
        <style>
            table {{ 
                border-collapse: collapse; 
                width: 100%; 
                font-family: sans-serif; 
                margin-bottom: 20px;
            }}
            th {{ 
                background-color: #f2f2f2; 
                font-weight: bold; 
                padding: 8px; 
                border: 1px solid #ddd; 
                color: black;
            }}
            td {{ 
                padding: 8px; 
                border: 1px solid #ddd; 
            }}
            
            /* Target only the table with the 'red-table' class */
            .red-table td {{ 
                color: #FF0000; 
            }}
            
            /* Target only the table with the 'black-table' class */
            .black-table td {{ 
                color: #000000; 
            }}
        </style>
        </head>
        <body>
            <p>Current IP Speakers that are NOT registered:</p>
            {html_table_problems}
            <p><p>
            <p>All IP Speakers that are registered:</p>
            {html_all}
        </body>
        </html>
    """
    s = smtplib.SMTP(configs['SMTPServerAddress'])
    msg = MIMEMultipart()
    msg['Subject'] = str("InformaCast Speaker Statuses "  + datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"))
    msg['From'] = configs['SMTPAddressFrom']
    msg['To'] = 'alltechnicians@auhsdschools.org'
    #msg['To'] = 'edannewitz@auhsdschools.org'
    msg.attach(MIMEText(html_body,'html'))
    s.send_message(msg)

def main():
    global msgbody,thelogger
    configs = getConfigs()
    thelogger = logging.getLogger('MyLogger')
    thelogger.setLevel(logging.DEBUG)
    handler = logging.handlers.SysLogHandler(address = (configs['logserveraddress'],514))
    thelogger.addHandler(handler)
    thelogger.info('Starting InformaCast tester')
    userid = configs['InformaCastUserName']
    passwd = configs['InformaCastPassword']
    token = configs['InformaCastToken']
    url = configs['InformaCastURL'] + '/Devices/?includeAttributes=true'
    all_results = fetch_all_informa_cast_data(url, token, limit=100)
    print(all_results)
    columns_keep =['id','description','attributes.IsRegistered','attributes.Description','attributes.Name','attributes.InformaCastDeviceType','attributes.MACAddress','attributes.Volume']
    results = all_results[columns_keep].copy()
    matches = results[results['attributes.IsRegistered'] == 'false']
    # Count records containing "IP Speaker"
    ip_speaker_count = results['description'].str.contains('IP Speaker', case=False, na=False).sum()
    # Count records containing "Cisco Phone"
    cisco_phone_count = results['description'].str.contains('Cisco IP Phone', case=False, na=False).sum()
    #matches = results
    send_status_email(matches,ip_speaker_count,cisco_phone_count,configs)
#    with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 1000):
#        print(r)
#    r.to_csv('informacasttest.csv',index=False)
    print('Done!')

if __name__ == '__main__':
  main()