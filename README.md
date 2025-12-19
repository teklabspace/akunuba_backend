# Akunuba Backend API

A comprehensive FastAPI-based backend application for financial services, featuring trading, portfolio management, KYC/KYB verification, banking integration, and more.

## Features

- **Authentication & Authorization**: JWT-based authentication with role-based access control
- **User Management**: Complete user profile and account management
- **Trading**: Integration with Alpaca for stock trading
- **Portfolio Management**: Real-time portfolio tracking and analytics
- **KYC/KYB Verification**: Persona integration for identity verification
- **Banking Integration**: Plaid integration for bank account connections
- **Payment Processing**: Stripe integration for payments and subscriptions
- **Document Management**: Secure document upload and storage
- **Support System**: Ticket-based customer support with SLA tracking
- **Notifications**: Real-time notifications system
- **Chat**: Sendbird integration for in-app messaging
- **Market Data**: Polygon.io integration for market data
- **Analytics**: PostHog integration for product analytics
- **Admin Panel**: Administrative endpoints for system management

## Tech Stack

- **Framework**: FastAPI 0.104.1
- **Database**: PostgreSQL (via Supabase)
- **ORM**: SQLAlchemy 2.0
- **Migrations**: Alembic
- **Authentication**: JWT (python-jose)
- **API Documentation**: Auto-generated OpenAPI/Swagger docs

## Prerequisites

- Python 3.8+
- PostgreSQL database (or Supabase)
- Git

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/teklabspace/akunuba_backend.git
   cd akunuba_backend
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   # On Windows
   venv\Scripts\activate
   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   
   Create a `.env` file in the root directory with the following variables:
   ```env
   # Application Settings
   APP_NAME=Fullego Backend
   APP_ENV=development
   APP_DEBUG=True
   APP_VERSION=1.0.0
   API_V1_PREFIX=/api/v1
   HOST=0.0.0.0
   PORT=8000
   CORS_ORIGINS=http://localhost:3000,http://localhost:5173
   
   # Database
   DATABASE_URL=postgresql://user:password@host:port/database
   
   # Supabase
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_ANON_KEY=your_anon_key
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
   SUPABASE_JWT_SECRET=your_jwt_secret
   
   # Authentication
   SECRET_KEY=your_secret_key_here
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=1440
   
   # Stripe
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   
   # Plaid
   PLAID_CLIENT_ID=your_plaid_client_id
   PLAID_SECRET_KEY=your_plaid_secret
   PLAID_PUBLIC_KEY=your_plaid_public_key
   PLAID_ENV=sandbox
   
   # Persona
   PERSONA_API_KEY=your_persona_api_key
   PERSONA_TEMPLATE_ID=itmpl_...
   
   # Sendbird
   SENDBIRD_APP_ID=your_sendbird_app_id
   SENDBIRD_API_TOKEN=your_sendbird_api_token
   
   # Polygon.io
   POLYGON_API_KEY=your_polygon_api_key
   
   # Alpaca
   ALPACA_API_KEY_ID=your_alpaca_key
   ALPACA_SECRET_KEY=your_alpaca_secret
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   
   # PostHog
   POSTHOG_API_KEY=your_posthog_key
   POSTHOG_PROJECT_API_KEY=your_posthog_project_key
   
   # SendGrid
   SENDGRID_API_KEY=your_sendgrid_key
   EMAIL_FROM_ADDRESS=noreply@fullego.com
   EMAIL_FROM_NAME=Fullego
   ```

5. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

## Running the Application

**Development mode:**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Production mode:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API will be available at:
- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

## API Endpoints

The API is organized into the following modules:

- `/api/v1/auth` - Authentication endpoints
- `/api/v1/users` - User management
- `/api/v1/accounts` - Account management
- `/api/v1/kyc` - KYC verification
- `/api/v1/kyb` - KYB verification
- `/api/v1/assets` - Asset management
- `/api/v1/portfolio` - Portfolio operations
- `/api/v1/trading` - Trading operations
- `/api/v1/marketplace` - Marketplace features
- `/api/v1/payments` - Payment processing
- `/api/v1/subscriptions` - Subscription management
- `/api/v1/banking` - Banking integration
- `/api/v1/documents` - Document management
- `/api/v1/support` - Support tickets
- `/api/v1/notifications` - Notifications
- `/api/v1/reports` - Reports and analytics
- `/api/v1/chat` - Chat functionality
- `/api/v1/analytics` - Analytics endpoints
- `/api/v1/admin` - Admin operations

## Database Migrations

**Create a new migration:**
```bash
alembic revision --autogenerate -m "description of changes"
```

**Apply migrations:**
```bash
alembic upgrade head
```

**Rollback migration:**
```bash
alembic downgrade -1
```

## Project Structure

```
akunuba_backend/
├── app/
│   ├── api/           # API routes and endpoints
│   │   └── v1/        # API version 1
│   ├── core/          # Core functionality (security, permissions, scheduler)
│   ├── integrations/  # Third-party service integrations
│   ├── models/        # SQLAlchemy database models
│   ├── schemas/       # Pydantic schemas for request/response validation
│   ├── services/      # Business logic services
│   ├── utils/         # Utility functions
│   ├── config.py      # Application configuration
│   ├── database.py    # Database connection and session management
│   └── main.py        # FastAPI application entry point
├── alembic/           # Database migration files
├── alembic.ini        # Alembic configuration
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

## Health Check

Check if the API is running:
```bash
curl http://localhost:8000/health
```

## Development

### Code Style
- Follow PEP 8 guidelines
- Use type hints where possible
- Document complex functions and classes

### Testing
- Write unit tests for services and utilities
- Write integration tests for API endpoints
- Use pytest for testing framework

## Security

- All sensitive data should be stored in environment variables
- Never commit `.env` files to version control
- Use HTTPS in production
- Implement proper authentication and authorization
- Validate and sanitize all user inputs

## License

[Specify your license here]

## Support

For support, please contact [your support email or channel]

