import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import boto3
from app.backend.config import load_environment

env = load_environment(root)

zip_file_path = root / "build" / "muletrace_lambda.zip"
if not zip_file_path.exists():
    raise FileNotFoundError(f"Package not found at {zip_file_path}")

print(f"Reading package: {zip_file_path} ({zip_file_path.stat().st_size} bytes)...")
with open(zip_file_path, "rb") as f:
    zip_bytes = f.read()

session = boto3.Session(
    aws_access_key_id=env.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=env.get("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=env.get("AWS_SESSION_TOKEN"),
    region_name=env.get("AWS_REGION", "us-east-1"),
)

sts = session.client("sts")
identity = sts.get_caller_identity()
print(f"Authenticated AWS Account: {identity.get('Account')}")
print(f"IAM Identity ARN: {identity.get('Arn')}")

lam = session.client("lambda")
function_name = "muletrace-api"

print(f"Uploading updated code package to Lambda: {function_name}...")
res = lam.update_function_code(
    FunctionName=function_name,
    ZipFile=zip_bytes,
)
print(f"Function Code Update Triggered: Version {res.get('Version')}, CodeSha256: {res.get('CodeSha256')}")

print("Waiting for Lambda update to settle...")
for _ in range(30):
    cfg = lam.get_function_configuration(FunctionName=function_name)
    status = cfg.get("LastUpdateStatus", "Successful")
    print(f"  Status: {status}")
    if status in ("Successful", "Failed"):
        break
    time.sleep(2)

print("\nDeployment complete!")
print("Live Cloud Web URL: https://as3teq2qp5.execute-api.us-east-1.amazonaws.com/login.html")
print("Admin Portal URL:   https://as3teq2qp5.execute-api.us-east-1.amazonaws.com/admin.html")
