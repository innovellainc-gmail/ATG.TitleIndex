import requests
import json

# Base URL for Doña Ana County's specific Neumo instance
BASE_URL = "https://donaana.nm.publicsearch.us"

# Establish a session to persist cookies/tokens automatically
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json"
})

def initialize_portal():
    """Hits the main page to fetch initial session cookies."""
    response = session.get(BASE_URL)
    return response.status_code == 200

def execute_search(search_term):
    """Queries the backend search index endpoint."""
    # Note: Replace this endpoint with the exact URL discovered in your browser's Network Tab
    search_endpoint = f"{BASE_URL}/api/search/query" 
    
    payload = {
        "searchTerm": search_term,
        "departments": ["Real Property"],
        "withOcr": False
    }
    
    try:
        response = session.post(search_endpoint, json=payload)
        if response.status_code == 200:
            return response.json()  # Contains list of documents and documentIds
        else:
            print(f"Search failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"Network error: {e}")
        return None

def download_document(document_id, output_path):
    """Extracts binary stream payload of the document."""
    # Note: Replace this endpoint with the exact URL discovered in your browser's Network Tab
    download_endpoint = f"{BASE_URL}/api/document/download/{document_id}"
    
    response = session.get(download_endpoint, stream=True)
    if response.status_code == 200:
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Successfully extracted document {document_id}")
    else:
        print(f"Extraction blocked: Status Code {response.status_code}")

# Execution Flow
if initialize_portal():
    print("Portal initialized successfully.")
    # data = execute_search("Your Target Name")
