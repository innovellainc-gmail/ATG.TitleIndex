import os
import re
import time
from playwright.sync_api import sync_playwright

# Define your targeted date range here
START_DATE = "01/01/1978"
END_DATE = "01/05/1978"
DOWNLOAD_DIR = "./downloaded_documents"

# Ensure the download directory exists locally
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def run():
    with sync_playwright() as p:
        # Launch browser. Set headless=False so you can watch the workflow live
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        print("Navigating to Doña Ana County Search...")
        page.goto("https://donaana.nm.publicsearch.us/")
        page.wait_for_load_state("networkidle")
        
        # --- STEP 1: Handle Date Range & Execute Search ---
        print(f"Entering date range: {START_DATE} to {END_DATE}")
        
        # Locate the 'from' and 'to' date input fields
        # Note: Adjust the selectors below if the input elements use specific IDs or names
        date_inputs = page.locator("input[placeholder*='date'], input[aria-label*='Date'], .date-range-input")
        
        if date_inputs.count() >= 2:
            date_inputs.nth(0).fill(START_DATE)
            date_inputs.nth(1).fill(END_DATE)
        else:
            # Fallback: Targets inputs by looking closely at the structure text if explicit selectors are hidden
            page.locator("text=Date Range").locator("..").locator("input").nth(0).fill(START_DATE)
            page.locator("text=to").locator("..").locator("input").fill(END_DATE)
            
        # Click the main Search button
        page.click("button:has-text('Search'), input[type='submit'][value='Search']")
        page.wait_for_load_state("networkidle")
        
        # --- STEP 2: Iterate Results via Clean Index Traversal ---
        print("Waiting for search results container to render...")
        try:
            page.wait_for_selector("div.search-results__results-wrap", timeout=15000)
        except Exception:
            raise RuntimeError("Timed out waiting for the search results container wrapper.")

        TARGET_TOTAL_RECORDS = 50 
        processed_count = 0
        
        print(f"Beginning index-driven traversal for {TARGET_TOTAL_RECORDS} items...")
        
        while processed_count < TARGET_TOTAL_RECORDS:
            ellipsis_selector = "button.a11y-menu__control[data-tourid='menu__control'] >> :visible"
            available_buttons = page.locator(ellipsis_selector)
            
            # If the virtual list hasn't loaded enough items yet, scroll down to force rendering
            if available_buttons.count() <= processed_count:
                print(f"Scrolling to render more rows beyond index {processed_count}...")
                page.evaluate("window.scrollBy(0, 500);")
                time.sleep(1.0)  # Give the framework a clear window to append new DOM elements
                available_buttons = page.locator(ellipsis_selector)
                
                # Safety break if no new records populate after scrolling
                if available_buttons.count() <= processed_count:
                    print("No more unique records discovered after scrolling. Finalizing loop.")
                    break

            print(f"Processing document instrument {processed_count + 1} of {TARGET_TOTAL_RECORDS}...")
            
            # Select the exact target row using your absolute sequential index counter
            target_button = available_buttons.nth(processed_count)
            
            # Bring it strictly into center view so the virtual list framework prioritizes it
            target_button.scroll_into_view_if_needed()
            time.sleep(0.2)
            
            # Open the ellipses dropdown menu
            target_button.click()
            
            # Target the opened list popup menu box
            dropdown_menu = page.locator("ul, [role='menu'], .a11y-menu__list").last
            dropdown_menu.wait_for(state="visible", timeout=5000)
            time.sleep(0.2)
            
            # Select 'Add To Cart' inside that specific menu
            add_to_cart_option = dropdown_menu.locator("li, button, [role='menuitem']").filter(has_text="Add To Cart").first
            add_to_cart_option.wait_for(state="visible", timeout=3000)
            add_to_cart_option.click(force=True)
            
            # Handle the Modal confirmation screen overlay
            print("Handling verification modal overlay popup...")
            modal_container = page.locator("div.modal-shell, div[role='dialog']").last
            modal_container.wait_for(state="visible", timeout=5000)
            
            modal_add_btn = modal_container.locator("button").filter(has_text=re.compile(r"^Add$|^Add To Cart$")).first
            modal_add_btn.wait_for(state="visible", timeout=3000)
            modal_add_btn.click(force=True)
            
            # Monitor the modal wrapper until it is gone from view
            retries = 20
            while modal_container.is_visible() and retries > 0:
                time.sleep(0.2)
                retries -= 1
                
            time.sleep(0.3)
            
            # Increment only when the item is successfully clicked and cleared
            processed_count += 1
            
        print(f"Success! Added {processed_count} unique items to the cart tracker.")
            
        # --- STEP 3: Navigate to Shopping Cart & Checkout ---
        print("All items added. Accessing Header Shopping Cart...")
        # Targets the "Cart 0" link in the website header toolbar
        page.click("a:has-text('Cart'), .header-toolbar >> text=Cart")
        
        print("Waiting for Shopping Cart page to fully load...")
        page.wait_for_selector("button:has-text('Place Your Order')")
        
        print("Submitting checkout order...")
        page.click("button:has-text('Place Your Order')")
        page.wait_for_load_state("networkidle")
        
        # --- STEP 4: Render & Download Local Document PDFs ---
        print("Waiting for download items to populate on screen...")
        download_buttons_selector = "button:has-text('Download PDF'), .btn-download-pdf"
        page.wait_for_selector(download_buttons_selector)
        
        # Pull all matching download buttons on the current post-checkout page
        download_buttons = page.locator(download_buttons_selector)
        cart_items_count = download_buttons.count()
        
        print(f"Ready to download {cart_items_count} files...")
        for j in range(cart_items_count):
            current_btn = download_buttons.nth(j)
            
            # Scrape instrument data from its surrounding parent elements to handle file naming
            # Modify selectors based on how the instrument metadata structure displays next to the buttons
            item_container = current_btn.locator("xpath=./ancestor::*[contains(@class, 'item') or contains(@class, 'row')][1]")
            
            instrument_number = item_container.locator(".instrument-num, .doc-id").text_content()
            document_type = item_container.locator(".doc-type, .instrument-type").text_content()
            
            # Clean string data to remove spaces, slashes, or special file-system characters
            clean_inst = re.sub(r'[^a-zA-Z0-9]', '', instrument_number.strip())
            clean_type = re.sub(r'[^a-zA-Z0-9_]', '', document_type.strip().replace(" ", "_"))
            
            file_name = f"{clean_inst}_{clean_type}.pdf"
            local_save_path = os.path.join(DOWNLOAD_DIR, file_name)
            
            # Use Playwright's download handler tool logic to grab the files seamlessly
            with page.expect_download() as download_info:
                current_btn.click()
                
            download = download_info.value
            download.save_as(local_save_path)
            print(f"[{j+1}/{cart_items_count}] Successfully saved: {file_name}")
            
        print(f"Process complete! Check your local directory: {DOWNLOAD_DIR}")
        browser.close()

if __name__ == "__main__":
    run()
