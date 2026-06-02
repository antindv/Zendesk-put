import azure.functions as func
from azure.functions import TimerRequest
import logging
import warnings
import unicodedata
import pandas as pd
import io
import os
import json
import subprocess
import requests
from datetime import datetime, timedelta

from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

#=============================================================
# 0) CONFIGURATION
#=============================================================

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(asctime)s:%(funcName)s: %(message)s")
warnings.filterwarnings("ignore")

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

#=============================================================================
# 1) Download Excel file with IR services information from Azure Blob Storage
#=============================================================================
def load_excel_from_storage():
    account_name = os.environ["STORAGE_ACCOUNT_NAME"]
    container_name = os.environ["STORAGE_CONTAINER"]
    blob_name = os.environ["STORAGE_FILE"]

    # URL of the blob storage, where the excel is stored.
    url = f"https://{account_name}.blob.core.windows.net"

    blob_service_client = BlobServiceClient(
        account_url=url,
        credential=DefaultAzureCredential()
    )

    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=blob_name
    )
    
    logging.info(f"Download of the excel file : {blob_name}")
    blob_bytes = blob_client.download_blob().readall()

    df = pd.read_excel(io.BytesIO(blob_bytes))
    logging.info(f"Excel file has {df.shape[0]} rows")

    return df


#================================================
# 2) Cleaning of Zendesk Tags to do the join
#================================================
def CleanTags(df, col_to_modify):

    def RemoveAccents(input_str):
        normalized_str = unicodedata.normalize("NFKD", input_str)
        return "".join([c for c in normalized_str if unicodedata.category(c) != "Mn"])

    df = df.copy()

    df[col_to_modify] = df[col_to_modify].apply(RemoveAccents)
    df[col_to_modify] = df[col_to_modify].str.lower()
    df[col_to_modify] = df[col_to_modify].str.replace(r"\s+", "_", regex=True)

    forbidden = ["\\(", "\\)", ",", "&amp;", "\\'", "\\+", "\\/", "\\&lt;", "\\&gt;"]
    for f in forbidden:
        df[col_to_modify] = df[col_to_modify].str.replace(f, "_", regex=True)

    return df

#================================================
# 3) Perform a PUT Query on a ticket on Zendesk
#================================================
def put_email_IR(ticket_id, investors, emails_coverage, emails_support, USER_EMAIL, API_TOKEN, ticket_updated, count_updated):
    """
    Function to do a PUT request on Zendesk
    
    :param ticket_id (int): Id of the ticket to change
    :param investors (str): String that correspond to the list of investors
    :param emails_coverage (str): String that correspond to the list of email of IR coverage
    :param emails_support (str): String that correspond to the list of email of IR support
    :param USER_EMAIL (str): Parameter setup in azure to connect to Zendesk
    :param API_TOKEN (str): Parameter setup in azure to connect to Zendesk
    """

    url_put = f"https://antininfrastructurepartners.zendesk.com/api/v2/tickets/{ticket_id}"

    custom_fields_list = []

    custom_fields_list.append({"id": 31177840207133, "value": investors})
    custom_fields_list.append({"id": 31177734633501, "value": emails_coverage})
    custom_fields_list.append({"id": 31177783596061, "value": emails_support})
    custom_fields_list.append({"id": 18212211780893, "value": ""})

    payload = {"ticket": {"custom_fields": custom_fields_list}}

    requests.put(
        url_put,
        auth=(USER_EMAIL, API_TOKEN),
        json=payload,
        verify=False
    )
    ticket_updated.append(ticket_id)
    count_updated += 1

    logging.info(
        f"Update ticket {ticket_id} | investors={investors} | coverage={emails_coverage} | support={emails_support}"
    )
    return ticket_updated, count_updated

#===========================================================================
# 4) Perform a GET Query on Zendesk to extract the list of tickets to change
#===========================================================================
def selection_of_relevant_tickets(FIRST_PAGE, NOW, DELTA_MINUTES, USER_EMAIL, API_TOKEN):
    
    all_possible_statuses = ['solved', 'new', 'closed', 'pending', 'open']
    tickets = ['init_']
    page_nb = FIRST_PAGE
    all_open_tickets = []
    all_modified_tickets = []
    
    while len(tickets) > 0:
        logging.info(f"Extraction of ticket status for page {page_nb}")

        # Extraction of all tickets of the page
        url = f"https://antininfrastructurepartners.zendesk.com/api/v2/tickets.json?include=statuses&page={page_nb}"
        response = requests.get(url, auth=(USER_EMAIL, API_TOKEN), verify=False)
        resp_json = response.json()
        tickets = resp_json['tickets']
        
        # Extraction of all ticket corresponding to the condition
        open_tickets = [tickets[i]['id'] for i in range(len(tickets)) if (tickets[i]['status'] != "solved" and tickets[i]['status'] != "closed")]
        modified_ticket = [tickets[i]['id'] for i in range(len(tickets)) if (NOW - datetime.strptime(tickets[i]['updated_at'], "%Y-%m-%dT%H:%M:%SZ") < timedelta(minutes=DELTA_MINUTES))]
        
        # Population of full list
        all_open_tickets += open_tickets
        all_modified_tickets += modified_ticket

        # Incrementation of the page
        page_nb += 1
    
    tickets_to_keep = list(set(all_open_tickets).intersection(all_modified_tickets))
    return tickets_to_keep


#================================================
# 5) HTTP TRIGGER – TRIGGER THE API OF ZENDESK
#================================================
def run_update_ticket_logic():
    USER_EMAIL = os.environ["ZENDESK_EMAIL"]
    API_TOKEN = os.environ["ZENDESK_TOKEN"]
    DELTA_MINUTES = int(os.environ['LATENCY_LAST_MODIFIED_MINUTES'])
    FIRST_PAGE = int(os.environ['FIRST_PAGE_TO_CHECK'])
    NOW = datetime.today()

    ticket_ids = selection_of_relevant_tickets(FIRST_PAGE, NOW, DELTA_MINUTES, USER_EMAIL, API_TOKEN)

    investor_coverage = load_excel_from_storage()
    investor_coverage_mod = CleanTags(investor_coverage, "InvestorAccount")

    id_email_coverage = 31177734633501
    id_email_support = 31177783596061
    id_investor = 31177840207133
    id_fvi = 20522855900445

    ticket_scanned = []
    ticket_updated = []
    count_updated = 0

    for ticket_id in ticket_ids:
        url_get = (
            f"https://antininfrastructurepartners.zendesk.com/api/v2/tickets/"
            f"{ticket_id}?remove_duplicate_fields=true"
        )

        response = requests.get(url_get, auth=(USER_EMAIL, API_TOKEN), verify=False)

        if response.status_code != 200:
            logging.warning(f"Ticket {ticket_id} not found")
            continue

        data = response.json()
        custom_fields = data["ticket"]["custom_fields"]

        investor_value = next(cf["value"] for cf in custom_fields if cf["id"] == id_investor)
        email_coverage_value = next(cf["value"] for cf in custom_fields if cf["id"] == id_email_coverage)
        email_support_value = next(cf["value"] for cf in custom_fields if cf["id"] == id_email_support)
        fvi_values = next(cf["value"] for cf in custom_fields if cf["id"] == id_fvi)

        if not fvi_values:
            logging.info(f"No Fund, Vehicle, Investor values for ticket {ticket_id}")
            continue

        df_fvi = pd.DataFrame(
            [v.split("___")[-1] for v in fvi_values],
            columns=["InvestorAccount"]
        )

        merged = pd.merge(df_fvi, investor_coverage_mod, on="InvestorAccount", how="left")
        ticket_scanned.append(ticket_id)

        if len(merged) == 0:
            logging.info(f"Investor cannot be found for {ticket_id}.")
            investors = ""
            coverage = ""
            support = ""
        else:
            logging.info(f"Investor found for {ticket_id}.")
            investors = ",".join(merged["Investor"].dropna().drop_duplicates())
            coverage = ",".join(merged["Coverage Person Email"].dropna().drop_duplicates())
            support = ",".join(merged["Coverage Support Email"].dropna().drop_duplicates())

        if (
            investors == investor_value and
            coverage == email_coverage_value and
            support == email_support_value
        ):
            logging.info(f"Ticket {ticket_id} is already up to date.")
        else:
            ticket_updated, count_updated = put_email_IR(
                ticket_id, investors, coverage, support,
                USER_EMAIL, API_TOKEN, ticket_updated, count_updated
            )

    body = {
        "status": "OK",
        "time_run": NOW.strftime("%Y-%m-%d - %H:%M:%S"),
        "tickets_input": ticket_ids,
        "tickets_scanned": ticket_scanned,
        "tickets_updated": ticket_updated,
        "count_updated": count_updated,
    }
    return body


# =============================================================
# 6) MAIN TRIGGERS : HTTP + TIMER
# =============================================================

@app.function_name(name="update_ticket")
@app.route(route="update_ticket", methods=["GET", "POST"])
def update_ticket(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = run_update_ticket_logic()
        return func.HttpResponse(
            json.dumps(body, indent=2),
            mimetype="application/json",
            status_code=200
        )
    except Exception as e:
        logging.error(str(e))
        return func.HttpResponse(f"Error: {e}", status_code=500)



@app.function_name(name="update_ticket_timer")
@app.schedule(
    schedule="0 */5 * * * *",  # toutes les 5 minutes
    arg_name="mytimer",
    run_on_startup=False,
    use_monitor=True
)
def update_ticket_timer(mytimer: func.TimerRequest) -> None:
    logging.info("Timer trigger 'update_ticket_timer' started.")
    try:
        body = run_update_ticket_logic()
        logging.info(f"Timer run finished. {body['count_updated']} tickets updated.")
    except Exception as e:
        logging.error(f"Timer run error: {e}")



# =============================================================
# 7) ENDPOINTS UTILITAIRES / DEBUG
# =============================================================
@app.function_name(name="ping")
@app.route(route="ping", methods=["GET"])
def ping(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("pong", status_code=200)


@app.function_name(name="test_packages")
@app.route(route="test-packages", methods=["GET"])
def test_packages(req: func.HttpRequest) -> func.HttpResponse:
    results = {}

    packages_to_test = {
        "requests": "requests",
        "pandas": "pandas",
        "numpy": "numpy",
        "azure-functions": "azure.functions",
        "azure-identity": "azure.identity",
        "azure-storage-blob": "azure.storage.blob",
        "openpyxl": "openpyxl"
    }

    for display_name, import_path in packages_to_test.items():
        try:
            module = __import__(import_path, fromlist=["*"])
            version = getattr(module, "__version__", "unknown")
            results[display_name] = {
                "status": "OK",
                "version": version
            }
        except Exception as e:
            results[display_name] = {
                "status": "KO",
                "error": str(e)
            }

    # Status global
    all_ok = all(v["status"] == "OK" for v in results.values())

    return func.HttpResponse(
        body=json.dumps(
            {
                "overall_status": "OK" if all_ok else "KO",
                "packages": results
            },
            indent=2
        ),
        mimetype="application/json",
        status_code=200 if all_ok else 500
    )