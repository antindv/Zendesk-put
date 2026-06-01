import azure.functions as func
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


# =============================================================
# 6) ENDPOINTS UTILITAIRES / DEBUG
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