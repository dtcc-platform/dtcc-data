#!/usr/bin/env python3
"""
Geotorget Nedladdning API Client
Downloads order data from Lantmäteriet's Geotorget API
"""

import requests
import json
import time
import os
from datetime import datetime
from typing import Optional, Dict, List
import base64

class GeotorgetClient:
    def __init__(self, username: str, password: str, order_id: str):
        """
        Initialize the Geotorget client
        
        Args:
            username: Your Geotorget username
            password: Your Geotorget password
            order_id: The order ID to download
        """
        self.base_url = "https://api.lantmateriet.se/geotorget/nedladdning/v1"
        self.order_id = order_id
        self.auth = (username, password)
        self.headers = {
            "Content-Type": "application/json"
        }
        
    def get_order_info(self) -> Dict:
        """Get information about the order"""
        url = f"{self.base_url}/{self.order_id}"
        print(f"Fetching order information for: {self.order_id}")
        
        try:
            response = requests.get(url, auth=self.auth, headers=self.headers)
            response.raise_for_status()
            order_info = response.json()
            
            print(f"Order found:")
            print(f"  Product: {order_info.get('produktnamn', 'N/A')}")
            print(f"  Status: {order_info.get('status', 'N/A')}")
            print(f"  Subscription: {order_info.get('abonnemang', False)}")
            print(f"  Product Type: {order_info.get('produktTyp', 'N/A')}")
            
            return order_info
        except requests.exceptions.RequestException as e:
            print(f"Error fetching order: {e}")
            if hasattr(e.response, 'text'):
                print(f"Response: {e.response.text}")
            raise
            
    def get_latest_delivery(self) -> Optional[Dict]:
        """Check the status of the latest delivery"""
        url = f"{self.base_url}/{self.order_id}/leverans/latest"
        print("\nChecking latest delivery status...")
        
        try:
            response = requests.get(url, auth=self.auth, headers=self.headers)
            
            if response.status_code == 404:
                print("No delivery found for this order")
                return None
                
            response.raise_for_status()
            delivery = response.json()
            
            print(f"Latest delivery found:")
            print(f"  ID: {delivery.get('objektidentitet', 'N/A')}")
            print(f"  Status: {delivery.get('status', 'N/A')}")
            print(f"  Type: {delivery.get('typ', 'N/A')}")
            print(f"  Created: {delivery.get('skapad', 'N/A')}")
            
            if delivery.get('metadata'):
                metadata = delivery['metadata']
                print(f"  Size: {metadata.get('humanReadableSize', 'N/A')}")
                print(f"  Storage time: {metadata.get('lagringstid', 'N/A')} days")
            
            return delivery
        except requests.exceptions.RequestException as e:
            if response.status_code != 404:
                print(f"Error fetching delivery: {e}")
            return None
            
    def start_new_delivery(self, delivery_type: str = "BAS") -> Dict:
        """
        Start a new delivery
        
        Args:
            delivery_type: "BAS" for full data or "FORANDRING" for changes only
        """
        url = f"{self.base_url}/{self.order_id}/leverans"
        params = {"typ": delivery_type}
        
        print(f"\nStarting new {delivery_type} delivery...")
        
        try:
            response = requests.post(url, auth=self.auth, headers=self.headers, params=params)
            response.raise_for_status()
            delivery = response.json()
            
            print(f"New delivery started:")
            print(f"  ID: {delivery.get('objektidentitet', 'N/A')}")
            print(f"  Status: {delivery.get('status', 'N/A')}")
            
            return delivery
        except requests.exceptions.RequestException as e:
            print(f"Error starting delivery: {e}")
            if hasattr(e.response, 'text'):
                print(f"Response: {e.response.text}")
            raise
            
    def wait_for_delivery(self, check_interval: int = 30, max_wait: int = 3600) -> Dict:
        """
        Wait for delivery to complete
        
        Args:
            check_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
        """
        print(f"\nWaiting for delivery to complete...")
        print(f"Checking every {check_interval} seconds...")
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            delivery = self.get_latest_delivery()
            
            if not delivery:
                raise Exception("Delivery disappeared while waiting")
                
            status = delivery.get('status', '')
            
            if status == 'LYCKAD':
                print("✓ Delivery completed successfully!")
                return delivery
            elif status == 'MISSLYCKAD':
                raise Exception("Delivery failed")
            elif status == 'MAKULERAD':
                raise Exception("Delivery was cancelled")
            elif status == 'PÅGÅENDE':
                print(f"  Still processing... (elapsed: {int(time.time() - start_time)}s)")
                time.sleep(check_interval)
            else:
                print(f"  Unknown status: {status}")
                time.sleep(check_interval)
                
        raise Exception(f"Timeout waiting for delivery after {max_wait} seconds")
        
    def get_file_list(self) -> List[Dict]:
        """Get list of files available for download"""
        url = f"{self.base_url}/{self.order_id}/leverans/latest/files"
        print("\nFetching file list...")
        
        try:
            response = requests.get(url, auth=self.auth, headers=self.headers)
            response.raise_for_status()
            files = response.json()
            
            print(f"Found {len(files)} files:")
            for file_info in files:
                print(f"  - {file_info.get('title', 'N/A')} ({file_info.get('displaySize', 'N/A')})")
                
            return files
        except requests.exceptions.RequestException as e:
            print(f"Error fetching file list: {e}")
            raise
            
    def download_file(self, file_path: str, file_name: str, output_dir: str = "downloads"):
        """Download a single file"""
        url = f"{self.base_url}/{self.order_id}{file_path}"
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, file_name)
        
        print(f"Downloading {file_name}...", end="")
        
        try:
            response = requests.get(url, auth=self.auth, stream=True)
            response.raise_for_status()
            
            # Write file in chunks to handle large files
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            print(" ✓")
            return output_path
        except requests.exceptions.RequestException as e:
            print(f" ✗ Error: {e}")
            raise
            
    def download_all_files(self, output_dir: str = "downloads") -> List[str]:
        """Download all files from the latest delivery"""
        files = self.get_file_list()
        
        if not files:
            print("No files to download")
            return []
            
        print(f"\nDownloading {len(files)} files to '{output_dir}' directory...")
        downloaded_files = []
        
        for file_info in files:
            file_path = file_info.get('path', '')
            file_name = file_info.get('title', '')
            
            if file_info.get('type') == 'application/octet-stream':
                try:
                    output_path = self.download_file(file_path, file_name, output_dir)
                    downloaded_files.append(output_path)
                except Exception as e:
                    print(f"Failed to download {file_name}: {e}")
                    
        print(f"\n✓ Downloaded {len(downloaded_files)} files successfully")
        return downloaded_files


def main():
    """Main function to run the download process"""
    
    # Configuration
    ORDER_ID = "b1b82908-55e1-495e-958c-76a201cd2063"
    
    # Get credentials (you should replace these or use environment variables)
    print("=== Geotorget Download Client ===\n")
    
    # You can hardcode credentials for testing (not recommended for production)
    # USERNAME = "your_username"
    # PASSWORD = "your_password"
    
    # Or get from user input
    USERNAME = input("Enter your Geotorget username: ")
    PASSWORD = input("Enter your Geotorget password: ")
    
    # Or get from environment variables (recommended)
    # import os
    # USERNAME = os.environ.get('GEOTORGET_USERNAME')
    # PASSWORD = os.environ.get('GEOTORGET_PASSWORD')
    
    # Initialize client
    client = GeotorgetClient(USERNAME, PASSWORD, ORDER_ID)
    
    try:
        # Step 1: Get order information
        order_info = client.get_order_info()
        
        # Check if order can be downloaded
        if order_info.get('produktTyp') != 'NEDLADDNING':
            print("Error: This order is not a downloadable product")
            return
            
        if order_info.get('status') != 'AKTIV':
            print("Error: Order is not active")
            return
            
        # Step 2: Check latest delivery
        delivery = client.get_latest_delivery()
        
        # Step 3: Determine if we need a new delivery
        if not delivery:
            # No delivery exists, create one
            if not order_info.get('abonnemang'):
                print("Error: Order is not a subscription, cannot create new delivery")
                return
            print("\nNo existing delivery found. Creating new delivery...")
            delivery = client.start_new_delivery("BAS")
            delivery = client.wait_for_delivery()
            
        elif delivery.get('status') == 'PÅGÅENDE':
            # Delivery in progress, wait for it
            delivery = client.wait_for_delivery()
            
        elif delivery.get('status') == 'LYCKAD':
            # Delivery ready
            print("\nExisting successful delivery found")
            
            # Ask if user wants a new delivery (only for subscriptions)
            if order_info.get('abonnemang'):
                choice = input("\nDo you want to download existing delivery or create a new one? (existing/new): ").lower()
                if choice == 'new':
                    delivery_type = input("Delivery type (BAS/FORANDRING) [default: BAS]: ").upper() or "BAS"
                    delivery = client.start_new_delivery(delivery_type)
                    delivery = client.wait_for_delivery()
                    
        else:
            # Delivery failed or cancelled, create new one
            if not order_info.get('abonnemang'):
                print("Error: Order is not a subscription, cannot create new delivery")
                return
            print(f"\nLast delivery status: {delivery.get('status')}. Creating new delivery...")
            delivery = client.start_new_delivery("BAS")
            delivery = client.wait_for_delivery()
            
        # Step 4: Download files
        output_dir = f"downloads_{ORDER_ID}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        downloaded_files = client.download_all_files(output_dir)
        
        if downloaded_files:
            print(f"\nAll files downloaded to: {os.path.abspath(output_dir)}")
            print("\nDownloaded files:")
            for file_path in downloaded_files:
                print(f"  - {os.path.basename(file_path)}")
                
    except Exception as e:
        print(f"\nError: {e}")
        return 1
        
    print("\n=== Download complete ===")
    return 0


if __name__ == "__main__":
    exit(main())
