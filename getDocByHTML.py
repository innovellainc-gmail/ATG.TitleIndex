import os
import re
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE_URL = "https://donaana.nm.publicsearch.us"
DOCUMENT_ID = "118950694"  # Example document ID for testing

# Maintain your verified session cookies and session components
session = requests.Session()
session.cookies.update({
    "authToken": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e",
    "authToken.sig": "jxPPnMHPIk62NJbem7TFsyYz9xA"
})
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": f"{BASE_URL}/results?department=RP&keywordSearch=false&recordedDateRange=19000101%2C19800107&searchOcrText=false&searchType=quickSearch&searchValue=doe"
})

def extract_and_export_to_excel(document_id):
    doc_viewer_url = f"{BASE_URL}/doc/{document_id}"
    response = session.get(doc_viewer_url)
    
    if response.status_code != 200:
        print(f"Extraction failed: {response.status_code}")
        return
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    print("=== START DIAGNOSTIC MEMORY SCAN ===")
    
    # Locate every potential embedded database string on the page
    for idx, script in enumerate(soup.find_all('script')):
        script_content = script.string if script.string else ""
        
        # Look for the global state wrapper text assignment
        if "STATE__" in script_content or "CHUNKS__" in script_content:
            print(f"\n[FOUND] Found a state data script at block index position {idx}!")
            
            # Isolate the text boundary sitting immediately after the assignment operator (=)
            try:
                json_match = re.search(r'=\s*(\{.*\});?', script_content)
                if json_match:
                    raw_json = json_match.group(1).strip()
                    # Clean trailing statement semicolons if present
                    if raw_json.endswith(';'):
                        raw_json = raw_json[:-1]
                        
                    data = json.loads(raw_json)
                    print(f" -> Success! Decoded a valid JSON memory dictionary.")
                    print(f" -> Top-level keys found in memory: {list(data.keys())}")
                    
                    # Dump a raw text snapshot to your drive so we can audit the file fields directly
                    debug_file = f"generated_debug_state_dump.json"
                    os.makedirs('generated', exist_ok=True)
                    with open(f"generated/{debug_file}", "w", encoding="utf-8") as df:
                        json.dump(data, df, indent=2)
                    print(f" -> [SAVED] Deep data footprint dumped directly to: generated/{debug_file}")
                    
                    # Let's perform a recursive search loop to find where common keys like 'grantor' or 'book' live
                    print(" -> Scanning for document attributes inside nested objects...")
                    find_document_keys_recursive(data)
                    return
            except Exception as e:
                print(f" -> Failed to decode this specific script block: {e}")
                
    print("\n[CRITICAL] No structural script variables matched. The server may be returning a skeleton container layout.")

def find_document_keys_recursive(item, path="root"):
    """Recursively walks the memory map tree to locate indexing variables."""
    target_keywords = ["grantor", "grantee", "recorded", "instrument", "doc", "reception"]
    
    if isinstance(item, dict):
        # Check if any of our document indices exist at this tier level
        matched_keys = [k for k in item.keys() if any(word in str(k).lower() for word in target_keywords)]
        if matched_keys:
            print(f"    * Found matching property fields at path location: '{path}' -> Keys: {matched_keys}")
            
        for k, v in item.items():
            find_document_keys_recursive(v, f"{path} -> {k}")
            
    elif isinstance(item, list):
        for i, element in enumerate(item):
            find_document_keys_recursive(element, f"{path}[{i}]")

# Run the updated compiler script 
extract_and_export_to_excel(DOCUMENT_ID)


#
# Simple extractor test for Doña Ana County's Neumo Document Viewer
#
# FIX 1: Change the base URL to include the exact Doña Ana subdomain
BASE_URL = "https://donaana.nm.publicsearch.us"
DOCUMENT_ID = "118511438"

session = requests.Session()

# Persist the active authentication tokens you captured
session.cookies.update({
    "authToken": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e",
    "authToken.sig": "jxPPnMHPIk62NJbem7TFsyYz9xA"
})

# FIX 2: Set anti-bot headers and mirror the precise Referer path
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    # Mimic navigating straight out of the search results grid
    "Referer": f"{BASE_URL}/results?department=RP&keywordSearch=false&recordedDateRange=19000101%2C19800107&searchOcrText=false&searchType=quickSearch&searchValue=doe"
})

def extract_summary_panel(document_id):
    doc_viewer_url = f"{BASE_URL}/doc/{document_id}"
    print(f"Fetching document data from: {doc_viewer_url}")
    
    response = session.get(doc_viewer_url)
    
    # Track the response signature
    if response.status_code != 200:
        print(f"Failed to load page. Status code: {response.status_code}")
        return None
        
    soup = BeautifulSoup(response.text, 'html.parser')
    summary_panel = soup.find(id="tabpanel-summary")
    
    if not summary_panel:
        print("Warning: Direct '#tabpanel-summary' selector not found in the HTML.")
        return None
        
    target_div = summary_panel.find('div')
    if target_div:
        return {
            "html": target_div.prettify(),
            "text": target_div.get_text(separator="\n", strip=True)
        }
    return None

# Re-run execution framework
summary_data = extract_summary_panel(DOCUMENT_ID)
if summary_data:
    print("Success! Data parsed safely.")


#
# Get Images from Doña Ana County's Neumo Document Viewer
#
BASE_URL = "https://donaana.nm.publicsearch.us"

# Initialize session with browser footprint and the authentication cookies you provided
session = requests.Session()
session.cookies.update({
    "authToken": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e",
    "authToken.sig": "jxPPnMHPIk62NJbem7TFsyYz9xA"
})
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Referer": "https://donaana.nm.publicsearch.us/"
})

def extract_document_images(document_id):
    """Hits the document landing page to harvest pre-signed image assets."""
    doc_viewer_url = f"{BASE_URL}/doc/{document_id}"
    print(f"Reading document viewer page: {doc_viewer_url}")
    
    # Maintain referer header state context as requested by the server
    session.headers.update({"Referer": doc_viewer_url})
    response = session.get(doc_viewer_url)
    
    if response.status_code != 200:
        print(f"Failed to access document view. Status: {response.status_code}")
        return
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Strategy A: Find all direct image tags matching the file path structure
    image_urls = []
    for img in soup.find_all('img', src=True):
        src = img['src']
        if "/files/documents/" in src:
            # Reconstruct absolute URL paths if necessary
            full_url = src if src.startswith("http") else f"{BASE_URL}{src}"
            image_urls.append(full_url)
            
    # Strategy B: Fallback search if links are buried inside embedded Javascript data lists
    if not image_urls:
        print("Images not found in plain HTML tags. Scanning internal scripts...")
        pattern = r'https://[^\s"\']+/files/documents/[^\s"\']+'
        image_urls = re.findall(pattern, response.text)
        
    # Deduplicate extracted elements
    image_urls = list(set(image_urls))
    print(f"Discovered {len(image_urls)} signed page links for extraction.")
    
    # Execute loop downloads for pages found
    for index, download_link in enumerate(image_urls, start=1):
        print(f"Downloading page {index} asset payload...")
        img_response = session.get(download_link, stream=True)
        
        if img_response.status_code == 200:
            filename = f"document_{document_id}_page_{index}.png"
            with open(filename, 'wb') as file:
                for chunk in img_response.iter_content(chunk_size=8192):
                    file.write(chunk)
            print(f"Saved: {filename}")
        else:
            print(f"Failed page extraction index {index}: Status {img_response.status_code}")

# Test extraction with your verified target document ID
#extract_document_images("118511438")
