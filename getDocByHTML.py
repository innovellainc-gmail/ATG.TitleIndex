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

def extract_with_headless_browser():
    print("Launching headless browser orchestration engine...")
    
    with sync_playwright() as p:
        # Launch an invisible Chromium instance to process the code
        browser = p.chromium.launch(headless=True)
        
        # Build a native context container with your specific browser signature
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0"
        )
        
        # Inject your active login validation credentials directly into the browser context memory
        context.add_cookies([
            {"name": "authToken", "value": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e", "domain": "donaana.nm.publicsearch.us", "path": "/"},
            {"name": "authToken.sig", "value": "jxPPnMHPIk62NJbem7TFsyYz9xA", "domain": "donaana.nm.publicsearch.us", "path": "/"}
        ])
        
        page = context.new_page()
        
        print(f"Navigating to results index: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="networkidle")
        
        # Wait a brief moment for the React component framework to finish virtual rendering
        time.sleep(3)
        
        # If the page loads, click directly on the table element row containing your Target Document ID
        # This triggers the "Document Preview" sliding state layout panel inside the browser window view
        print(f"Attempting to click result row matching ID: {TARGET_DOC_ID}")
        target_row_selector = f"[data-id='{TARGET_DOC_ID}'], [id*='{TARGET_DOC_ID}'], tr:has-text('{TARGET_DOC_ID}')"
        
        try:
            page.locator(target_row_selector).first.click(timeout=5000)
            print(" -> Click registered. Waiting for Summary Panel text fields to draw...")
            time.sleep(2)
        except Exception:
            print(" -> Row selector not immediately clickable. Proceeding to direct viewport content check...")

        # Directly navigate the browser frame to the explicit preview viewer layout if necessary
        page.goto(f"{BASE_URL}/doc/{TARGET_DOC_ID}", wait_until="networkidle")
        time.sleep(3)

        print("Isolating summary sheet components...")
        record_fields = {}
        
        # Extract data directly from the dynamic text elements on the screen
        # We target the key-value labels inside the dynamically rendered panel
        labels = page.locator("dt, label, .summary-label, td:first-child").all_text_contents()
        values = page.locator("dd, span, .summary-value, td:nth-child(2)").all_text_contents()
        
        # If generic text arrays populate, map them together into clear structural entries
        if labels and values:
            for lbl, val in zip(labels, values):
                clean_k = lbl.replace(":", "").strip()
                clean_v = val.strip()
                if clean_k and clean_v and len(clean_k) < 50:
                    record_fields[clean_k] = clean_v

        # Fallback Strategy: Sweep plain inner text layouts if custom element selectors are obfuscated
        if not record_fields:
            print("Dynamic elements hidden. Extracting deep text string lines...")
            raw_text = page.locator("body").inner_text()
            lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
            
            target_anchors = ["Instrument Number", "Number of Pages", "Recorded Date", "Book", "Page"]
            for anchor in target_anchors:
                for idx, line in enumerate(lines):
                    if anchor.lower() in line.lower() and idx + 1 < len(lines):
                        record_fields[anchor] = lines[idx + 1]
                        break

        # Shut down the background automated browser session
        browser.close()

    # Stream out the captured metrics directly to your Excel template workbook
    if record_fields:
        df = pd.DataFrame(list(record_fields.items()), columns=['Summary Field Name', 'Extracted Record Value'])
        df.insert(0, 'Document ID', TARGET_DOC_ID)
        
        os.makedirs('generated', exist_ok=True)
        output_path = "generated/extracted_document_summary.xlsx"
        df.to_excel(output_path, index=False)
        print(f"\n=== [SUCCESS] Summary file successfully generated at: {output_path} ===")
        for k, v in list(record_fields.items())[:6]:
            print(f"   * {k}: {v}")
    else:
        print("\n[CRITICAL ERROR] Automated rendering returned an empty data map. Please confirm your account access rights.")

if __name__ == "__main__":
    extract_with_headless_browser()


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
