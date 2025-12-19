# Akunuba Backend API

A comprehensive FastAPI-based backend application for financial services,
featuring trading, portfolio management, KYC/KYB verification, banking
integration, and more.

## Features

- **Authentication & Authorization**: JWT-based authentication with role-based
  access control
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

4. **Run database migrations**
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

