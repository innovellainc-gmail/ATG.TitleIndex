import os
import re
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE_URL = "https://donaana.nm.publicsearch.us"
TARGET_DOC_ID = "118511438"

# FIX: Target the direct internal HTML partial sub-route used to serve the summary content
TARGET_PARTIAL_URL = f"{BASE_URL}/doc/{TARGET_DOC_ID}/initial"

session = requests.Session()
session.cookies.update({
    "authToken": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e",
    "authToken.sig": "jxPPnMHPIk62NJbem7TFsyYz9xA"
})
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    # Point referer to the base document view to satisfy security checks
    "Referer": f"{BASE_URL}/doc/{TARGET_DOC_ID}"
})

def extract_summary_direct():
    print(f"Fetching direct data segment from: {TARGET_PARTIAL_URL}")
    response = session.get(TARGET_PARTIAL_URL)
    
    if response.status_code != 200:
        print(f"[ERROR] Access denied. Status code: {response.status_code}")
        return
        
    soup = BeautifulSoup(response.text, 'html.parser')
    record_fields = {}
    
    # Isolate all standard table data grid values or definition blocks inside the returned partial layout
    rows = soup.find_all(['tr', 'div', 'dt'])
    
    # Process text layout map lines directly
    text_lines = [line.strip() for line in soup.get_text(separator="\n").split("\n") if line.strip()]
    
    # Neumo structures these text arrays sequentially: [Label, Value, Label, Value]
    for i in range(0, len(text_lines) - 1, 2):
        key = text_lines[i].replace(":", "").strip()
        val = text_lines[i+1].strip()
        if key and val and len(key) < 50:  # Enforce reasonable constraint boundaries on keys
            record_fields[key] = val

    if record_fields:
        df = pd.DataFrame(list(record_fields.items()), columns=['Summary Field Name', 'Extracted Record Value'])
        df.insert(0, 'Document ID', TARGET_DOC_ID)
        
        os.makedirs('generated', exist_ok=True)
        output_path = "generated/extracted_document_summary.xlsx"
        df.to_excel(output_path, index=False)
        print(f"\n=== [SUCCESS] Summary successfully generated at: {output_path} ===")
        for k, v in list(record_fields.items())[:5]:
            print(f"   * {k}: {v}")
    else:
        print("\n[CRITICAL ERROR] The partial layout string returned empty text nodes. Please inspect response.text data.")

extract_summary_direct()






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
