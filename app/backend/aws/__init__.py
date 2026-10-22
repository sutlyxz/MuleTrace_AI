"""AWS integration package for MuleTrace AI."""
from .bedrock_service import (
    BEDROCK_TOOL_DEFINITIONS,
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    analyze_account_with_bedrock,
    analyze_case_with_bedrock,
    dispatch_engine_tool,
    generate_narrative_report,
    get_bedrock_runtime_client,
    is_boto3_available,
    run_investigation_agent,
)

__all__ = [
    "BEDROCK_TOOL_DEFINITIONS",
    "DEFAULT_MODEL_ID",
    "DEFAULT_REGION",
    "analyze_account_with_bedrock",
    "analyze_case_with_bedrock",
    "dispatch_engine_tool",
    "generate_narrative_report",
    "get_bedrock_runtime_client",
    "is_boto3_available",
    "run_investigation_agent",
]
