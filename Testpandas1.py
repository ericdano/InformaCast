from pathlib import Path
import pandas as pd
import requests, json, os


def get_inventory_df():
    # Example: Loading data into a DataFrame
    # You could also use: df = pd.read_csv('/path/to/data.csv')
    data = {
        "name": ["WebSrv-01", "DB-01", "App-01"],
        "ip": ["192.168.1.10", "192.168.1.20", "192.168.1.30"],
        "status": [1, 0, 1],
        "mac": ["00:1A:2B:3C:4D:5E", "00:1A:2B:3C:4D:5F", "00:1A:2B:3C:4D:60"],
        "id": [101, 102, 103]
    }
    return pd.DataFrame(data)
if __name__ == '__main__':
    print(get_inventory_df())
