import os
import re
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd

# Hardcoded target variables from your verified browser network footprint
BASE_URL = "https://donaana.nm.publicsearch.us"
TARGET_DOC_ID = "118511438" # This is instrument number 723762

# 1. Manually build the EXACT query string verified by your browser console
# Note the explicit %2C URL encoding for the date range split parameter
QUERY_STRING = "department=RP&keywordSearch=false&recordedDateRange=19000101%2C19800107&searchOcrText=false&searchType=quickSearch&searchValue=doe"
TARGET_RESULTS_URL = f"{BASE_URL}/results?{QUERY_STRING}"

session = requests.Session()

# Inject your verified persistent browser authentication session tokens
session.cookies.update({
    "authToken": "25af87ab-dbfc-4a04-818d-4a1b12c0cd6e",
    "authToken.sig": "jxPPnMHPIk62NJbem7TFsyYz9xA"
})

# Update complete anti-bot headers and add the correct base Referer pointer
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    # FIX: Point the referrer to the main landing page to mimic an authentic user click path
#    "Referer": f"{BASE_URL}/results?department=RP&keywordSearch=false&recordedDateRange=19000101%2C19800107&searchOcrText=false&searchType=quickSearch&searchValue=doe"
#    "Referer": f"{BASE_URL}/"
})

def execute_final_extraction():
    print(f"Requesting hardcoded results index page:\n{TARGET_RESULTS_URL}\n")
    response = session.get(TARGET_RESULTS_URL)
    
    if response.status_code != 200:
        print(f"[CRITICAL] Access blocked by firewall. Status code: {response.status_code}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    record_fields = {}

    print("Analyzing page body layout structure...")

    # --- PHASE 1: Scan for the hidden global JSON state tree ---
    for script in soup.find_all('script'):
        script_content = script.string if script.string else ""
        if "STATE__" in script_content or "results" in script_content:
            try:
                # Find any nested JSON dictionary object configuration strings
                json_match = re.search(r'(\{.*\})', script_content)
                if json_match:
                    state_data = json.loads(json_match.group(1))
                    
                    # Recursively walk the decrypted JSON memory tree to grab the target document ID
                    found_dict = search_json_tree_for_doc(state_data, TARGET_DOC_ID)
                    if found_dict:
                        print(" -> [SUCCESS] Isolated target document dictionary from internal JavaScript state memory!")
                        record_fields = {str(k): str(v) for k, v in found_dict.items() if v is not None}
                        break
            except Exception:
                pass

    # --- PHASE 2: Fallback to a deep text container sweep if scripts are clean ---
    if not record_fields:
        print(" -> Data state empty. Initiating fallback deep HTML text block sweep...")
        
        # Pull every text line from the document container to see if the ID is listed anywhere
        all_text_blocks = soup.get_text(separator="\n").split("\n")
        clean_blocks = [b.strip() for b in all_text_blocks if b.strip()]
        
        # If the targeted Document ID string exists in the page, grab the nearby strings as a fallback
        if any(TARGET_DOC_ID in block for block in clean_blocks):
            print(f" -> [SUCCESS] Located raw string entries matching ID '{TARGET_DOC_ID}' on the page.")
            for idx, chunk in enumerate(clean_blocks):
                if TARGET_DOC_ID in chunk:
                    # Capture a window of 10 text metrics before and after the matched ID line
                    start = max(0, idx - 4)
                    end = min(len(clean_blocks), idx + 10)
                    for fallback_idx, i in enumerate(range(start, end)):
                        record_fields[f"Context_Line_{fallback_idx}"] = clean_blocks[i]
                    break

    # --- PHASE 3: Compile and write output directly to your Excel file ---
    if record_fields:
        df = pd.DataFrame(list(record_fields.items()), columns=['Summary Field Name', 'Extracted Record Value'])
        df.insert(0, 'Document ID', TARGET_DOC_ID)
        
        os.makedirs('generated', exist_ok=True)
        output_path = "generated/extracted_document_summary.xlsx"
        df.to_excel(output_path, index=False)
        print(f"\n=== [FINISHED] Summary file written safely to: {output_path} ===")
        for k, v in list(record_fields.items())[:5]: # Print the first 5 variables to check
            print(f"   * {k}: {v}")
    else:
        print(f"\n[CRITICAL ERROR] Extraction returned an empty layout. Please open the browser, perform the search 'doe', and verify if your cookies have rolled over.")

def search_json_tree_for_doc(element, target_id):
    """Deep search helper to find an object containing our target ID string."""
    if isinstance(element, dict):
        # Check if this specific object level represents our target record card block
        id_val = str(element.get('id', '')) or str(element.get('documentId', ''))
        if id_val == target_id:
            return element
        for key, val in element.items():
            result = search_json_tree_for_doc(val, target_id)
            if result:
                return result
    elif isinstance(element, list):
        for item in element:
            result = search_json_tree_for_doc(item, target_id)
            if result:
                return result
    return None

# Execute the final compilation sequence
execute_final_extraction()






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
