import os
import time
import re
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
from playwright.sync_api import sync_playwright

BASE_URL = "https://donaana.nm.publicsearch.us"
TARGET_DOC_ID = "118511438" #Instrument Number: 723762

# FIX: Target the direct internal HTML partial sub-route used to serve the summary content
# 1. Target the internal core API data endpoint instead of layout views
API_DATA_URL = f"{BASE_URL}/api/document/{TARGET_DOC_ID}"

# We go back to the ONLY page that holds raw index data: the search results page
# Reconstruct the exact search results routing path used by your browser
QUERY_STRING = "department=RP&keywordSearch=false&recordedDateRange=19000101%2C19800107&searchOcrText=false&searchType=quickSearch&searchValue=doe"
# Force the browser directly to the explicit document profile view path
TARGET_URL = f"{BASE_URL}/doc/{TARGET_DOC_ID}"

def extract_strict_schema_fields():
    print("Launching Chromium browser automation framework...")
    
    # 1. Hardcode your exact 34 required title index fields as a clean schema framework
    required_schema = [
        "Legal Description", "County", "Grantor", "Grantee", "Volume", "Page", 
        "Instrument Date", "Instrument Number", "Section", "Township", 
        "Range or Block (S-T-R)", "Abstract Number", "Survey", "Quarter Call", 
        "Book Type", "Instrument Type", "Instrument Type Alias", "Subdivision", 
        "Subdivision Alias", "Lot (Sub)", "Block (Sub)", "Acres", "File Date", 
        "Instrument Type Group", "Prior Reference Instrument Number", 
        "Prior Reference Volume", "Prior Reference Page", "State", "APN #", 
        "Street Address", "City (Address)", "State (Address)", "Zip (Address)", 
        "Tract Description (City Block)"
    ]
    
    # Initialize the results table with empty values for every single field
    extracted_record = {field: "" for field in required_schema}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0"
        )
        
        # Inject your refreshed persistent authorization session parameters
        context.add_cookies([
            {"name": "authToken", "value": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e", "domain": "donaana.nm.publicsearch.us", "path": "/"},
            {"name": "authToken.sig", "value": "jxPPnMHPIk62NJbem7TFsyYz9xA", "domain": "donaana.nm.publicsearch.us", "path": "/"}
        ])
        
        page = context.new_page()
        print(f"Loading document tracking preview target layout: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="networkidle")
        
        # Enforce an extended wait block to let the client-side JavaScript load the summary fields
        print("Waiting 6 seconds for dynamic data tables to render on screen...")
        time.sleep(6)
        
        print("Beginning targeted schema property parsing...")
        
        # 2. Extract every layout text block from the body container
        body_text = page.locator("body").inner_text()
        lines = [line.strip() for line in body_text.split("\n") if line.strip()]
        
        # 3. Match keys based on text proximity rules
        for field in required_schema:
            for idx, line in enumerate(lines):
                # Normalize line formatting to verify clean label text match strings
                clean_line = line.replace(":", "").strip().lower()
                
                if clean_line == field.lower():
                    # Safety check: Grab the text block sitting directly below the matched label string
                    if idx + 1 < len(lines):
                        candidate_value = lines[idx + 1]
                        
                        # Ensure the captured row isn't just another core schema tracking block label name
                        if not any(f.lower() == candidate_value.replace(":", "").strip().lower() for f in required_schema):
                            extracted_record[field] = candidate_value
                            break
                            
        browser.close()

    # 4. Stream out the complete matrix structure directly to your verification spreadsheet
    if any(v != "" for v in extracted_record.values()):
        # Convert the dictionary layout smoothly into separate Excel rows
        df = pd.DataFrame(list(extracted_record.items()), columns=['Summary Field Name', 'Extracted Record Value'])
        df.insert(0, 'Document ID', TARGET_DOC_ID)
        
        os.makedirs('generated', exist_ok=True)
        output_path = "generated/extracted_document_summary.xlsx"
        df.to_excel(output_path, index=False)
        
        print(f"\n=== [FINISHED] Compiled Excel sheet created safely at: {output_path} ===")
        print(f"Total rows written: {len(df)}")
        for k, v in list(extracted_record.items())[:8]:
            print(f"   * {k}: {'[EMPTY]' if v == '' else v}")
    else:
        print("\n[CRITICAL ERROR] The data extraction pipeline returned a completely empty mapping sheet.")
        print("Please log into your web browser and ensure your auth tokens haven't rolled over.")

if __name__ == "__main__":
    extract_strict_schema_fields()




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
