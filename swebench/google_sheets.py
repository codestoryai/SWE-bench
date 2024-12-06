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


def main():
    LOG_SHEET_ID = "1W0gxh-NC9Sl01yrlTRPNGvyDQva3_lZPPPMQ2M8IP74"
    RANGE_NAME = "A1:X254"

    try:
        values = read_sheet_values(LOG_SHEET_ID, RANGE_NAME)
        if not values:
            print("No data found.")
        else:
            for row in values:
                # Safely access row elements, if they exist
                col1 = row[0] if len(row) > 0 else ""
                col5 = row[4] if len(row) > 4 else ""
                print(f"{col1}, {col5}")

        # Example of adding a column: You need the sheetId (not the name).
        # The sheet ID can be found by checking the Sheets UI or using metadata APIs.
        # For demonstration, we assume a sheetId of 0 (often the first sheet).
        # add_column_response = add_column(LOG_SHEET_ID, sheet_id=0, at_index=1)
        # print("Column added:", add_column_response)

    except HttpError as err:
        print(err)


if __name__ == "__main__":
    main()
