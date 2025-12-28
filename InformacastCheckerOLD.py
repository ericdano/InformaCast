import pandas as pd
import requests, json, logging, smtplib, datetime, gam, arrow, os
from pathlib import Path
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from logging.handlers import SysLogHandler


#load configs
def getConfigs():
  # Function to get passwords and API keys for Acalanes Canvas and stuff
  confighome = Path.home() / ".Acalanes" / "Acalanes.json"
  with open(confighome) as f:
    configs = json.load(f)
  return configs

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
    url = configs['InformaCastURL'] + 'IPSpeakers'
    #headers = {'Authorization' : f'Basic {token}'}
    thelogger.info('Logging into InformaCast')
    all_results = []
    headers = {'Authorization' : f'Basic {token}'} 
    while True:
      r = requests.get(url,headers = headers,verify=False)
      
    print(r.text)
    data = r.json()
    df = pd.DataFrame(data)
    print(df.head())
    print(df)
    df.to_csv('informacasttest.csv')

if __name__ == '__main__':
  main()