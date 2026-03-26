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
data/         – Sample menu data and placeholder images
```

---

## 1. Build the Frontend

```bash
cd frontend
npm ci
npm run build
cd ..
```

## 2. Deploy Everything

A single `cdk deploy` handles the entire stack:

- DynamoDB tables (menu + orders)
- S3 buckets (food images + frontend hosting)
- CloudFront distribution
- Cognito User Pool + Identity Pool
- AgentCore Runtime with the voice agent
- Frontend SPA uploaded to S3
- Runtime config injected automatically
- Sample menu data seeded into DynamoDB
- Placeholder food images uploaded to S3

```bash
cd cdk
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# First time only
cdk bootstrap

# Deploy everything
cdk deploy
```

No manual data seeding or image uploads needed — it's all handled by CDK.

## 3. Create a Cognito User

This is the only manual step after deploy:

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

Replace `<UserPoolId>` with the value from the `cdk deploy` output.

## 4. Try It Out

1. Open `https://<DistributionDomainName>` in your browser
2. Sign in with the Cognito user you created
3. Browse the visual menu (5 categories, 21 items)
4. Click "Start Voice Order" and allow microphone access
5. Talk to the AI attendant — try things like:
   - "What do you have?"
   - "Tell me about the classic burger"
   - "I'll take two cheeseburgers and a cola"
   - "What's my total?"
   - "That's all, place my order"

## Sample Menu

The deploy seeds these categories automatically:

| Category | Items | Price Range |
|----------|-------|-------------|
| Burgers  | Classic, Cheese, Bacon, Double, Veggie | $7.99–$11.99 |
| Chicken  | Crispy Sandwich, Spicy, Nuggets 6pc/10pc | $5.99–$9.99 |
| Sides    | Fries, Onion Rings, Mozz Sticks, Salad | $3.49–$5.49 |
| Drinks   | Cola, Lemonade, Iced Tea, Milkshakes | $2.49–$5.49 |
| Desserts | Apple Pie, Sundae, Cookie | $1.99–$4.49 |

To modify the menu, edit `data/menu_items.json` and run `cdk deploy` again.

## Local Development

### Frontend dev server

Create `frontend/public/runtime-config.json` with your deployed resource IDs:

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
cd frontend && npm run dev
```

### Run Tests

```bash
cd cdk && python -m pytest tests/ -v       # CDK (21 tests)
python -m pytest agent/ -v                  # Agent (58 tests)
cd frontend && npm test                     # Frontend (134 tests)
```

### Redeploying

After any code or data changes:

```bash
cd frontend && npm run build && cd ../cdk && cdk deploy
```
