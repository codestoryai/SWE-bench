import os.path
import json
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time
import random
from functools import wraps

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def exponential_backoff(max_retries=100, base_delay=2, max_delay=128):
    """
    Decorator that implements exponential backoff for rate limit errors.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for n in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except HttpError as e:
                    # Only retry on rate limit errors (429)
                    if e.resp.status != 429:
                        raise
                    
                    if n == max_retries - 1:  # Last attempt failed
                        raise
                    
                    # Calculate delay with random jitter
                    delay = min(((2 ** n) * base_delay + random.random()), max_delay)
                    print(f"Rate limit hit. Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
            return func(*args, **kwargs)  # Final attempt
        return wrapper
    return decorator

def get_sheets_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("sheets", "v4", credentials=creds)

@exponential_backoff()
def read_sheet_values(spreadsheet_id, range_name):
    service = get_sheets_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    return result.get("values", [])

@exponential_backoff()
def add_column(spreadsheet_id, sheet_id, at_index=0):
    service = get_sheets_service()
    requests = [
        {
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": at_index,
                    "endIndex": at_index + 1,
                },
                "inheritFromBefore": True
            }
        }
    ]
    body = {"requests": requests}
    response = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=body
    ).execute()
    return response

def column_index_to_letter(index):
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord('A')) + result
        index = index // 26 - 1
    return result

@exponential_backoff()
def set_cell_value(spreadsheet_id, sheet_name, row, col_index, value):
    service = get_sheets_service()
    col_letter = column_index_to_letter(col_index)
    cell_range = f"{sheet_name}!{col_letter}{row + 1}"
    body = {"values": [[value]]}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=cell_range,
        valueInputOption="RAW",
        body=body
    ).execute()

def name_column(spreadsheet_id, sheet_name, column_index, column_name):
    # Name the header cell (first row)
    set_cell_value(spreadsheet_id, sheet_name, 0, column_index, column_name)

def find_row_by_instance_id(spreadsheet_id, sheet_name, instance_id):
    # instance_id located in column C (index 2)
    service = get_sheets_service()
    read_range = f"{sheet_name}!C:C"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=read_range
    ).execute()
    values = result.get("values", [])
    for i, row in enumerate(values):
        if row and row[0] == instance_id:
            return i
    return None

def timestamp_to_readable(timestamp):
    # Handle string timestamps by converting to float first
    if isinstance(timestamp, str):
        timestamp = float(timestamp)
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

def get_header_row(spreadsheet_id, sheet_name):
    values = read_sheet_values(spreadsheet_id, f"{sheet_name}!1:1")
    return values[0] if values else []

def ensure_run_columns(spreadsheet_id, sheet_id, sheet_name, run_id):
    """
    Ensures that two columns for the given run_id exist:
    - The main run column (for a simple status)
    - The details column (for JSON metadata)
    
    Returns (run_col_index, run_details_col_index).
    """
    headers = get_header_row(spreadsheet_id, sheet_name)
    run_name = timestamp_to_readable(run_id)
    details_name = f"{run_name} DETAILS"

    # Check if run_name already in headers
    run_col_index = None
    run_details_col_index = None
    for idx, header in enumerate(headers):
        if header == run_name:
            run_col_index = idx
        if header == details_name:
            run_details_col_index = idx

    # If run column not found, add it
    if run_col_index is None:
        run_col_index = len(headers)  # add at end
        add_column(spreadsheet_id, sheet_id, at_index=run_col_index)
        name_column(spreadsheet_id, sheet_name, run_col_index, run_name)
        headers.append(run_name)

    # If details column not found, add it
    if run_details_col_index is None:
        run_details_col_index = len(headers)  # add after run column
        add_column(spreadsheet_id, sheet_id, at_index=run_details_col_index)
        name_column(spreadsheet_id, sheet_name, run_details_col_index, details_name)
        headers.append(details_name)

    return run_col_index, run_details_col_index

def update_instance_run_status(spreadsheet_id, sheet_id, sheet_name, run_id, instance_id, status, metadata):
    """
    Updates the sheet for a given run_id and instance_id:
    - Sets the main run column cell to `status` (e.g. True/False)
    - Sets the details column cell (paired with run column) to JSON serialized `metadata`.
    """
    # Ensure both run columns exist
    run_col_index, run_details_col_index = ensure_run_columns(spreadsheet_id, sheet_id, sheet_name, run_id)

    # Find the instance row
    row_index = find_row_by_instance_id(spreadsheet_id, sheet_name, instance_id)
    if row_index is None:
        print(f"Instance ID {instance_id} not found. Cannot update.")
        return

    # Update main column cell
    set_cell_value(spreadsheet_id, sheet_name, row_index, run_col_index, status)

    # Update details column cell with JSON
    json_data = json.dumps(metadata, indent=2)
    set_cell_value(spreadsheet_id, sheet_name, row_index, run_details_col_index, json_data)
    print(f"Updated instance {instance_id} with status {status} and JSON metadata for run {run_id}.")

def build_instance_id_mapping(spreadsheet_id, sheet_name):
    """
    Builds a mapping of instance IDs to row indices by reading column C once.
    Returns a dictionary of {instance_id: row_index}.
    """
    values = read_sheet_values(spreadsheet_id, f"{sheet_name}!C:C")
    return {row[0]: i for i, row in enumerate(values) if row}

def update_instance_run_resolved_status(spreadsheet_id, sheet_id, sheet_name, column_index, instance_id, status, id_mapping=None):
    """
    Updates the sheet for a given column_index and instance_id:
    - Sets the column cell to `status` (e.g. True/False)
    
    Args:
        id_mapping: Optional dict mapping instance IDs to row indices to avoid repeated reads
    """
    if id_mapping is None:
        row_index = find_row_by_instance_id(spreadsheet_id, sheet_name, instance_id)
    else:
        row_index = id_mapping.get(instance_id)
        
    if row_index is None:
        print(f"Instance ID {instance_id} not found. Cannot update.")
        return
    
    set_cell_value(spreadsheet_id, sheet_name, row_index, column_index, status)
    print(f"Updating instance {instance_id} with status {status} at row {row_index} and column {column_index}")

def append_new_column(spreadsheet_id, sheet_id, sheet_name, column_name):
    headers = get_header_row(spreadsheet_id, sheet_name)
    at_index = len(headers)  # This will put it at the end
    add_column(spreadsheet_id, sheet_id, at_index=at_index)
    name_column(spreadsheet_id, sheet_name, at_index, column_name)
    print(f"Added column {column_name} at index {at_index}")
    return at_index

def main():
    LOG_SHEET_ID = "1W0gxh-NC9Sl01yrlTRPNGvyDQva3_lZPPPMQ2M8IP74"
    SHEET_ID = 280623479
    LOG_SHEET_NAME = "RUNS"

    # Example data
    run_id = 1700000000
    instance_ids = [
        "django__django-10097",
        "django__django-10554",
        "django__django-10880",
        "django__django-10914",
        "django__django-10973",
    ]
    status = True
    instance_results = {
        "success": True,
        "time_taken": 12.5,
        "completion_nodes": 15,
        "total_nodes": 20,
        "mcts_tree_path": ["root", "node3", "node7"],
        "parea_link": "http://example.com/area",
        "timestamp": "2024-12-06 12:34:56",
    }

    # Update the sheet for this run and instance
    try:
        for instance_id in instance_ids:
            update_instance_run_status(
                spreadsheet_id=LOG_SHEET_ID,
                sheet_id=SHEET_ID,
                sheet_name=LOG_SHEET_NAME,
                run_id=run_id,
                instance_id=instance_id,
                status=status,
                metadata=instance_results
            )

        print(f"Sheet url: https://docs.google.com/spreadsheets/d/{LOG_SHEET_ID}/edit#gid={SHEET_ID}")
    except HttpError as err:
        print(err)

if __name__ == "__main__":
    main()
