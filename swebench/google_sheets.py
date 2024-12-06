import os.path
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
    sheet_id: The numeric sheet ID (not the human-readable name).
    at_index: The index where the new column should be inserted.
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
    For example: 0 -> A, 1 -> B, 2 -> C, ...
    """
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord('A')) + result
        index = index // 26 - 1
    return result

def set_cell_value(spreadsheet_id, sheet_name, row, col_index, value):
    """
    Sets the value of a single cell given by row and zero-based column index.
    Rows and columns here are zero-based, but the Sheets API expects a 1-based row number and a letter-based column.
    """
    service = get_sheets_service()
    col_letter = column_index_to_letter(col_index)
    print(f"Setting cell {col_letter}{row + 1} to {value}")
    cell_range = f"{sheet_name}!{col_letter}{row + 1}"  # Convert zero-based row to 1-based
    body = {
        "values": [[value]]
    }
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
    Given an instance_id, find the row index where it's located in the third column (column C).
    Returns zero-based row index of the matching instance_id, or None if not found.
    """
    service = get_sheets_service()
    # Assume the third column might have a large range; adjust as needed
    read_range = f"{sheet_name}!C:C"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=read_range
    ).execute()
    values = result.get("values", [])
    # values is a list of lists, each sublist is a row
    for i, row in enumerate(values):
        if row and row[0] == instance_id:
            return i
    return None

def main():
    LOG_SHEET_ID = "1W0gxh-NC9Sl01yrlTRPNGvyDQva3_lZPPPMQ2M8IP74"
    # RANGE_NAME = "A1:X254"
    LOG_SHEET_NAME = "RUNS"

    # Sheet ID can be found in the URL of the sheet. It is the number after gid=
    SHEET_ID = "280623479" # the ID of the 'RUN' sheet

    try:
        # Example of adding a column: You need the sheetId (not the name).
        # The sheet ID can be found by checking the Sheets UI or using metadata APIs.
        # For demonstration, we assume a sheetId of 0 (often the first sheet).
        run_column_index = 3

        add_column_response = add_column(LOG_SHEET_ID, sheet_id=SHEET_ID, at_index=run_column_index)
        spreadsheetId = add_column_response["spreadsheetId"]
        print(f"Column added to {SHEET_ID} at index {run_column_index}")

        column_name = "date/month/year"
        name_column(LOG_SHEET_ID, LOG_SHEET_NAME, run_column_index, column_name)

        # Suppose we have an instance_id "django_123" in column A and we want to place a value in the new column.
        instance_id = "django__django-11734"
        row_index = find_row_by_instance_id(LOG_SHEET_ID, LOG_SHEET_NAME, instance_id)

        if row_index is not None:
            # Set a value in this row, newly created column at index 3
            set_cell_value(spreadsheetId, LOG_SHEET_NAME, row_index, run_column_index, "My New Value")
            print(f"Value set for {instance_id} at row {row_index}, column {run_column_index}.")
        else:
            print(f"Instance ID {instance_id} not found.")

        print(f"Sheet url: https://docs.google.com/spreadsheets/d/{spreadsheetId}/edit#gid={SHEET_ID}")

    except HttpError as err:
        print(err)


if __name__ == "__main__":
    main()
