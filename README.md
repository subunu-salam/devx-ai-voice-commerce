# Drive-Thru Voice Ordering

A drive-thru ordering app where customers place food orders using natural voice interaction powered by Amazon Nova Sonic via the Strands Agents SDK.

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
cdk/              – Two CDK stacks (BackendStack + FrontendStack)
agent/            – Strands BidiAgent with menu & order tools
frontend/         – Vite + React + TypeScript SPA
data/             – Sample menu data and placeholder images
deploy.sh         – One-command deploy script
generate_config.py – Generates runtime-config.json from backend outputs
```

---

## Deploy

### One command

```bash
./deploy.sh
```

This runs all four steps automatically:

1. Deploys the backend stack (DynamoDB, S3, CloudFront, Cognito, AgentCore Runtime, seeds menu data + images)
2. Reads backend outputs and generates `frontend/public/runtime-config.json`
3. Builds the frontend (`npm ci && npm run build`)
4. Deploys the frontend stack (uploads dist/ to S3, invalidates CloudFront)

### Step by step (if you prefer)

```bash
# 1. Deploy backend
cd cdk
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap    # first time only
cdk deploy BackendStack --outputs-file backend-outputs.json

# 2. Generate frontend config
cd ..
python generate_config.py

# 3. Build frontend
cd frontend && npm ci && npm run build && cd ..

# 4. Deploy frontend
cd cdk
BUCKET=$(python3 -c "import json; print(json.load(open('backend-outputs.json'))['BackendStack']['HostingBucketName'])")
DIST=$(python3 -c "import json; print(json.load(open('backend-outputs.json'))['BackendStack']['DistributionId'])")
cdk deploy FrontendStack --context hostingBucketName="$BUCKET" --context distributionId="$DIST"
```

## Create a Cognito User

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

## Try It Out

1. Open `https://<DistributionDomainName>` in your browser
2. Sign in with the Cognito user you created
3. Browse the visual menu (5 categories, 21 items)
4. Click "Start Voice Order" and allow microphone access
5. Talk to the AI attendant

## Sample Menu

Seeded automatically on deploy:

| Category | Items | Price Range |
|----------|-------|-------------|
| Burgers  | Classic, Cheese, Bacon, Double, Veggie | $7.99–$11.99 |
| Chicken  | Crispy Sandwich, Spicy, Nuggets 6pc/10pc | $5.99–$9.99 |
| Sides    | Fries, Onion Rings, Mozz Sticks, Salad | $3.49–$5.49 |
| Drinks   | Cola, Lemonade, Iced Tea, Milkshakes | $2.49–$5.49 |
| Desserts | Apple Pie, Sundae, Cookie | $1.99–$4.49 |

Edit `data/menu_items.json` and re-run `./deploy.sh` to update.

## Local Development

```bash
cd frontend && npm run dev
```

For local dev, copy `frontend/public/runtime-config.json` from a previous deploy, or create one manually.

### Run Tests

```bash
cd cdk && python -m pytest tests/ -v       # CDK
python -m pytest agent/ -v                  # Agent
cd frontend && npm test                     # Frontend
```

## Redeploying

```bash
./deploy.sh
```
