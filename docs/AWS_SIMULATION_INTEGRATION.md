# MuleTrace AI — AWS Simulation Integration Guide

This guide is for the AWS Infrastructure Engineer connecting the MuleTrace AI **Transaction Simulation** feature to AWS serverless services.

---

## 1. Architectural Overview

```
[ Frontend: Overview UI ]
        │  Click "Simulate Transactions"
        ▼
[ Backend Simulation API: POST /api/simulation/run ]
        │  (Validates session + generates 21-transaction batch)
        ▼
[ Amazon EventBridge Event Bus: 'muletrace-transactions' ]
        │  Rule: { "source": ["muletrace.simulation"], "detail-type": ["TransactionEvent"] }
        ▼
[ AWS Lambda: Risk Detection Function ]
        │  Fetches AML rules configuration from Amazon S3
        │  Evaluates: Multiple Incoming, Rapid Outgoing, High-Value Transfer
        ▼
[ Amazon DynamoDB: Cases & Alerts Tables ]
        │  (Only flagged risk findings create cases; normal transactions do not)
        ▼
[ Frontend: Case Queue Dashboard (Polled or refreshed via /api/cases) ]
```

---

## 2. Environment Variables Configuration

Set the following environment variables in the backend environment (ECS task definition, Lambda, or App Runner):

| Variable Name | Default Value | Description |
|---|---|---|
| `MULETRACE_SIMULATION_TRANSPORT` | `local` (or `eventbridge` on AWS) | Selects the active transport adapter (`local` or `eventbridge`). |
| `EVENTBRIDGE_BUS_NAME` | `muletrace-transactions` | Name of the custom Amazon EventBridge Event Bus. |
| `EVENTBRIDGE_SOURCE` | `muletrace.simulation` | The `Source` field for emitted EventBridge events. |
| `EVENTBRIDGE_DETAIL_TYPE` | `TransactionEvent` | The `DetailType` field for emitted EventBridge events. |
| `AWS_REGION` | `us-east-1` | Target AWS region. |

---

## 3. EventBridge Event Envelope & Payload Schema

### Event Envelope
```json
{
  "Time": "2026-10-24T10:00:00Z",
  "Source": "muletrace.simulation",
  "Resources": [
    "muletrace:run:sim_20261024_093000_a1b2c3d4"
  ],
  "DetailType": "TransactionEvent",
  "Detail": "{...JSON String of Event Payload...}",
  "EventBusName": "muletrace-transactions"
}
```

### Event Payload Schema (`Detail` JSON object)
Every simulation event matches the canonical `transactions.csv` schema and includes deduplication metadata:

```json
{
  "transaction_id": "TXSIM_A1B2C3D4_01",
  "timestamp": "2026-10-24 09:30:00",
  "source_account": "N012",
  "target_account": "N005",
  "amount": 1200.0,
  "scenario": "normal",
  "is_suspicious": false,
  "event_id": "EVT_A1B2C3D4_01",
  "simulation_run_id": "sim_20261024_093000_a1b2c3d4",
  "is_simulated": true,
  "sequence_number": 1,
  "total_in_batch": 20,
  "seed": 1827364590,
  "base_timestamp": "2026-10-24T09:30:00+00:00",
  "generator_version": "2.0.0-dynamic",
  "dataset_ref": "accounts.csv:v1",
  "is_debug": false
}
```

---

## 4. Idempotency, Deduplication & Safety Isolation

EventBridge and Lambda operate with **at-least-once delivery**. Out-of-order delivery and duplicate transmissions can occur.

To ensure idempotent and safe processing in the Risk Detection Lambda:
1. **Deduplication Key**: Construct a unique key using `simulation_run_id` + `transaction_id`:
   ```python
   dedup_key = f"{event['simulation_run_id']}#{event['transaction_id']}"
   ```
2. **Conditional Put in DynamoDB**: Write processed events or intermediate account windows using a condition expression:
   ```python
   ConditionExpression="attribute_not_exists(dedup_key)"
   ```
3. **Chronological Sorting**: The simulation batch uses timestamps relative to `base_timestamp` spanning ~45-55 minutes. The Risk Detection Lambda should evaluate windows based on event `timestamp`, not the Lambda execution arrival time (`Time`).
4. **Debug Isolation Guard**: If `is_debug` is `true` (e.g. debugging via explicit seed/timestamp), the backend blocks dispatch to production EventBridge bus by default (`allow_debug_dispatch=False`) to avoid contaminating production risk alerts.

---

## 5. Event Batch Composition (Exactly 20 Dynamic Transactions)

Each run emits exactly 20 dynamic transactions interleaved naturally:
- **6 Normal Background Transactions**: Routine transfers between accounts randomly drawn from the valid normal pool.
- **5 Historical Baseline Transactions**: Account transfers establishing a dynamic median profile for historical baseline analysis.
- **5 Multiple Incoming Transactions**: Five distinct smurfing accounts transfer into a designated mule account within <= 10 minutes. (Exercises **Rule 1: Multiple Incoming**).
- **1 Rapid Outgoing Transaction**: Mule account transfers funds to a relay account within 120 seconds of receiving funds. (Exercises **Rule 2: Rapid Outgoing**).
- **1 High-Value Baseline Anomaly**: Baseline account transfers >= 3x its historical median. (Exercises **Rule 3: Dynamic Historical Baseline**).
- **1 High-Value Fallback**: Fallback account transfers >= 50,000 THB with history < 5. (Exercises **Rule 3: Fallback Threshold**).
- **1 Multi-hop Continuation Transaction**: Relay account transfers to a destination account. (Connects money trail `Smurf -> Mule -> Relay -> Dest` for the **AI Multi-hop Money Tracing Tool** without generating false alerts).

---

## 6. IAM Permissions Required

The execution role running the MuleTrace backend API requires:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEventBridgePutEvents",
      "Effect": "Allow",
      "Action": [
        "events:PutEvents"
      ],
      "Resource": "arn:aws:events:us-east-1:*:event-bus/muletrace-transactions"
    }
  ]
}
```

---

## 7. Performance & Latency Target

- **Target**: One click → Cases visible in Case Queue within 10 seconds.
- **Backend submission**: Exactly 20 events are batched into 2 `put_events` calls (chunks of 10), completing in < 100ms.
- **Lambda processing**: Keep risk detection Lambda invocation lightweight. Do not block case creation on Amazon Bedrock narrative generation; allow Bedrock AI explanations to be generated asynchronously or on-demand when the analyst inspects the case.
