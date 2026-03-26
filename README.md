# Drive-Thru Voice Ordering

A drive-thru ordering app where customers place food orders using natural voice interaction powered by Amazon Nova Sonic via the Strands Agents SDK. Browse the menu visually, talk to an AI drive-thru attendant, and place your order hands-free.

## Architecture

```
Browser (React SPA)
  ├── CloudFront → S3 (static hosting)
  ├── Cognito (auth + AWS credentials)
  ├── DynamoDB (menu data, read via AWS SDK)
  └── WebSocket → AgentCore Runtime
                    └── Strands BidiAgent + Nova Sonic
                          ├── Menu Tools → DynamoDB
                          └── Order Tools → DynamoDB
```

## Prerequisites

- Node.js 18+
- Python 3.11+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- An AWS account with access to Amazon Bedrock Nova Sonic in us-east-1

## Project Structure

```
cdk/          – AWS CDK infrastructure (Python), deploys everything
agent/        – Strands BidiAgent with menu & order tools (Python)
frontend/     – Vite + React + TypeScript SPA
```

---

## 1. Deploy Everything

A single `cdk deploy` builds and deploys the entire stack: DynamoDB tables, S3 buckets, CloudFront, Cognito, the AgentCore Runtime agent, and the frontend SPA.

The agent is deployed via `@aws-cdk/aws-bedrock-agentcore-alpha` with direct code deployment. The frontend is built locally (or in Docker), uploaded to S3, and served via CloudFront. A `runtime-config.json` is generated with all resource IDs so the frontend doesn't need any manual `.env` configuration.

```bash
cd cdk
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# First time only
cdk bootstrap

# Deploy everything (infrastructure + agent + frontend)
cdk deploy
```

After deploy, note the stack outputs:

| Output                   | Description                  |
|--------------------------|------------------------------|
| `DistributionDomainName` | Your app URL                 |
| `AgentEndpointUrl`       | Agent WebSocket endpoint     |
| `UserPoolId`             | Cognito User Pool ID         |
| `UserPoolClientId`       | Cognito client ID            |
| `IdentityPoolId`         | Cognito Identity Pool ID     |
| `MenuTableName`          | DynamoDB menu table          |
| `ImagesBucketName`       | S3 bucket for food images    |
| `AgentRuntimeId`         | AgentCore Runtime ID         |

## 2. Seed Menu Data

Upload menu items to the `DriveThruMenu` DynamoDB table:

```bash
# Category metadata
aws dynamodb put-item --table-name DriveThruMenu --item '{
  "PK": {"S": "CATEGORY#burgers"},
  "SK": {"S": "METADATA"},
  "name": {"S": "Burgers"},
  "sortOrder": {"N": "1"}
}'

# Menu item
aws dynamodb put-item --table-name DriveThruMenu --item '{
  "PK": {"S": "CATEGORY#burgers"},
  "SK": {"S": "ITEM#classic"},
  "name": {"S": "Classic Burger"},
  "description": {"S": "A juicy beef patty with lettuce, tomato, and pickles"},
  "price": {"N": "899"},
  "imageUrl": {"S": "images/classic-burger.jpg"},
  "category": {"S": "Burgers"},
  "featured": {"BOOL": true},
  "sortOrder": {"N": "1"}
}'
```

Prices are in cents (899 = $8.99). Upload food images to the S3 images bucket:

```bash
aws s3 cp ./my-images/ s3://<ImagesBucketName>/images/ --recursive
```

## 3. Create a Cognito User

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username your@email.com \
  --temporary-password TempPass123! \
  --user-attributes Name=email,Value=your@email.com Name=email_verified,Value=true

aws cognito-idp admin-set-user-password \
  --user-pool-id <UserPoolId> \
  --username your@email.com \
  --password YourPassword123! \
  --permanent
```

## 4. Try It Out

1. Open `https://<DistributionDomainName>` in your browser
2. Sign in with the Cognito user you created
3. Browse the visual menu
4. Click "Start Voice Order" and allow microphone access
5. Talk to the AI attendant — try things like:
   - "What do you have?"
   - "Tell me about the classic burger"
   - "I'll take two cheeseburgers and a cola"
   - "What's my total?"
   - "That's all, place my order"

## Local Development

### Frontend dev server

For local development, create `frontend/public/runtime-config.json` with your deployed resource IDs (or use `frontend/.env` with `VITE_*` vars as fallbacks):

```json
{
  "userPoolId": "us-east-1_XXXXXXXXX",
  "userPoolClientId": "xxxxxxxxxxxxxxxxxxxxxxxxxx",
  "identityPoolId": "us-east-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "menuTableName": "DriveThruMenu",
  "awsRegion": "us-east-1",
  "agentEndpointUrl": "wss://your-agent-endpoint"
}
```

```bash
cd frontend
npm install
npm run dev        # starts at http://localhost:5173
```

### Run Tests

```bash
# CDK tests
cd cdk && python -m pytest tests/ -v

# Agent tests
python -m pytest agent/ -v

# Frontend tests
cd frontend && npm test
```

All three layers have property-based tests (Hypothesis for Python, fast-check for TypeScript) that verify correctness properties across randomly generated inputs.

## Redeploying

After code changes, just run `cdk deploy` again — it rebuilds the frontend, repackages the agent, and updates everything in one shot.
