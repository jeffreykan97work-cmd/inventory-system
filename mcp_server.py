#!/usr/bin/env python3
"""MCP Server for Google Apps Script deployment"""
import json, sys, os
from pathlib import Path

# Fix: don't buffer stdout
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

TOKEN_FILE = os.path.expanduser("~/.hermes/google_token.json")
GS_SRC = Path(r"D:\HERMES_WORK\inventory-system\AppsScript.gs")
HTML_SRC = Path(r"D:\HERMES_WORK\inventory-system\AppsScript.html")

def get_script_service():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE)
    creds.refresh(Request())
    return build("script", "v1", credentials=creds)

def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "apps-script-deployer", "version": "1.0.0"}
        }}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
            {"name": "deploy_webapp", "description": "Update Apps Script code and deploy as web app. Provide the script project ID.", "inputSchema": {
                "type": "object",
                "properties": {
                    "scriptId": {"type": "string", "description": "The Google Apps Script project ID"}
                },
                "required": ["scriptId"]
            }},
            {"name": "create_and_deploy", "description": "Create a NEW Apps Script project, upload code, and deploy as web app.", "inputSchema": {
                "type": "object", "properties": {},
                "required": []
            }}
        ]}}

    if method == "tools/call":
        tool_name = req["params"]["name"]
        args = req["params"].get("arguments", {})

        if tool_name == "deploy_webapp":
            script_id = args["scriptId"]
            try:
                service = get_script_service()
                # Upload code
                gs = GS_SRC.read_text(encoding="utf-8")
                html = HTML_SRC.read_text(encoding="utf-8")
                manifest = json.dumps({"timeZone":"Asia/Macau","dependencies":{},"exceptionLogging":"STACKDRIVER","runtimeVersion":"V8","webapp":{"access":"ANYONE","executeAs":"USER_ACCESSING"}})
                
                service.projects().updateContent(
                    scriptId=script_id,
                    body={"files": [
                        {"name": "appsscript", "type": "JSON", "source": manifest},
                        {"name": "Code", "type": "SERVER_JS", "source": gs},
                        {"name": "Index", "type": "HTML", "source": html}
                    ]}
                ).execute()
                
                ver = service.projects().versions().create(
                    scriptId=script_id, body={"description": "v-auto"}
                ).execute()
                
                service.projects().deployments().create(
                    scriptId=script_id,
                    body={"versionNumber": ver["versionNumber"], "manifestFileName": "appsscript", "description": "Web App"}
                ).execute()
                
                url = f"https://script.google.com/macros/s/{script_id}/exec"
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"✅ Deployed!\nURL: {url}"}]}}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"❌ Error: {e}"}]}}

        if tool_name == "create_and_deploy":
            try:
                service = get_script_service()
                proj = service.projects().create(body={"title": "紀念品倉存系統"}).execute()
                sid = proj["scriptId"]
                
                gs = GS_SRC.read_text(encoding="utf-8")
                html = HTML_SRC.read_text(encoding="utf-8")
                manifest = json.dumps({"timeZone":"Asia/Macau","dependencies":{},"exceptionLogging":"STACKDRIVER","runtimeVersion":"V8","webapp":{"access":"ANYONE","executeAs":"USER_ACCESSING"}})
                
                service.projects().updateContent(
                    scriptId=sid,
                    body={"files": [
                        {"name": "appsscript", "type": "JSON", "source": manifest},
                        {"name": "Code", "type": "SERVER_JS", "source": gs},
                        {"name": "Index", "type": "HTML", "source": html}
                    ]}
                ).execute()
                
                ver = service.projects().versions().create(
                    scriptId=sid, body={"description": "v1"}
                ).execute()
                
                service.projects().deployments().create(
                    scriptId=sid,
                    body={"versionNumber": ver["versionNumber"], "manifestFileName": "appsscript", "description": "Web App"}
                ).execute()
                
                url = f"https://script.google.com/macros/s/{sid}/exec"
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"✅ Created & Deployed!\nScript ID: {sid}\nURL: {url}"}]}}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"❌ Error: {e}"}]}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            print(json.dumps(resp), flush=True)
        except Exception as e:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
            print(json.dumps(err), flush=True)
