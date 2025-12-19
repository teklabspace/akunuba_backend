from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1 import auth, users, accounts, assets, portfolio, trading, marketplace, payments, subscriptions, banking, documents, support, notifications, reports, kyc, kyb, chat, analytics, admin
from app.utils.logger import logger

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.APP_DEBUG,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["Authentication"])
app.include_router(users.router, prefix=f"{settings.API_V1_PREFIX}/users", tags=["Users"])
app.include_router(accounts.router, prefix=f"{settings.API_V1_PREFIX}/accounts", tags=["Accounts"])
app.include_router(kyc.router, prefix=f"{settings.API_V1_PREFIX}/kyc", tags=["KYC"])
app.include_router(kyb.router, prefix=f"{settings.API_V1_PREFIX}/kyb", tags=["KYB"])
app.include_router(assets.router, prefix=f"{settings.API_V1_PREFIX}/assets", tags=["Assets"])
app.include_router(portfolio.router, prefix=f"{settings.API_V1_PREFIX}/portfolio", tags=["Portfolio"])
app.include_router(trading.router, prefix=f"{settings.API_V1_PREFIX}/trading", tags=["Trading"])
app.include_router(marketplace.router, prefix=f"{settings.API_V1_PREFIX}/marketplace", tags=["Marketplace"])
app.include_router(payments.router, prefix=f"{settings.API_V1_PREFIX}/payments", tags=["Payments"])
app.include_router(subscriptions.router, prefix=f"{settings.API_V1_PREFIX}/subscriptions", tags=["Subscriptions"])
app.include_router(banking.router, prefix=f"{settings.API_V1_PREFIX}/banking", tags=["Banking"])
app.include_router(documents.router, prefix=f"{settings.API_V1_PREFIX}/documents", tags=["Documents"])
app.include_router(support.router, prefix=f"{settings.API_V1_PREFIX}/support", tags=["Support"])
app.include_router(notifications.router, prefix=f"{settings.API_V1_PREFIX}/notifications", tags=["Notifications"])
app.include_router(reports.router, prefix=f"{settings.API_V1_PREFIX}/reports", tags=["Reports"])
app.include_router(chat.router, prefix=f"{settings.API_V1_PREFIX}/chat", tags=["Chat"])
app.include_router(analytics.router, prefix=f"{settings.API_V1_PREFIX}/analytics", tags=["Analytics"])
app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin", tags=["Admin"])


@app.get("/")
async def root():
    return {
        "message": "Fullego Backend API",
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION
    }


@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    
    # Start background job scheduler
    from app.core.scheduler import scheduler, setup_scheduled_tasks
    if settings.APP_ENV != "test":
        setup_scheduled_tasks()
        scheduler.start()
        logger.info("Background job scheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    from app.integrations.posthog_client import PosthogClient
    from app.core.scheduler import scheduler
    
    scheduler.shutdown()
    PosthogClient.shutdown()
    logger.info("Shutting down application")

