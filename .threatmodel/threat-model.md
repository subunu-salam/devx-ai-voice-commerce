# Comprehensive Threat Model Report

**Generated**: 2026-04-30 12:30:59
**Current Phase**: 1 - Business Context Analysis
**Overall Completion**: 100.0%

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Business Context](#business-context)
3. [System Architecture](#system-architecture)
4. [Threat Actors](#threat-actors)
5. [Trust Boundaries](#trust-boundaries)
6. [Assets and Flows](#assets-and-flows)
7. [Threats](#threats)
8. [Mitigations](#mitigations)
9. [Assumptions](#assumptions)
10. [Phase Progress](#phase-progress)

## Executive Summary

Drive-thru voice ordering application built with Amazon Nova Sonic, Strands Agents SDK, and React. Customers interact with an AI voice attendant via WebSocket to browse a menu, customize orders, and place them. The agent controls the entire frontend UI through a single update_ui tool. Architecture includes a React SPA frontend served via CloudFront, a Python/FastAPI backend agent running on AWS Bedrock AgentCore Runtime, DynamoDB for menu and order storage, S3 for image hosting, and Cognito for authentication. All communication flows through bidirectional WebSocket with JSON protocol (audio is base64-encoded).

### Key Statistics

- **Total Threats**: 11
- **Total Mitigations**: 13
- **Total Assumptions**: 5
- **System Components**: 9
- **Assets**: 13
- **Threat Actors**: 10

## Business Context

**Description**: Drive-thru voice ordering application built with Amazon Nova Sonic, Strands Agents SDK, and React. Customers interact with an AI voice attendant via WebSocket to browse a menu, customize orders, and place them. The agent controls the entire frontend UI through a single update_ui tool. Architecture includes a React SPA frontend served via CloudFront, a Python/FastAPI backend agent running on AWS Bedrock AgentCore Runtime, DynamoDB for menu and order storage, S3 for image hosting, and Cognito for authentication. All communication flows through bidirectional WebSocket with JSON protocol (audio is base64-encoded).

### Business Features

- **Industry Sector**: Retail
- **Data Sensitivity**: Internal
- **User Base Size**: Medium
- **Geographic Scope**: Regional
- **Regulatory Requirements**: None
- **System Criticality**: Medium
- **Financial Impact**: Medium
- **Authentication Requirement**: Basic
- **Deployment Environment**: Cloud-Public
- **Integration Complexity**: Complex

## System Architecture

### Components

| ID | Name | Type | Service Provider | Description |
|---|---|---|---|---|
| C001 | Frontend SPA | Compute | AWS | React SPA served via CloudFront. Renders UI state received from agent. Captures microphone audio and sends via WebSocket. |
| C002 | Voice Agent (Backend) | Compute | AWS | Python FastAPI backend running Strands BidiAgent with Amazon Nova Sonic. Handles voice processing, menu queries, order management, and UI state control. Runs as container on AgentCore Runtime. |
| C003 | Menu Table (DynamoDB) | Storage | AWS | DynamoDB table storing menu categories and items. Partition key PK (CATEGORY#id), sort key SK (METADATA or ITEM#id). Read by agent for menu queries. |
| C004 | Orders Table (DynamoDB) | Storage | AWS | DynamoDB table storing placed orders. Contains orderId, userId, items, total, timestamp. Written by agent on order placement. |
| C005 | Images S3 Bucket | Storage | AWS | S3 bucket storing food images. Served via CloudFront distribution with OAC. Not directly accessible from internet. |
| C006 | CloudFront CDN | Network | AWS | CloudFront distribution serving frontend SPA and food images. Enforces HTTPS, uses OAC for S3 access. No WAF configured. |
| C007 | Seed Lambda | Compute | AWS | Lambda function that seeds DynamoDB menu table with initial menu data and uploads food images to S3 during deployment. |
| C008 | Amazon Bedrock (Nova Sonic) | Compute | AWS | Amazon Bedrock Nova Sonic model providing speech-to-text and text-to-speech capabilities for the voice agent. |
| C009 | Cognito User Pool | Security | AWS | AWS Cognito User Pool for user authentication. Issues JWT tokens used for WebSocket authentication via Sec-WebSocket-Protocol header. MFA is disabled. |

### Connections

| ID | Source | Destination | Protocol | Port | Encrypted | Description |
|---|---|---|---|---|---|---|
| CN001 | C006 | C001 | HTTPS | 443 | Yes | User browser loads React SPA from CloudFront CDN over HTTPS. |
| CN002 | C002 | C003 | HTTPS | 443 | Yes | Voice Agent reads menu categories and items from DynamoDB Menu table. |
| CN003 | C002 | C004 | HTTPS | 443 | Yes | Voice Agent writes placed orders to DynamoDB Orders table. |
| CN004 | C002 | C008 | HTTPS | 443 | Yes | Voice Agent invokes Amazon Bedrock Nova Sonic for speech-to-text and text-to-speech processing. |
| CN005 | C001 | C009 | HTTPS | 443 | Yes | Frontend SPA authenticates users via Cognito User Pool to obtain JWT tokens. |
| CN006 | C006 | C005 | HTTPS | 443 | Yes | CloudFront serves food images from S3 Images bucket via Origin Access Control. |
| CN007 | C001 | C002 | WebSocket | 443 | Yes | Frontend SPA connects to Voice Agent via secure WebSocket through AgentCore Runtime. JWT token passed in Sec-WebSocket-Protocol header. Bidirectional audio + UI state events. |

### Data Stores

| ID | Name | Type | Classification | Encrypted at Rest | Description |
|---|---|---|---|---|---|
| D001 | Menu Data (DynamoDB) | NoSQL | Internal | Yes | DynamoDB table storing menu categories and items with prices, descriptions, and image references. |
| D002 | Order Data (DynamoDB) | NoSQL | Confidential | Yes | DynamoDB table storing placed orders with orderId, userId, items, total, timestamp, and special instructions. |
| D003 | Food Images (S3) | Object Storage | Public | Yes | S3 bucket storing food item images served via CloudFront. Block public access enabled, SSL enforced. |
| D004 | User Credentials (Cognito) | Other | Confidential | Yes | Cognito User Pool storing user credentials (hashed passwords), email addresses, and authentication state. |

## Threat Actors

### Insider

- **Type**: ThreatActorType.INSIDER
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Revenge
- **Resources**: ResourceLevel.LIMITED
- **Relevant**: Yes
- **Priority**: 4/10
- **Description**: An employee or contractor with legitimate access to the system

### External Attacker

- **Type**: ThreatActorType.EXTERNAL
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 1/10
- **Description**: An external individual or group attempting to gain unauthorized access

### Nation-state Actor

- **Type**: ThreatActorType.NATION_STATE
- **Capability Level**: CapabilityLevel.HIGH
- **Motivations**: Espionage, Political
- **Resources**: ResourceLevel.EXTENSIVE
- **Relevant**: No
- **Priority**: 1/10
- **Description**: A government-sponsored group with advanced capabilities

### Hacktivist

- **Type**: ThreatActorType.HACKTIVIST
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Ideology, Political
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: No
- **Priority**: 6/10
- **Description**: An individual or group motivated by ideological or political beliefs

### Organized Crime

- **Type**: ThreatActorType.ORGANIZED_CRIME
- **Capability Level**: CapabilityLevel.HIGH
- **Motivations**: Financial
- **Resources**: ResourceLevel.EXTENSIVE
- **Relevant**: Yes
- **Priority**: 3/10
- **Description**: A criminal organization with significant resources

### Competitor

- **Type**: ThreatActorType.COMPETITOR
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Espionage
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: No
- **Priority**: 7/10
- **Description**: A business competitor seeking competitive advantage

### Script Kiddie

- **Type**: ThreatActorType.SCRIPT_KIDDIE
- **Capability Level**: CapabilityLevel.LOW
- **Motivations**: Curiosity, Reputation
- **Resources**: ResourceLevel.LIMITED
- **Relevant**: Yes
- **Priority**: 2/10
- **Description**: An inexperienced attacker using pre-made tools

### Disgruntled Employee

- **Type**: ThreatActorType.DISGRUNTLED_EMPLOYEE
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Revenge
- **Resources**: ResourceLevel.LIMITED
- **Relevant**: Yes
- **Priority**: 7/10
- **Description**: A current or former employee with a grievance

### Privileged User

- **Type**: ThreatActorType.PRIVILEGED_USER
- **Capability Level**: CapabilityLevel.HIGH
- **Motivations**: Financial, Accidental
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 5/10
- **Description**: A user with elevated privileges who may abuse them or make mistakes

### Third Party

- **Type**: ThreatActorType.THIRD_PARTY
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Accidental
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 6/10
- **Description**: A vendor, partner, or service provider with access to the system

## Trust Boundaries

### Trust Zones

#### Internet

- **Trust Level**: TrustLevel.UNTRUSTED
- **Description**: The public internet, considered untrusted

#### DMZ

- **Trust Level**: TrustLevel.LOW
- **Description**: Demilitarized zone for public-facing services

#### Application

- **Trust Level**: TrustLevel.MEDIUM
- **Description**: Zone containing application servers and services

#### Data

- **Trust Level**: TrustLevel.HIGH
- **Description**: Zone containing databases and data storage

#### Admin

- **Trust Level**: TrustLevel.FULL
- **Description**: Administrative zone with highest privileges

#### Internet / End User

- **Trust Level**: TrustLevel.UNTRUSTED
- **Description**: Public internet where end users interact with the application via browser. Untrusted input source.

#### CDN Edge (CloudFront)

- **Trust Level**: TrustLevel.LOW
- **Description**: CloudFront CDN edge serving static frontend assets and images. AWS-managed, public-facing.

#### Application Tier (AWS Managed)

- **Trust Level**: TrustLevel.MEDIUM
- **Description**: AWS managed services tier: AgentCore Runtime (voice agent), Bedrock (Nova Sonic), Cognito. Authenticated access required.

#### Data Tier (DynamoDB / S3)

- **Trust Level**: TrustLevel.HIGH
- **Description**: Data storage tier: DynamoDB tables (menu, orders), S3 buckets. Accessible only from application tier via IAM roles.

### Trust Boundaries

#### Internet Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Web Application Firewall, DDoS Protection, TLS Encryption
- **Description**: Boundary between the internet and internal systems

#### DMZ Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Network Firewall, Intrusion Detection System, API Gateway
- **Description**: Boundary between public-facing services and internal applications

#### Data Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Database Firewall, Encryption, Access Control Lists
- **Description**: Boundary protecting data storage systems

#### Admin Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Privileged Access Management, Multi-Factor Authentication, Audit Logging
- **Description**: Boundary for administrative access

#### Internet to CDN Edge

- **Type**: BoundaryType.NETWORK
- **Controls**: HTTPS/TLS, CloudFront Edge Caching, OAC for S3
- **Description**: Boundary between public internet and CloudFront CDN. No WAF configured.

#### User to Application Services

- **Type**: BoundaryType.NETWORK
- **Controls**: Cognito JWT Authentication, WebSocket Protocol Auth, TLS 1.2+
- **Description**: Boundary between end user browser and AWS application services. Authentication required via Cognito JWT.

#### Application to Data Tier

- **Type**: BoundaryType.ACCOUNT
- **Controls**: IAM Role-based Access, Least Privilege Policies, HTTPS
- **Description**: Boundary between application tier and data storage. Agent accesses DynamoDB/S3 via IAM role with minimal permissions.

## Assets and Flows

### Assets

| ID | Name | Type | Classification | Sensitivity | Criticality | Owner |
|---|---|---|---|---|---|---|
| A001 | User Credentials | AssetType.CREDENTIAL | AssetClassification.CONFIDENTIAL | 5 | 5 | N/A |
| A002 | Personal Identifiable Information | AssetType.DATA | AssetClassification.CONFIDENTIAL | 4 | 4 | N/A |
| A003 | Session Token | AssetType.TOKEN | AssetClassification.CONFIDENTIAL | 5 | 5 | N/A |
| A004 | Configuration Data | AssetType.CONFIG | AssetClassification.INTERNAL | 3 | 4 | N/A |
| A005 | Encryption Keys | AssetType.KEY | AssetClassification.RESTRICTED | 5 | 5 | N/A |
| A006 | Public Content | AssetType.DATA | AssetClassification.PUBLIC | 1 | 2 | N/A |
| A007 | Audit Logs | AssetType.DATA | AssetClassification.INTERNAL | 3 | 4 | N/A |
| A008 | JWT Authentication Tokens | AssetType.CREDENTIAL | AssetClassification.CONFIDENTIAL | 4 | 4 | N/A |
| A009 | Customer Order Data | AssetType.DATA | AssetClassification.CONFIDENTIAL | 3 | 3 | N/A |
| A010 | Menu Data | AssetType.DATA | AssetClassification.INTERNAL | 2 | 3 | N/A |
| A011 | Voice Audio Stream | AssetType.DATA | AssetClassification.CONFIDENTIAL | 4 | 4 | N/A |
| A012 | User Credentials | AssetType.CREDENTIAL | AssetClassification.CONFIDENTIAL | 5 | 5 | N/A |
| A013 | UI State Data | AssetType.DATA | AssetClassification.INTERNAL | 1 | 3 | N/A |

### Asset Flows

| ID | Asset | Source | Destination | Protocol | Encrypted | Risk Level |
|---|---|---|---|---|---|---|
| F001 | User Credentials | C001 | C002 | HTTPS | Yes | 4 |
| F002 | Session Token | C002 | C001 | HTTPS | Yes | 3 |
| F003 | Personal Identifiable Information | C003 | C004 | TLS | Yes | 3 |
| F004 | Audit Logs | C003 | C005 | TLS | Yes | 2 |
| F005 | Menu Data | C003 | C002 | HTTPS | Yes | 1 |
| F006 | Customer Order Data | C002 | C004 | HTTPS | Yes | 2 |
| F007 | Voice Audio Stream | C001 | C002 | WebSocket | Yes | 3 |
| F008 | UI State Data | C002 | C001 | WebSocket | Yes | 2 |
| F009 | JWT Authentication Tokens | C001 | C009 | HTTPS | Yes | 3 |

## Threats

### Resolved Threats

#### T1: External attacker

**Statement**: A External attacker with stolen or guessed credentials can authenticate as a legitimate user and place fraudulent orders, which leads to unauthorized orders placed under victim's account, potential financial loss

- **Prerequisites**: with stolen or guessed credentials
- **Action**: authenticate as a legitimate user and place fraudulent orders
- **Impact**: unauthorized orders placed under victim's account, potential financial loss
- **Impacted Assets**: A008
- **Tags**: STRIDE-S, Authentication

#### T2: Authenticated user

**Statement**: A Authenticated user with access to the agent session can manipulate order data by injecting crafted voice or text input to alter prices or items, which leads to incorrect orders placed, potential price manipulation

- **Prerequisites**: with access to the agent session
- **Action**: manipulate order data by injecting crafted voice or text input to alter prices or items
- **Impact**: incorrect orders placed, potential price manipulation
- **Impacted Assets**: A009
- **Tags**: STRIDE-T, Data Integrity

#### T3: Authenticated user

**Statement**: A Authenticated user after placing an order via voice can deny having placed an order since no audit trail or voice recording is retained, which leads to disputed orders with no evidence, financial loss for business

- **Prerequisites**: after placing an order via voice
- **Action**: deny having placed an order since no audit trail or voice recording is retained
- **Impact**: disputed orders with no evidence, financial loss for business
- **Impacted Assets**: A009, A011
- **Tags**: STRIDE-R, Audit

#### T4: Network attacker

**Statement**: A Network attacker with ability to intercept WebSocket traffic can eavesdrop on voice audio and order data transmitted via WebSocket, which leads to exposure of customer voice data, order details, and preferences

- **Prerequisites**: with ability to intercept WebSocket traffic
- **Action**: eavesdrop on voice audio and order data transmitted via WebSocket
- **Impact**: exposure of customer voice data, order details, and preferences
- **Impacted Assets**: A009, A011
- **Tags**: STRIDE-I, Privacy

#### T5: External attacker or script kiddie

**Statement**: A External attacker or script kiddie with internet access to the application can flood the WebSocket endpoint or CloudFront with requests to exhaust resources, which leads to service unavailable for legitimate customers, revenue loss

- **Prerequisites**: with internet access to the application
- **Action**: flood the WebSocket endpoint or CloudFront with requests to exhaust resources
- **Impact**: service unavailable for legitimate customers, revenue loss
- **Tags**: STRIDE-D, Availability

#### T6: Malicious user

**Statement**: A Malicious user with access to the agent's tool interface can exploit prompt injection via voice to make agent execute unintended tool calls or access unauthorized data, which leads to unauthorized data access, menu manipulation, or agent misuse

- **Prerequisites**: with access to the agent's tool interface
- **Action**: exploit prompt injection via voice to make agent execute unintended tool calls or access unauthorized data
- **Impact**: unauthorized data access, menu manipulation, or agent misuse
- **Impacted Assets**: A010
- **Tags**: STRIDE-E, Authorization

#### T7: External attacker

**Statement**: A External attacker with automated tooling can perform credential stuffing or brute force attacks against Cognito login, which leads to account compromise, unauthorized access to ordering system

- **Prerequisites**: with automated tooling
- **Action**: perform credential stuffing or brute force attacks against Cognito login
- **Impact**: account compromise, unauthorized access to ordering system
- **Impacted Assets**: A008
- **Tags**: STRIDE-S, Authentication

#### T8: Authenticated user

**Statement**: A Authenticated user with authenticated session can inject malicious content in special_instructions field stored in DynamoDB, which leads to stored XSS if instructions rendered unsafely, or NoSQL injection

- **Prerequisites**: with authenticated session
- **Action**: inject malicious content in special_instructions field stored in DynamoDB
- **Impact**: stored XSS if instructions rendered unsafely, or NoSQL injection
- **Impacted Assets**: A009
- **Tags**: STRIDE-T, Input Validation

#### T9: Malicious authenticated user

**Statement**: A Malicious authenticated user with authenticated WebSocket session can send oversized audio frames or excessive requests to exhaust Bedrock/agent resources, which leads to increased AWS costs, degraded service for other users

- **Prerequisites**: with authenticated WebSocket session
- **Action**: send oversized audio frames or excessive requests to exhaust Bedrock/agent resources
- **Impact**: increased AWS costs, degraded service for other users
- **Tags**: STRIDE-D, Resource Exhaustion

#### T10: External attacker

**Statement**: A External attacker with access to browser memory or XSS vulnerability can steal JWT token from browser memory to hijack authenticated session, which leads to full session hijack, unauthorized order placement

- **Prerequisites**: with access to browser memory or XSS vulnerability
- **Action**: steal JWT token from browser memory to hijack authenticated session
- **Impact**: full session hijack, unauthorized order placement
- **Impacted Assets**: A012
- **Tags**: STRIDE-I, Token Security

#### T11: External attacker

**Statement**: A External attacker when agent encounters errors can trigger error conditions that expose internal system details via silent exception handling, which leads to information leakage about system internals aiding further attacks

- **Prerequisites**: when agent encounters errors
- **Action**: trigger error conditions that expose internal system details via silent exception handling
- **Impact**: information leakage about system internals aiding further attacks
- **Tags**: STRIDE-I, Error Handling

## Mitigations

### Resolved Mitigations

#### M1: Deploy AWS WAF on CloudFront distributions with OWASP managed rules, rate limiting, and bot control.

**Addresses Threats**: T5

#### M3: Implement rate limiting per user/session on WebSocket connections and agent tool invocations.

**Addresses Threats**: T5, T9

#### M4: Add input validation and sanitization for special_instructions field before storing in DynamoDB.

**Addresses Threats**: T8

#### M5: Implement comprehensive audit logging for order placement, authentication events, and agent actions.

**Addresses Threats**: T3

#### M6: Replace silent exception handling (try/except/pass) with proper error logging in WebSocket cleanup code.

**Addresses Threats**: T11

#### M8: Implement WebSocket payload size limits to prevent oversized audio frames from exhausting resources.

**Addresses Threats**: T9

#### M9: Add prompt injection guardrails to the agent system prompt and implement tool call validation.

**Addresses Threats**: T6

#### M10: Implement Cognito advanced security features including adaptive authentication and compromised credential detection.

**Addresses Threats**: T1, T7

#### M11: Enforce TLS 1.2+ on all connections. WSS for WebSocket. HTTPS for all API calls. Already implemented.

**Addresses Threats**: T4, T10

#### M12: Server-side price validation: agent uses unit_price from DynamoDB, not from user input. Prices are integers (cents).

**Addresses Threats**: T2

#### M13: Add Content Security Policy and security response headers via CloudFront to prevent XSS-based token theft.

**Addresses Threats**: T10

#### M14: Reduce JWT token lifetime to 15 minutes and refresh every 10 minutes to limit exploitation window of stolen tokens.

**Addresses Threats**: T10

### Identified Mitigations

#### M2: Enable MFA on Cognito User Pool for all users to prevent credential-based account takeover.

**Addresses Threats**: T1, T7

## Assumptions

### A001: Authentication

**Description**: Authentication is handled by AWS Cognito with username/password (no MFA enabled). JWT tokens are passed via Sec-WebSocket-Protocol header for WebSocket auth.

- **Impact**: Password compromise leads to full account takeover without MFA as a second factor.
- **Rationale**: MFA is suppressed via cdk-nag suppression. Acceptable for demo/MVP but not production.

### A002: Network

**Description**: All communication uses TLS/HTTPS. WebSocket uses WSS. S3 buckets enforce SSL. CloudFront enforces HTTPS with TLS 1.2+.

- **Impact**: Reduces risk of data interception in transit.
- **Rationale**: Verified in CDK stack configuration - all S3 buckets have enforce_ssl=True, CloudFront uses HTTPS.

### A003: AWS Services

**Description**: The application runs entirely on AWS managed services (AgentCore, DynamoDB, S3, CloudFront, Cognito). No self-managed servers.

- **Impact**: AWS manages infrastructure security, patching, and availability for managed services.
- **Rationale**: CDK stack uses fully managed AWS services, reducing operational security burden.

### A004: Data

**Description**: Order data is stored in DynamoDB with user_id, items, prices, and special instructions. No payment card data is collected or stored.

- **Impact**: Reduces PCI-DSS scope. Data sensitivity is limited to order details and user accounts.
- **Rationale**: Order placement stores order summary only. No payment processing is implemented.

### A005: Authentication

**Description**: No WAF is deployed on CloudFront distributions. This is suppressed via cdk-nag.

- **Impact**: No protection against common web attacks (SQLi, XSS, bot traffic) at the CDN edge.
- **Rationale**: WAF suppressed for cost/simplicity in demo. Should be enabled for production.

## Phase Progress

| Phase | Name | Completion |
|---|---|---|
| 1 | Business Context Analysis | 100% ✅ |
| 2 | Architecture Analysis | 100% ✅ |
| 3 | Threat Actor Analysis | 100% ✅ |
| 4 | Trust Boundary Analysis | 100% ✅ |
| 5 | Asset Flow Analysis | 100% ✅ |
| 6 | Threat Identification | 100% ✅ |
| 7 | Mitigation Planning | 100% ✅ |
| 7.5 | Code Validation Analysis | 100% ✅ |
| 8 | Residual Risk Analysis | 100% ✅ |
| 9 | Output Generation and Documentation | 100% ✅ |

---

*This threat model report was generated automatically by the Threat Modeling MCP Server.*
