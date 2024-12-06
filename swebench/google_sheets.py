import os.path
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, make sure to run the auth flow again.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheets_service():
    """Returns an authenticated Sheets API service instance."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("sheets", "v4", credentials=creds)

def read_sheet_values(spreadsheet_id, range_name):
    """Reads and returns values from a given sheet range."""
    service = get_sheets_service()
    sheet = service.spreadsheets()
    result = (
        sheet.values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    return result.get("values", [])

def add_column(spreadsheet_id, sheet_id, at_index=0):
    """
    Inserts a new column at the specified index in a given sheet.
    """
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
    """
    Convert a zero-based column index into an Excel-style column letter (A, B, C, ...).
    """
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord('A')) + result
        index = index // 26 - 1
    return result

def set_cell_value(spreadsheet_id, sheet_name, row, col_index, value):
    """
    Sets the value of a single cell given by row and zero-based column index.
    """
    service = get_sheets_service()
    col_letter = column_index_to_letter(col_index)
    cell_range = f"{sheet_name}!{col_letter}{row + 1}"  # Convert zero-based row to 1-based
    body = {"values": [[value]]}

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=cell_range,
        valueInputOption="RAW",
        body=body
    ).execute()

def name_column(spreadsheet_id, sheet_name, column_index, column_name):
    set_cell_value(spreadsheet_id, sheet_name, 0, column_index, column_name)

def find_row_by_instance_id(spreadsheet_id, sheet_name, instance_id):
    """
    Given an instance_id, find the zero-based row index where it's located in column C.
    """
    # Column C is index 2 zero-based
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
    """
    Converts a UNIX timestamp to a human-readable format for the column name.
    """
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

def get_header_row(spreadsheet_id, sheet_name):
    """
    Returns the header row values (assuming it's the first row of the sheet).
    """
    values = read_sheet_values(spreadsheet_id, f"{sheet_name}!1:1")
    return values[0] if values else []

def ensure_run_column(spreadsheet_id, sheet_id, sheet_name, run_id):
    """
    Ensures that a column for the given run_id exists.
    If not, adds a new column at the end and names it.
    Returns the zero-based column index of the run column.
    """
    headers = get_header_row(spreadsheet_id, sheet_name)
    run_name = timestamp_to_readable(run_id)

    # Check if run_name is already a header
    for idx, header in enumerate(headers):
        if header == run_name:
            return idx

    # If not found, add a new column at the end
    new_col_index = len(headers)  # Append at end
    add_column(spreadsheet_id, sheet_id, at_index=new_col_index)
    name_column(spreadsheet_id, sheet_name, new_col_index, run_name)
    return new_col_index

def update_instance_run_status(spreadsheet_id, sheet_id, sheet_name, run_id, instance_id, status):
    """
    Updates the cell corresponding to the given run_id (column) and instance_id (row) 
    to the specified status (e.g., True/False or a string).
    """
    # Ensure run column exists
    run_col_index = ensure_run_column(spreadsheet_id, sheet_id, sheet_name, run_id)

    # Find instance row
    row_index = find_row_by_instance_id(spreadsheet_id, sheet_name, instance_id)
    if row_index is None:
        print(f"Instance ID {instance_id} not found. Cannot update status.")
        return

    # Update the cell
    set_cell_value(spreadsheet_id, sheet_name, row_index, run_col_index, status)
    print(f"Updated instance {instance_id} with status {status} in run {run_id} column.")

def main():
    LOG_SHEET_ID = "1W0gxh-NC9Sl01yrlTRPNGvyDQva3_lZPPPMQ2M8IP74"
    LOG_SHEET_NAME = "RUNS"
    SHEET_ID = 280623479  # numeric sheet ID for RUNS sheet

    try:
        # Example usage
        run_id = 1700000000  # some UNIX timestamp
        instance_id = "django__django-10097"
        status = True

        # Update instance run status
        update_instance_run_status(LOG_SHEET_ID, SHEET_ID, LOG_SHEET_NAME, run_id, instance_id, status)

        print(f"Sheet url: https://docs.google.com/spreadsheets/d/{LOG_SHEET_ID}/edit#gid={SHEET_ID}")

    except HttpError as err:
        print(err)

if __name__ == "__main__":
    main()
