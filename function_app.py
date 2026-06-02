import azure.functions as func
import json
import logging
import warnings
import os
import json
import requests

app = func.FunctionApp()

@app.route(route="calc", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET", "POST"])
def calc(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Calc function triggered.")

    # Récupère a et b depuis la query string
    a = req.params.get("a")
    b = req.params.get("b")

    # Si manquants en query, essaie dans le body JSON
    if not (a and b):
        try:
            body = req.get_json()
        except ValueError:
            body = {}
        a = a or body.get("a")
        b = b or body.get("b")

    if a is None or b is None:
        return _json_response(
            {
                "error": "Missing 'a' or 'b'.",
                "usage": {
                    "query_example": "/api/calc?a=5&b=7",
                    "body_example": {"a": 5, "b": 7},
                },
            },
            status_code=400,
        )

    try:
        a_val = float(a)
        b_val = float(b)
    except ValueError:
        return _json_response(
            {
                "error": "'a' and 'b' must be numbers.",
                "received": {"a": a, "b": b},
            },
            status_code=400,
        )

    result = a_val + b_val

    return _json_response(
        {
            "a": a_val,
            "b": b_val,
            "operation": "addition",
            "result": result,
        }
    )


def _json_response(data, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, ensure_ascii=False),
        status_code=status_code,
        mimetype="application/json",
    )