# Architecture

```text
Browser
  │
  ▼
[Frontend Dashboard] (โฮสต์บน Amazon S3 + CloudFront)
  ├── assets/css/ ── shared styles and case-manager styles
  ├── assets/js/  ── application, cases, API, config, i18n, demo data
  └── sw.js       ── caches local assets; stays at root for scope
          │
          ▼ (HTTPS API Call)
  [Amazon API Gateway]
          │
          ▼
  [AWS Lambda (Risk Engine & Agent)]
          ├── ดึง Dataset / Rules อ้างอิง  ──► [Amazon S3]
          ├── สรุปวิเคราะห์เคสลึกซึ้ง      ──► [Amazon Bedrock]
          └── บันทึก Alert / ผลตรวจ         ──► [Amazon DynamoDB]
```

## Core Components & AWS Responsibilities

### 1. Frontend Hosting (Amazon S3 + CloudFront)
- `app/frontend/` is pure static HTML/CSS/JavaScript with zero build-step overhead.
- Deployable directly to Amazon S3 via `python scripts/deploy_frontend_s3.py`.
- Paired with Amazon CloudFront for HTTPS, low-latency CDN edge delivery, and zero server maintenance.

### 2. API Gateway & Serverless Compute (AWS Lambda)
- `app/backend/aws/lambda_handler.py` provides the serverless API proxy handling:
  - `GET /health`: Engine status
  - `GET /cases`: Investigation case catalog
  - `POST /trace`: Multi-hop transaction fund flow graph tracing
  - `GET /score`: Heuristic AML risk scoring
  - `POST /api/ai/summary`: Synchronous triage combining Amazon Bedrock, S3 audit reports, and DynamoDB alerts
  - Full CORS support for cross-domain calls from S3/CloudFront.

### 3. Case & Dataset Storage (Amazon S3)
- `app/backend/aws/s3_service.py` manages S3 object storage for:
  - Raw and processed transaction CSV datasets.
  - Comprehensive case investigation summaries (`reports/{case_id}/investigation_summary.json`).

### 4. Fast Alert Persistence (Amazon DynamoDB)
- `app/backend/aws/dynamodb_service.py` provides sub-millisecond NoSQL persistence:
  - Persists high-priority alerts with partition key `case_id` on-demand (`PAY_PER_REQUEST`).
  - Automatic type serialization (`float` <-> `Decimal`) for DynamoDB compatibility.

### 5. Generative AML AI Copilot (Amazon Bedrock)
- `app/backend/aws/bedrock_service.py`:
  - Uses Converse API with Amazon Nova Lite or Anthropic Claude.
  - Generates formal bilingual Thai/English compliance narrative reports.
  - Autonomous agent loop with Bedrock Tool Use for multi-hop graph analysis.

## Running Tests
Run Python test suite from the project root:
- `python -m unittest discover -s tests -p "test_*.py"`
