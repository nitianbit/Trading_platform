"""
Order placement service - places, modifies, cancels orders via broker APIs.
Dual-entry pattern: place_order_with_auth() + place_order()
"""

import copy
import logging
from typing import Any

from backend.utils.constants import (
    VALID_ACTIONS,
    VALID_EXCHANGES,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
)

logger = logging.getLogger(__name__)

REQUIRED_ORDER_FIELDS = ["symbol", "exchange", "action", "quantity", "pricetype", "product"]


def validate_order_data(data: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate order data against required fields and valid values.

    Returns:
        (is_valid, error_message)
    """
    missing_fields = [field for field in REQUIRED_ORDER_FIELDS if field not in data]
    if missing_fields:
        return False, f"Missing mandatory field(s): {', '.join(missing_fields)}"

    if data.get("exchange") not in VALID_EXCHANGES:
        return False, f"Invalid exchange. Must be one of: {', '.join(sorted(VALID_EXCHANGES))}"

    if "action" in data:
        data["action"] = data["action"].upper()
        if data["action"] not in VALID_ACTIONS:
            return False, f"Invalid action. Must be one of: {', '.join(sorted(VALID_ACTIONS))}"

    if data.get("pricetype") not in VALID_PRICE_TYPES:
        return False, f"Invalid pricetype. Must be one of: {', '.join(sorted(VALID_PRICE_TYPES))}"

    if data.get("product") not in VALID_PRODUCT_TYPES:
        return False, f"Invalid product. Must be one of: {', '.join(sorted(VALID_PRODUCT_TYPES))}"

    return True, None


def _paper(operation: str, user_id: int | None, *args):
    if user_id is None or user_id <= 0:
        return False, {"status": "error", "message": "An authenticated platform account is required"}, 401
    from backend.services import sandbox_service
    return getattr(sandbox_service, operation)(user_id, *args)


def place_order_with_auth(order_data, auth_token, broker, config=None, user_id=None):
    valid, reason = validate_order_data(order_data)
    if not valid:
        return False, {"status": "error", "message": reason}, 400
    return _paper("place_order", user_id, order_data)


def place_order(order_data, api_key=None, auth_token=None, broker=None, config=None, user_id=None):
    return place_order_with_auth(order_data, auth_token, broker, config, user_id)


def place_smart_order(order_data, auth_token, broker, config=None, user_id=None):
    return _paper("place_smart_order", user_id, order_data)


def modify_order_service(data, auth_token, broker, config=None, user_id=None):
    return _paper("modify_order", user_id, data)


def cancel_order_service(orderid, auth_token, broker, config=None, user_id=None):
    return _paper("cancel_order", user_id, orderid)


def cancel_all_orders_service(auth_token, broker, config=None, user_id=None):
    return _paper("cancel_all_orders", user_id)


def close_all_positions_service(api_key, auth_token, broker, config=None, user_id=None):
    return _paper("close_all_positions", user_id)
