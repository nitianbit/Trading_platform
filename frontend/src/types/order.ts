export interface FundsData {
  availablecash: number;
  brokerage_paid: number;
  gross_realized_pnl: number;
  collateral: number;
  m2munrealized: number;
  m2mrealized: number;
  utiliseddebits: number;
}

export interface OrderbookItem {
  symbol: string;
  exchange: string;
  action: string;
  product: string;
  pricetype: string;
  quantity: number;
  price: number;
  trigger_price: number;
  orderid: string;
  order_status: string;
  timestamp: string;
}

export interface TradebookItem {
  brokerage: number;
  broker_credit: number;
  admin_credit: number;
  symbol: string;
  exchange: string;
  action: string;
  product: string;
  quantity: number;
  average_price: number;
  trade_value: number;
  orderid: string;
  timestamp: string;
}

export interface PositionItem {
  symbol: string;
  exchange: string;
  product: string;
  quantity: number;
  average_price: number;
  ltp: number;
  pnl: number;
}

export interface HoldingItem {
  symbol: string;
  exchange: string;
  quantity: number;
  product: string;
  average_price: number;
  ltp: number;
  pnl: number;
  pnlpercent: number;
}
