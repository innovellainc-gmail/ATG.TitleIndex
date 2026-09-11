# Doña Ana County Records Indexer

Streamlit application that searches the Doña Ana County Public Records portal with Playwright and stores indexed metadata in SQLite.

## Setup

From `c:\LocalDrive\Repos`:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

The app creates `dona_ana_records.db` and `document_images\` in the working directory on first launch.

Optional environment variables:

- `DONA_ANA_DATABASE`: alternate SQLite database path.
- `DONA_ANA_DOCUMENTS`: alternate document storage directory.

The browser runs headlessly. The sidebar controls the date range, department, and grantor/grantee term. Results are written as they are processed and can be searched or downloaded as CSV from the main view.