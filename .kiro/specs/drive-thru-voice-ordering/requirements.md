# Requirements Document

## Introduction

A drive-thru ordering application that allows customers to place food orders using voice interaction powered by Amazon Nova Sonic through the Strands Agents SDK. The system consists of a Vite + React static SPA frontend hosted on S3 and served via CloudFront, and a Python Strands BidiAgent backend that handles real-time bidirectional voice streaming via BidiNovaSonicModel. The Strands agent uses custom tools for menu browsing and order management. The Strands BidiAgent is deployed to Amazon Bedrock AgentCore Runtime, a serverless runtime purpose-built for AI agents that provides session isolation with dedicated microVMs per user session. Customers authenticate via Amazon Cognito to obtain JWT tokens, which are used for AgentCore WebSocket authentication and AWS SDK access. The browser connects directly to the AgentCore Runtime WebSocket endpoint. Customers interact through a browser-based drive-thru experience where they can browse the menu visually, navigate menu categories and items using voice commands, and place orders by speaking naturally.

## Glossary

- **Frontend**: The Vite + React static single-page application hosted on S3 and served via CloudFront_Distribution, authenticates via Cognito_User_Pool, reads menu data from DynamoDB using Cognito-authenticated AWS SDK calls, and connects directly to the AgentCore_Runtime WebSocket endpoint for voice interaction with the Strands_Agent
- **Strands_Agent**: The Python Strands BidiAgent deployed on AgentCore_Runtime that handles real-time bidirectional voice streaming using BidiNovaSonicModel with Amazon Nova Sonic, and uses custom tools for menu browsing and order management
- **BidiNovaSonicModel**: The Strands Agents SDK experimental model provider (strands.experimental.bidi.models.BidiNovaSonicModel) that connects to Amazon Nova Sonic (model ID: amazon.nova-sonic-v1:0) for bidirectional audio streaming
- **Menu_Tools**: The set of Strands agent tools (get_categories, get_items_by_category, get_item_details, get_recommendations) used by the Strands_Agent to retrieve menu data from the data store
- **Order_Tools**: The set of Strands agent tools (add_to_order, remove_from_order, get_order_summary, place_order, cancel_order) used by the Strands_Agent to manage customer orders
- **CDK_Stack**: The AWS CDK Python infrastructure code that provisions and configures all cloud resources
- **AgentCore_Runtime**: The Amazon Bedrock AgentCore Runtime, a secure serverless runtime purpose-built for deploying AI agents, providing session isolation with dedicated microVMs per user session, automatic scaling, and pay-per-use pricing
- **Cognito_User_Pool**: The Amazon Cognito user pool and identity pool that authenticates customers, issues JWT tokens for AgentCore_Runtime WebSocket authentication, and provides temporary AWS credentials for direct DynamoDB and S3 access from the Frontend
- **CloudFront_Distribution**: The Amazon CloudFront distribution that serves the static Frontend build output from the S3 hosting bucket as its origin
- **Customer**: The end user placing a food order through the drive-thru application
- **Order**: A collection of menu items selected by the customer along with quantities and a computed total price
- **Menu_Item**: A single food or drink product available for ordering, including name, description, price, and image
- **UI_Event**: A structured JSON message sent by the Strands_Agent over the WebSocket alongside audio frames, containing a type field and payload that instructs the Frontend to update its visual state
- **UI_State**: A structured JSON message sent by the Frontend to the Strands_Agent over the WebSocket, containing the current visual state of the Frontend (e.g., currently viewed category, currently highlighted item, visible menu items, current order state) so the Strands_Agent can provide context-aware responses

## Requirements

### Requirement 1: Display Visual Menu

**User Story:** As a customer, I want to see an attractive visual menu with food images, so that I can browse available items before ordering.

#### Acceptance Criteria

1. WHEN the customer opens the Frontend, THE Frontend SHALL read all available menu items from the DynamoDB menu table using Cognito-authenticated AWS SDK calls
2. THE Frontend SHALL display each Menu_Item with its name, description, price, and a food image served from S3 via CloudFront_Distribution
3. WHEN menu items are returned, THE Frontend SHALL organize Menu_Items into categories (e.g., Burgers, Sides, Drinks, Desserts)
4. IF the DynamoDB menu table is unreachable, THEN THE Frontend SHALL display an error message indicating the menu cannot be loaded
5. THE Frontend SHALL render food images at a consistent size and aspect ratio across all Menu_Items

### Requirement 2: Voice Order Initiation

**User Story:** As a customer, I want to start a voice conversation to place my order, so that I can order hands-free like a real drive-thru.

#### Acceptance Criteria

1. THE Frontend SHALL display a clearly visible button to start a voice ordering session
2. WHEN the customer activates the voice ordering button, THE Frontend SHALL request microphone access from the browser
3. WHEN microphone access is granted, THE Frontend SHALL establish a WebSocket connection directly to the AgentCore_Runtime endpoint using the Cognito JWT token for OAuth authentication for bidirectional audio streaming with the Strands_Agent
4. IF microphone access is denied, THEN THE Frontend SHALL display a message explaining that microphone access is required for voice ordering
5. WHILE a voice session is active, THE Frontend SHALL display a visual indicator showing that the system is listening

### Requirement 3: Voice Order Processing

**User Story:** As a customer, I want to speak my order naturally and have the system understand it, so that ordering feels conversational.

#### Acceptance Criteria

1. WHEN the customer speaks a menu item name or description, THE Strands_Agent SHALL use BidiNovaSonicModel to interpret the speech and invoke the appropriate Menu_Tools to identify the matching Menu_Item
2. WHEN the Strands_Agent identifies a Menu_Item from speech, THE Strands_Agent SHALL invoke the add_to_order tool from Order_Tools to add the item to the current Order and confirm the addition via a spoken response
3. WHEN the customer speaks a quantity modifier (e.g., "two burgers"), THE Strands_Agent SHALL invoke the add_to_order tool with the correct quantity for the identified Menu_Item
4. IF the Strands_Agent cannot match spoken input to any Menu_Item, THEN THE Strands_Agent SHALL respond with a spoken prompt asking the customer to repeat or clarify
5. WHEN the customer requests to remove an item from the Order, THE Strands_Agent SHALL invoke the remove_from_order tool and confirm the removal via a spoken response
6. WHILE a voice session is active, THE Strands_Agent SHALL maintain context of the current Order so the customer can make incremental changes
7. WHEN the customer uses a contextual reference (e.g., "I'll take that", "add this one", "how much is that?"), THE Strands_Agent SHALL use the most recent UI_State to resolve the reference to the correct Menu_Item

### Requirement 4: Order Summary and Confirmation

**User Story:** As a customer, I want to review my order before confirming, so that I can verify everything is correct.

#### Acceptance Criteria

1. WHEN the Frontend receives a UI_Event of type "order_update" from the Strands_Agent, THE Frontend SHALL update the running order summary to display the item names, quantities, individual prices, and total price contained in the UI_Event payload
2. WHEN the customer asks to hear the order summary, THE Strands_Agent SHALL invoke the get_order_summary tool and read back all items in the current Order with quantities and the total price
3. WHEN the customer confirms the order via voice (e.g., "that's all", "place my order"), THE Strands_Agent SHALL invoke the place_order tool to finalize the Order
4. WHEN the customer requests to cancel the order, THE Strands_Agent SHALL invoke the cancel_order tool to clear all items from the current Order and confirm the cancellation via spoken response
5. WHEN the Frontend receives a UI_Event of type "order_confirmed" from the Strands_Agent, THE Frontend SHALL display an order confirmation screen with the order number and complete order details contained in the UI_Event payload

### Requirement 5: Menu Data Management

**User Story:** As a restaurant operator, I want menu data stored in DynamoDB, so that menu items can be managed centrally and read directly by the Frontend.

#### Acceptance Criteria

1. THE Frontend SHALL read menu data (name, description, price, category, and image URL) from a DynamoDB menu table using the AWS SDK with Cognito identity pool credentials
2. THE Menu_Tools SHALL read menu data from the same DynamoDB menu table provisioned by the CDK_Stack
3. WHEN a menu data request is made by the Frontend, THE DynamoDB menu table SHALL return the response as structured items containing name, description, price, category, and image URL fields
4. THE DynamoDB menu table SHALL store food image URLs referencing an S3 bucket provisioned by the CDK_Stack

### Requirement 6: Order Persistence

**User Story:** As a restaurant operator, I want orders saved to a database, so that I can track and fulfill them.

#### Acceptance Criteria

1. WHEN the place_order tool is invoked, THE Order_Tools SHALL persist the Order with a unique order number, item details, quantities, total price, and a timestamp
2. THE Order_Tools SHALL store orders in a DynamoDB orders table provisioned by the CDK_Stack
3. WHEN the Order is persisted, THE Order_Tools SHALL return the generated order number to the Strands_Agent, which relays it to the Frontend

### Requirement 7: Infrastructure Deployment

**User Story:** As a developer, I want all cloud resources defined in Python CDK, so that the infrastructure is reproducible and version-controlled.

#### Acceptance Criteria

1. THE CDK_Stack SHALL provision a DynamoDB table for storing Orders
2. THE CDK_Stack SHALL provision a DynamoDB table for storing menu data
3. THE CDK_Stack SHALL provision an S3 bucket for storing food images
4. THE CDK_Stack SHALL provision an S3 bucket for hosting the static Frontend build output
5. THE CDK_Stack SHALL provision a CloudFront_Distribution that uses the S3 hosting bucket as its origin to serve the Frontend
6. THE CDK_Stack SHALL provision a Cognito_User_Pool for customer authentication
7. THE CDK_Stack SHALL provision a Cognito identity pool federated with the Cognito_User_Pool to issue temporary AWS credentials for authenticated users
8. THE CDK_Stack SHALL provision an AgentCore_Runtime endpoint for the Strands_Agent deployment
9. THE CDK_Stack SHALL grant the AgentCore_Runtime agent permissions to invoke Amazon Bedrock with the amazon.nova-sonic-v1:0 model in us-east-1, access the DynamoDB orders table for order persistence, access the DynamoDB menu table for menu data, and read from the S3 bucket for food images
10. THE CDK_Stack SHALL configure the Cognito identity pool authenticated role with least-privilege IAM permissions granting read-only access to the DynamoDB menu table and read access to the S3 food images bucket
11. THE CDK_Stack SHALL configure the CloudFront_Distribution with an Origin Access Identity to restrict direct S3 bucket access

### Requirement 8: Voice Menu Browsing

**User Story:** As a customer, I want to browse the menu using voice commands, so that I can discover available items and make informed choices without needing to look at the screen.

#### Acceptance Criteria

1. WHEN the customer asks what categories are available (e.g., "what do you have?", "what are the categories?"), THE Strands_Agent SHALL invoke the get_categories tool and respond with a spoken list of all menu categories
2. WHEN the customer asks about a specific category (e.g., "what burgers do you have?", "tell me about the sides"), THE Strands_Agent SHALL invoke the get_items_by_category tool and respond with a spoken list of all Menu_Items in that category including names and prices
3. WHEN the customer asks about a specific Menu_Item (e.g., "tell me about the cheeseburger", "what comes on the classic burger?"), THE Strands_Agent SHALL invoke the get_item_details tool and respond with the item name, description, and price
4. WHEN the Frontend receives a UI_Event of type "browse_category" from the Strands_Agent, THE Frontend SHALL scroll to and visually highlight the corresponding category and display the relevant Menu_Items
5. WHEN the Frontend receives a UI_Event of type "highlight_item" from the Strands_Agent, THE Frontend SHALL visually highlight the specified Menu_Item on the menu display
6. IF the customer asks about a category or Menu_Item that does not exist, THEN THE Strands_Agent SHALL respond with a spoken message indicating the item was not found and suggest available alternatives
7. WHEN the customer asks for recommendations (e.g., "what do you recommend?", "what's popular?"), THE Strands_Agent SHALL invoke the get_recommendations tool and respond with a spoken list of featured or popular Menu_Items
8. WHEN the customer asks about "this category" or "these items" without specifying a name, THE Strands_Agent SHALL use the most recent UI_State to determine which category or items the customer is referring to

### Requirement 9: Voice Session Management

**User Story:** As a customer, I want the voice session to handle pauses and disconnections gracefully, so that my ordering experience is smooth.

#### Acceptance Criteria

1. IF the WebSocket connection between the Frontend and the AgentCore_Runtime is interrupted during a voice session, THEN THE Frontend SHALL attempt to reconnect directly to the AgentCore_Runtime within 5 seconds
2. IF the voice session is idle for more than 30 seconds, THEN THE Strands_Agent SHALL prompt the customer with a spoken message asking if they would like to continue ordering
3. IF the voice session is idle for more than 60 seconds after the prompt, THEN THE Strands_Agent SHALL end the session and notify the Frontend
4. WHEN a voice session ends, THE Frontend SHALL return to the initial menu browsing state while preserving any items already in the Order

### Requirement 10: Customer Authentication

**User Story:** As a customer, I want to authenticate before placing an order, so that my session is secure and I can access the ordering system.

#### Acceptance Criteria

1. WHEN the customer opens the Frontend, THE Frontend SHALL present a sign-in screen powered by Cognito_User_Pool
2. WHEN the customer provides valid credentials, THE Cognito_User_Pool SHALL issue a JWT token to the Frontend
3. THE Frontend SHALL use the Cognito JWT token for OAuth authentication when establishing the WebSocket connection to AgentCore_Runtime
4. THE Frontend SHALL use Cognito identity pool credentials obtained via the JWT token for AWS SDK calls to DynamoDB and S3
5. IF the JWT token expires during an active session, THEN THE Frontend SHALL refresh the token using the Cognito refresh token without interrupting the customer experience
6. IF authentication fails, THEN THE Frontend SHALL display an error message and prompt the customer to retry sign-in

### Requirement 11: Agent-Driven UI Updates

**User Story:** As a customer, I want the visual display to update in real-time as I interact with the voice agent, so that I can see what the agent is doing.

#### Acceptance Criteria

1. THE Strands_Agent SHALL send structured JSON UI_Event messages over the WebSocket connection alongside audio frames
2. THE Frontend SHALL demultiplex incoming WebSocket messages, treating binary frames as audio data and text frames as JSON UI_Events
3. WHEN the Strands_Agent invokes any Order_Tools tool (add_to_order, remove_from_order, cancel_order, place_order), THE Strands_Agent SHALL send a UI_Event of type "order_update" containing the current order state (items, quantities, prices, total)
4. WHEN the Strands_Agent invokes the get_categories tool, THE Strands_Agent SHALL send a UI_Event of type "highlight_category" containing the category name to highlight
5. WHEN the Strands_Agent invokes the get_items_by_category tool, THE Strands_Agent SHALL send a UI_Event of type "browse_category" containing the category name, causing the Frontend to scroll to and highlight that category
6. WHEN the Strands_Agent invokes the get_item_details tool, THE Strands_Agent SHALL send a UI_Event of type "highlight_item" containing the Menu_Item identifier, causing the Frontend to visually highlight that specific item
7. WHEN the Strands_Agent invokes the place_order tool successfully, THE Strands_Agent SHALL send a UI_Event of type "order_confirmed" containing the order number and complete order details
8. THE Frontend SHALL maintain a local state store that is updated by incoming UI_Events, and all visual components SHALL reactively render based on this state
9. THE Frontend SHALL send structured JSON UI_State messages over the WebSocket connection alongside audio frames to provide the Strands_Agent with current visual context
10. WHEN the WebSocket voice session is established, THE Frontend SHALL send an initial UI_State message containing the full current state including the visible category, any items in the Order, and the currently highlighted Menu_Item
11. WHEN the customer scrolls to or selects a different menu category in the Frontend, THE Frontend SHALL send a UI_State message to the Strands_Agent containing the currently visible category
12. WHEN the customer taps or clicks on a specific Menu_Item in the Frontend, THE Frontend SHALL send a UI_State message to the Strands_Agent containing the selected Menu_Item identifier
13. THE Strands_Agent SHALL use the most recent UI_State received from the Frontend to provide context-aware spoken responses when the customer makes ambiguous or deictic references
