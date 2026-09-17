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
TARGET_URL = f"{BASE_URL}/results?{QUERY_STRING}"

def extract_via_shadow_data():
    print("Launching Chromium orchestration layer...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0"
        )
        
        # Apply your verified login credentials
        context.add_cookies([
            {"name": "authToken", "value": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e", "domain": "donaana.nm.publicsearch.us", "path": "/"},
            {"name": "authToken.sig", "value": "jxPPnMHPIk62NJbem7TFsyYz9xA", "domain": "donaana.nm.publicsearch.us", "path": "/"}
        ])
        
        page = context.new_page()
        print(f"Loading document tracking preview target: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="load")
        
        # Enforce an extended timing window to guarantee complete state data hydration
        print("Allowing background script elements to hydrate state memory...")
        time.sleep(6)
        
        print("Scanning global window space for hidden data structures...")
        
        # Execute an internal memory sweep to pull out the hidden raw index parameters
        raw_metadata = page.evaluate("""
            () => {
                // Sweep common framework layout vectors where Neumo caches metadata
                const rootState = window.__PRELOADED_STATE__ || window.__INITIAL_STATE__;
                if (rootState) return rootState;
                
                // Fallback: Check if there's any data element attributes sitting inside elements
                const summaryPanel = document.querySelector('#tabpanel-summary, [id*="summary"]');
                if (summaryPanel && summaryPanel.dataset) {
                    return Object.assign({}, summaryPanel.dataset);
                }
                
                return null;
            }
        """)
        
        record_fields = {}
        
        if raw_metadata:
            print(" -> [SUCCESS] Located data tree inside application context variables.")
            # Deep search the extracted map to isolate keys like book, page, or instrument
            record_fields = parse_nested_state_tree(raw_metadata, TARGET_DOC_ID)
            
        # Fallback Strategy: Target specific elements via dynamic cell processing
        if not record_fields:
            print(" -> State variables clear. Initiating direct panel element scanner...")
            # Locate all visible text nodes in the summary panel area
            panel_text = page.locator("#tabpanel-summary, .summary-panel, main").first.inner_text()
            lines = [l.strip() for l in panel_text.split("\n") if l.strip()]
            
            # Map standard record fields if they exist sequentially in the layout text stream
            for i in range(0, len(lines) - 1):
                clean_key = lines[i].replace(":", "").strip()
                # Check for standard record index fields
                if any(k in clean_key.lower() for k in ["instrument", "book", "page", "recorded"]):
                    if len(clean_key) < 40:
                        record_fields[clean_key] = lines[i + 1]

        browser.close()

    # Excel output writing phase
    if record_fields:
        df = pd.DataFrame(list(record_fields.items()), columns=['Summary Field Name', 'Extracted Record Value'])
        df.insert(0, 'Document ID', TARGET_DOC_ID)
        
        os.makedirs('generated', exist_ok=True)
        output_path = "generated/extracted_document_summary.xlsx"
        df.to_excel(output_path, index=False)
        print(f"\n=== [FINISHED] Summary sheet written successfully to: {output_path} ===")
        for k, v in list(record_fields.items())[:6]:
            print(f"   * {k}: {v}")
    else:
        print("\n[CRITICAL FAILURE] Document properties missing from page context. Check browser render targets.")

def parse_nested_state_tree(node, target_id):
    """Deep extracts simple flat parameters if the script locates the state array."""
    if isinstance(node, dict):
        current_id = str(node.get('id', '')) or str(node.get('documentId', ''))
        if current_id == target_id:
            # Flatten out atomic tracking elements
            return {str(k): str(v) for k, v in node.items() if isinstance(v, (str, int, float, bool))}
        for k, v in node.items():
            res = parse_nested_state_tree(v, target_id)
            if res: return res
    elif isinstance(node, list):
        for item in node:
            res = parse_nested_state_tree(item, target_id)
            if res: return res
    return None

if __name__ == "__main__":
    extract_via_shadow_data()


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
