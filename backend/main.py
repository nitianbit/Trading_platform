import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.config import get_settings
from backend.database import engine, Base
from backend.exceptions import OpenBullException, openbull_exception_handler
from backend.limiter import limiter
from backend.middleware import RequestLoggingMiddleware
from backend.middleware_api_log import ApiLogMiddleware
from backend.utils.api_log_writer import init_writer as init_api_log_writer, get_writer as get_api_log_writer
from backend.utils.logging import get_logger, setup_logging
from backend.utils.plugin_loader import load_all_plugins
from backend.utils.httpx_client import close_httpx_client
from backend.utils.redis_client import close_redis

settings = get_settings()

# Centralized logging — installs console + rotating file handlers, sensitive-
# data redaction, request-id stamping, and a DB sink for WARNING+ records.
setup_logging(settings)
logger = get_logger("openbull")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Startup
    logger.info("OpenBull starting up...")

    from backend.sandbox._db import get_engine
    if settings.production:
        from backend.paper.readiness import require_migrated
        await asyncio.to_thread(require_migrated, get_engine())
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        from backend.utils.schema_migrations import run_startup_migrations
        await asyncio.to_thread(run_startup_migrations)
        from backend.security import migrate_api_keys
        await asyncio.to_thread(migrate_api_keys, get_engine())

    from backend.paper.market import seed_symbols, publish_quotes, run_feed
    await asyncio.to_thread(seed_symbols)
    await asyncio.to_thread(publish_quotes)
    demo_feed = asyncio.create_task(run_feed())

    # Start the async-safe DB writer for api_logs. The middleware enqueues
    # rows non-blocking; a daemon thread drains the queue and trims the
    # table to settings.api_log_db_max_rows.
    init_api_log_writer(settings.sync_database_url, settings.api_log_db_max_rows)
    logger.info("ApiLogWriter started (max_rows=%d)", settings.api_log_db_max_rows)

    # Seed sandbox_config defaults (starting capital, leverage, squareoff
    # times) if the row isn't already there, and start the tick-driven
    # sandbox execution engine. Safe to call even when trading_mode=live —
    # the engine only fires when sandbox orders exist.
    try:
        from backend.sandbox.config import seed_defaults
        from backend.sandbox.execution_engine import start as start_sandbox_engine
        from backend.sandbox.mtm_updater import start as start_sandbox_mtm
        from backend.sandbox.scheduler import start as start_sandbox_scheduler
        from backend.sandbox.catch_up import run_catch_up_tasks

        seed_defaults()
        # Catch up any scheduled work the app missed while it was down: stale
        # MIS positions, T+1 CNC settlement, today_realized_pnl reset, expired
        # F&O contracts. Runs *before* the engine/scheduler so the first tick
        # sees a consistent book.
        run_catch_up_tasks()
        start_sandbox_engine()
        start_sandbox_scheduler()
        start_sandbox_mtm()
        logger.info("Sandbox: catch-up done; engine + scheduler + MTM updater started")
    except Exception:
        logger.exception("Failed to start sandbox engine/scheduler/MTM")
        raise

    # Wire all event-bus subscribers (strategy audit, future: telegram, etc.).
    # Done after tables exist so audit subscribers can write rows on any
    # publish that happens during plugin load or symbol-cache hydration.
    try:
        from backend.subscribers import register_all as register_event_subscribers

        register_event_subscribers()
    except Exception:
        logger.exception("Failed to register event-bus subscribers")

    # Strategy module: recovery, then tick processor + tick feed, then
    # periodic checkpoints, then scheduler. Order matters — the processor
    # must be alive before the feed starts dispatching, and recovery
    # should run before the first checkpoint pass. Scheduler comes last so
    # any cron firing immediately can already start runs through a fully
    # initialized engine.
    try:
        from backend.strategy import (
            checkpoint as strategy_checkpoint,
            scheduler as strategy_scheduler,
            tick_feed as strategy_tick_feed,
            tick_processor as strategy_tick_processor,
        )
        from backend.strategy.recovery import recover_all as strategy_recover_all

        await strategy_recover_all()
        queue = strategy_tick_processor.start()
        strategy_tick_feed.init(asyncio.get_running_loop(), queue)
        strategy_checkpoint.start()
        await strategy_scheduler.start()
    except Exception:
        logger.exception("Strategy engine startup failed")

    # Load broker plugins
    plugins = load_all_plugins()
    logger.info("Loaded %d broker plugins: %s", len(plugins), list(plugins.keys()))

    # Load symbol cache if symtoken table has data
    try:
        from backend.broker.upstox.mapping.order_data import _load_symbol_cache
        await _load_symbol_cache()
    except Exception as e:
        logger.info("Symbol cache not loaded (will load after master contract download): %s", e)

    # Start WebSocket proxy server in background
    from backend.websocket_proxy.server import start_ws_proxy, shutdown_ws_proxy
    ws_task = asyncio.create_task(
        start_ws_proxy(settings.websocket_host, settings.websocket_port)
    )
    logger.info(
        "WebSocket proxy starting on ws://%s:%d", settings.websocket_host, settings.websocket_port
    )

    yield

    # Shutdown
    demo_feed.cancel()
    try:
        await demo_feed
    except asyncio.CancelledError:
        pass
    await shutdown_ws_proxy()
    ws_task.cancel()
    try:
        await ws_task
    except asyncio.CancelledError:
        pass
    close_httpx_client()
    await close_redis()
    # Drain the api-log queue so in-flight writes make it to the DB.
    w = get_api_log_writer()
    if w is not None:
        w.stop(timeout=2.0)
    try:
        from backend.sandbox.execution_engine import stop as stop_sandbox_engine
        from backend.sandbox.mtm_updater import stop as stop_sandbox_mtm
        from backend.sandbox.scheduler import stop as stop_sandbox_scheduler

        stop_sandbox_scheduler()
        stop_sandbox_mtm()
        stop_sandbox_engine()
    except Exception:
        logger.exception("Error stopping sandbox engine/scheduler/MTM")
    try:
        from backend.strategy import (
            checkpoint as strategy_checkpoint,
            scheduler as strategy_scheduler,
            tick_feed as strategy_tick_feed,
            tick_processor as strategy_tick_processor,
        )

        strategy_scheduler.stop()
        strategy_tick_feed.shutdown()
        await strategy_tick_processor.stop()
        await strategy_checkpoint.stop()
    except Exception:
        logger.exception("Error stopping strategy engine")
    await engine.dispose()
    logger.info("OpenBull shut down")
    # Flush DB error sink before the process exits so in-flight queued
    # WARNING/ERROR records have a chance to persist.
    import logging as _std_logging
    _std_logging.shutdown()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.paper.runtime import single_runtime
    with single_runtime():
        async with _lifespan(app):
            yield


app = FastAPI(
    title="DHK Paper",
    description="Platform-owned virtual trading with synthetic demonstration prices",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings.production else "/docs",
    redoc_url=None if settings.production else "/redoc",
    openapi_url=None if settings.production else "/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(OpenBullException, openbull_exception_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; " +
        ("script-src 'self'; " if settings.production else "script-src 'self' 'unsafe-inline'; ") +
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' wss: ws:; "
        "frame-ancestors 'none'"
    )
    return response


# Auth-gated DB log. Added before the request-id middleware so that
# RequestLoggingMiddleware wraps it — i.e. request_id_var is populated
# before ApiLogMiddleware reads it, and the access-log line still covers
# the full request lifecycle.
app.add_middleware(ApiLogMiddleware)

# Request-id + access log. Added last so it is the outermost wrapper —
# the request_id contextvar is set before any other middleware runs,
# and the latency line covers the full request lifecycle.
app.add_middleware(RequestLoggingMiddleware)


# Register routers
from backend.routers.auth import router as auth_router
from backend.routers.error_logs import router as error_logs_router

app.include_router(auth_router)
app.include_router(error_logs_router)

# Phase 3: Symbol search and master contract download
from backend.routers.symbols import router as symbols_router

app.include_router(symbols_router)

# Phase 4: Core trading web routes
from backend.routers.dashboard import router as dashboard_router
from backend.routers.orderbook import router as orderbook_router
from backend.routers.tradebook import router as tradebook_router
from backend.routers.positions import router as positions_router
from backend.routers.holdings import router as holdings_router

app.include_router(dashboard_router)
app.include_router(orderbook_router)
app.include_router(tradebook_router)
app.include_router(positions_router)
app.include_router(holdings_router)

# Phase 5: API key management and external API
from backend.routers.api_key import router as api_key_router
from backend.api import api_v1_router

app.include_router(api_key_router)
app.include_router(api_v1_router)

# WebSocket support endpoints (config, health, cached ticks)
from backend.routers.websocket import router as websocket_router

app.include_router(websocket_router)

# API request logs (auth-gated, DB-backed; see ApiLogMiddleware)
from backend.routers.api_logs import router as api_logs_router

app.include_router(api_logs_router)

# Live / Sandbox trading-mode toggle
from backend.routers.trading_mode import router as trading_mode_router

app.include_router(trading_mode_router)

# Sandbox configuration + reset
from backend.routers.sandbox import router as sandbox_router

app.include_router(sandbox_router)

# Saved strategies (Strategy Builder + Strategy Portfolio)
from backend.routers.strategies import router as strategies_router
from backend.routers.strategybuilder import router as strategybuilder_router

app.include_router(strategies_router)
app.include_router(strategybuilder_router)

# Strategy module — multi-leg options strategies with risk management
# (separate from the legacy Strategy Builder above)
from backend.routers.strategy_module import router as strategy_module_router
from backend.routers.strategy_webhook import router as strategy_webhook_router
from backend.strategy.ws import router as strategy_ws_router

app.include_router(strategy_module_router)
app.include_router(strategy_webhook_router)
app.include_router(strategy_ws_router)

# Playground — REST + WebSocket tester surfaced at /playground in the SPA.
from backend.routers.playground import router as playground_router

app.include_router(playground_router)


from backend.routers.paper import router as paper_router
app.include_router(paper_router)

# Readiness includes actual dependencies and the synthetic feed heartbeat.
@app.get("/health")
async def health():
    from sqlalchemy import text
    from backend.database import async_session
    from backend.paper.market import feed_is_healthy
    from backend.utils.redis_client import get_redis
    from fastapi.responses import JSONResponse
    checks = {"database": False, "redis": False, "feed": feed_is_healthy()}
    try:
        async with async_session() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=2)
            checks["database"] = True
        checks["redis"] = bool(await asyncio.wait_for(get_redis().ping(), timeout=2))
    except Exception:
        pass
    healthy = all(checks.values())
    return JSONResponse(status_code=200 if healthy else 503, content={
        "status": "ok" if healthy else "degraded", "app": "DHK Paper", "version": "0.1.0",
        "paper_only": True, "data_source": "synthetic_demo", "checks": checks})
