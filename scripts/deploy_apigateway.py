import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import boto3
from app.backend.config import load_environment

env = load_environment(root)

session = boto3.Session(
    aws_access_key_id=env.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=env.get("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=env.get("AWS_SESSION_TOKEN"),
    region_name="us-east-1"
)
ag = session.client("apigatewayv2")
lam = session.client("lambda")

print("1. Checking HTTP API...")
apis = ag.get_apis().get("Items", [])
api = next((a for a in apis if a.get("Name") == "muletrace-serverless-web"), None)
if not api:
    api = ag.create_api(
        Name="muletrace-serverless-web",
        ProtocolType="HTTP",
        CorsConfiguration={
            "AllowOrigins": ["*"],
            "AllowMethods": ["GET", "POST", "OPTIONS"],
            "AllowHeaders": ["*"],
            "MaxAge": 86400,
        }
    )
api_id = api["ApiId"]
api_endpoint = api["ApiEndpoint"]
print(f"   API ID: {api_id} -> {api_endpoint}")

lambda_arn = "arn:aws:lambda:us-east-1:598122632336:function:muletrace-api"

print("2. Checking integration...")
integrations = ag.get_integrations(ApiId=api_id).get("Items", [])
if integrations:
    integration_id = integrations[0]["IntegrationId"]
else:
    integ = ag.create_integration(
        ApiId=api_id,
        IntegrationType="AWS_PROXY",
        IntegrationUri=lambda_arn,
        PayloadFormatVersion="2.0"
    )
    integration_id = integ["IntegrationId"]
print(f"   Integration ID: {integration_id}")

print("3. Checking route ($default)...")
routes = ag.get_routes(ApiId=api_id).get("Items", [])
if not any(r.get("RouteKey") == "$default" for r in routes):
    ag.create_route(
        ApiId=api_id,
        RouteKey="$default",
        Target=f"integrations/{integration_id}"
    )
    print("   Route $default created.")
else:
    print("   Route $default exists.")

print("4. Checking stage ($default)...")
stages = ag.get_stages(ApiId=api_id).get("Items", [])
if not any(s.get("StageName") == "$default" for s in stages):
    ag.create_stage(
        ApiId=api_id,
        StageName="$default",
        AutoDeploy=True
    )
    print("   Stage $default created.")
else:
    print("   Stage $default exists.")

print("5. Granting Lambda permission...")
statement_id = f"apigateway-invoke-{api_id}"
try:
    lam.add_permission(
        FunctionName="muletrace-api",
        StatementId=statement_id,
        Action="lambda:InvokeFunction",
        Principal="apigateway.amazonaws.com",
        SourceArn=f"arn:aws:execute-api:us-east-1:598122632336:{api_id}/*/*"
    )
    print("   Permission granted.")
except Exception as e:
    if "ResourceConflictException" in str(e):
        print("   Permission statement already exists.")
    else:
        print("   Permission error/note:", e)

print("\n" + "="*60)
print(f"   SERVERLESS MOBILE WEB URL: {api_endpoint}/login.html")
print("="*60)