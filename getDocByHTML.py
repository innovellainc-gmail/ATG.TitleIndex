import re
import requests
from bs4 import BeautifulSoup

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
extract_document_images("118511438")
