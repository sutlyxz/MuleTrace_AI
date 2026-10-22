"""Diagnostic script to verify live connection to AWS Bedrock."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend.config import load_environment, BedrockSettings
from app.backend.aws.bedrock_service import (
    is_boto3_available,
    get_bedrock_runtime_client,
    analyze_case_with_bedrock,
)


def run_diagnostics(target_case: str = 'CASE001', target_account: str | None = None) -> int:
    print("=" * 60)
    print("       MuleTrace AI - AWS Bedrock Connection Test       ")
    print("=" * 60)

    # 1. Load .env
    env = load_environment(PROJECT_ROOT)
    os.environ.update(env)
    print(f"[*] Workspace Root: {PROJECT_ROOT}")

    # 2. Check boto3
    if not is_boto3_available():
        print("\n[!] ERROR: 'boto3' library is not installed in this Python environment.")
        print("    -> Run this command to install: pip install boto3\n")
        return 1
    print("[+] boto3 library: Installed and ready")

    # 3. Check Credentials
    access_key = env.get("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = env.get("AWS_SECRET_ACCESS_KEY", "").strip()
    session_token = env.get("AWS_SESSION_TOKEN", "").strip()
    region = env.get("AWS_REGION", "us-east-1").strip()
    model_id = env.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0").strip()

    if not access_key or not secret_key:
        print("\n[!] ERROR: AWS credentials are missing in your '.env' file.")
        print(f"    Target Region  : {region}")
        print(f"    Target Model   : {model_id}")
        print("\n    Please open the '.env' file in MuleTrace_AI root and fill in:")
        print("      AWS_ACCESS_KEY_ID=...")
        print("      AWS_SECRET_ACCESS_KEY=...")
        print("      AWS_SESSION_TOKEN=... (if using AWS SSO)\n")
        return 1

    if access_key.startswith("ASIA") and not session_token:
        print("\n[!] WARNING: Detected temporary AWS SSO credentials (key starts with ASIA),")
        print("    but 'AWS_SESSION_TOKEN' is missing in .env.")
        print("    AWS SSO credentials require all 3 values (Access Key, Secret Key, Session Token).\n")
        return 1

    masked_key = access_key[:4] + "*" * (len(access_key) - 8) + access_key[-4:] if len(access_key) > 8 else "***"
    print(f"[+] Region         : {region}")
    print(f"[+] Model ID       : {model_id}")
    print(f"[+] Access Key ID  : {masked_key}")
    if session_token:
        print(f"[+] Session Token  : Present (AWS SSO / Temporary STS)")

    # 4. Initialize Client & Invoke
    print("\n[*] Connecting to AWS Bedrock...")
    try:
        client = get_bedrock_runtime_client(
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=session_token or None,
            environment=env,
        )

        print("[*] Sending ping request to Amazon Nova Lite...")
        response = client.converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": "Hello! Reply with 'MuleTrace AI connected to Bedrock Nova Lite successfully!' in English and Thai."}
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 100, "temperature": 0.1},
        )

        message_content = response.get("output", {}).get("message", {}).get("content", [])
        reply_text = message_content[0].get("text", "") if message_content else ""

        print(f"[+] Connection SUCCESSFUL!")
        print(f"[+] Bedrock Model Reply: {reply_text.strip()}")
        usage = response.get("usage", {})
        print(f"[+] Tokens Used: {usage.get('totalTokens', 'N/A')}")

        # 5. AML Case / Account Analysis Test with Bedrock
        if target_account:
            from app.backend.aws.bedrock_service import analyze_account_with_bedrock
            print(f"\n[*] Testing MuleTrace AI Account Analysis ({target_account})...")
            report = analyze_account_with_bedrock(target_account, model_id=model_id, client=client)
            print(f"[+] Account {target_account} Analysis completed successfully!")
        else:
            print(f"\n[*] Testing MuleTrace AI AML Case Analysis ({target_case})...")
            report = analyze_case_with_bedrock(target_case, model_id=model_id, client=client)
            print(f"[+] Case {target_case} Analysis completed successfully!")

        narrative = report.get("ai_narrative", "").strip()
        print("\n" + "=" * 30 + " AI REPORT " + "=" * 30)
        print(narrative)
        print("=" * 71 + "\n")

        print("=" * 60)
        print("   ALL CHECKS PASSED: Your project is connected to AWS Bedrock!  ")
        print("=" * 60)
        return 0

    except Exception as exc:
        error_name = type(exc).__name__
        error_str = str(exc)
        print(f"\n[!] Connection Failed with {error_name}:")
        print(f"    {error_str}")

        if "AccessDeniedException" in error_str or "AccessDenied" in error_name:
            print("\n    [Guide]: IAM User lacks permission or account verification is pending.")
            print("    -> Make sure IAM User has policy 'AmazonBedrockFullAccess'")
        elif "UnrecognizedClientException" in error_str or "InvalidSignatureException" in error_str:
            print("\n    [Guide]: Invalid Access Key or Secret Key.")
            print("    -> Please double-check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
        elif "ResourceNotFoundException" in error_str:
            print(f"\n    [Guide]: Model '{model_id}' was not found in region '{region}'.")
            print("    -> Ensure region is set to us-east-1.")

        print("\n" + "=" * 60)
        return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test AWS Bedrock connection and case analysis")
    parser.add_argument("--case", type=str, default="CASE001", help="Case ID to analyze (default: CASE001)")
    parser.add_argument("--account", type=str, default=None, help="Account ID to analyze (e.g. B782)")
    args = parser.parse_args()
    sys.exit(run_diagnostics(target_case=args.case, target_account=args.account))
