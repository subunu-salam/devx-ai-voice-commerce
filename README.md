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
cdk/          – AWS CDK infrastructure (Python)
agent/        – Strands BidiAgent with menu & order tools (Python)
frontend/     – Vite + React + TypeScript SPA
```

---

## 1. Deploy Infrastructure

```bash
cd cdk
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Synthesize and review
cdk synth

# Deploy (first time requires bootstrap)
cdk bootstrap   # only once per account/region
cdk deploy
```

After deploy, note the stack outputs — you'll need them:

| Output                 | Used For                          |
|------------------------|-----------------------------------|
| `UserPoolId`           | Frontend auth config              |
| `UserPoolClientId`     | Frontend auth config              |
| `IdentityPoolId`       | Frontend auth config              |
| `MenuTableName`        | Frontend menu service             |
| `HostingBucketName`    | Frontend deployment target        |
| `DistributionDomainName` | Your app URL                   |
| `AgentRoleArn`         | AgentCore Runtime agent role      |
| `ImagesBucketName`     | Upload food images here           |

## 2. Seed Menu Data

Upload menu items to the `DriveThruMenu` DynamoDB table. Each category needs a METADATA record and ITEM records:

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
# Create a user
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username your@email.com \
  --temporary-password TempPass123! \
  --user-attributes Name=email,Value=your@email.com Name=email_verified,Value=true

# Set permanent password
aws cognito-idp admin-set-user-password \
  --user-pool-id <UserPoolId> \
  --username your@email.com \
  --password YourPassword123! \
  --permanent
```

## 4. Deploy the Agent to AgentCore Runtime

```bash
cd agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Deploy the agent to AgentCore Runtime using the AWS CLI or console. Associate it with the `AgentRoleArn` from the CDK outputs. The agent entry point is `agent/main.py`.

Refer to the [Bedrock AgentCore documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html) for deployment steps. You'll get a WebSocket endpoint URL after deployment.

## 5. Build and Deploy the Frontend

```bash
cd frontend
npm install
```

Create a `.env` file with your stack outputs:

```bash
# frontend/.env
VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
VITE_COGNITO_USER_POOL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_IDENTITY_POOL_ID=us-east-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
VITE_MENU_TABLE_NAME=DriveThruMenu
VITE_AWS_REGION=us-east-1
VITE_AGENT_ENDPOINT=wss://your-agentcore-endpoint.amazonaws.com
```

Build and deploy to S3:

```bash
npm run build
aws s3 sync dist/ s3://<HostingBucketName>/ --delete
```

Invalidate CloudFront cache:

```bash
aws cloudfront create-invalidation \
  --distribution-id <DistributionId> \
  --paths "/*"
```

Your app is now live at `https://<DistributionDomainName>`.

## 6. Try It Out

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

### Frontend (dev server)

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
