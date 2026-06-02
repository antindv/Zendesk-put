import azure.functions as func
import json

app = func.FunctionApp()

@app.route(route="test_imports", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def test_imports(req: func.HttpRequest) -> func.HttpResponse:
    results = {}

    packages = {
        "warnings": "warnings",
        "os": "os",
        "requests": "requests",
        "pandas": "pandas",
        "numpy": "numpy",
        "openpyxl": "openpyxl",
        "azure_identity": "azure.identity",
        "azure_storage_blob": "azure.storage.blob",
    }

    for name, module_name in packages.items():
        try:
            module = __import__(module_name, fromlist=["*"])
            version = getattr(module, "__version__", "unknown")
            results[name] = {"status": "OK", "version": version}
        except Exception as e:
            results[name] = {"status": "KO", "error": str(e)}

    return func.HttpResponse(
        json.dumps(results, indent=2),
        mimetype="application/json",
        status_code=200
    )