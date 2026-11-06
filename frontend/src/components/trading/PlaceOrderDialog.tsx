import { useAuth } from "@/contexts/AuthContext";
import { errorMessage } from "@/lib/apiError";
import { useEffect, useState, useId } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { placeOrder } from "@/api/optionchain";
import { roundToTick, adjustPrice, formatPrice } from "@/lib/price";
import { cn } from "@/lib/utils";

const PRICE_TYPES = [
  { value: "MARKET", label: "Market" },
  { value: "LIMIT", label: "Limit" },
  { value: "SL-M", label: "SL-M" },
  { value: "SL", label: "SL-L" },
] as const;

const FNO_PRODUCTS = [
  { value: "NRML", label: "NRML" },
  { value: "MIS", label: "MIS" },
] as const;

const EQUITY_PRODUCTS = [
  { value: "MIS", label: "MIS" },
] as const;

type PriceType = (typeof PRICE_TYPES)[number]["value"];
type Product = "MIS" | "NRML" | "CNC";

export interface PlaceOrderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  ltp?: number;
  lotSize: number;
  tickSize: number;
  strategy?: string;
  onSuccess?: (orderid: string) => void;
  disabled?: boolean;
}

function isFnOExchange(exchange: string): boolean {
  return ["MSE", "NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "GIFT", "GLOBAL"].includes(exchange);
}

export function PlaceOrderDialog({
  open,
  onOpenChange,
  symbol,
  exchange,
  action,
  ltp,
  lotSize,
  tickSize,
  strategy = "OptionChain",
  onSuccess,
  disabled = false,
}: PlaceOrderDialogProps) {
  const { user } = useAuth();
  const fieldId = useId();
  const [formAction, setFormAction] = useState<"BUY" | "SELL">(action);
  const [quantityMode, setQuantityMode] = useState<"lots" | "shares">("lots");
  const [lots, setLots] = useState(1);
  const [priceType, setPriceType] = useState<PriceType>("MARKET");
  const [product, setProduct] = useState<Product>(
    isFnOExchange(exchange) ? "NRML" : "MIS"
  );
  const [price, setPrice] = useState(0);
  const [triggerPrice, setTriggerPrice] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const productOptions = isFnOExchange(exchange) ? FNO_PRODUCTS.filter(p => p.value !== "MIS" || !["MSE", "GIFT", "GLOBAL", "CRYPTO"].includes(exchange)) : EQUITY_PRODUCTS;
  const totalQty = lots * lotSize;
  const needsPrice = priceType === "LIMIT" || priceType === "SL";
  const needsTrigger = priceType === "SL" || priceType === "SL-M";

  useEffect(() => {
    if (!open) return;
    setFormAction(action);
    setQuantityMode("lots");
    setLots(1);
    setPriceType("MARKET");
    setProduct(isFnOExchange(exchange) ? "NRML" : "MIS");
    setPrice(ltp ? roundToTick(ltp, tickSize) : 0);
    setTriggerPrice(0);
  }, [open, action, exchange, ltp, tickSize]);

  const isValid = (): boolean => {
    if (!symbol || !exchange) return false;
    if (totalQty <= 0) return false;
    if (needsPrice && price <= 0) return false;
    if (needsTrigger && triggerPrice <= 0) return false;
    return true;
  };

  const handleQuantityChange = (raw: string) => {
    const n = parseInt(raw, 10) || 0;
    if (quantityMode === "lots") {
      setLots(Math.max(1, n));
    } else {
      const rounded = Math.max(lotSize, Math.round(n / lotSize) * lotSize);
      setLots(rounded / lotSize);
    }
  };

  const handleSubmit = async () => {
    if (disabled || !isValid()) {
      toast.error("Please fill all required fields");
      return;
    }
    setSubmitting(true);
    try {
      const resp = await placeOrder({
        strategy,
        symbol,
        exchange,
        action: formAction,
        quantity: totalQty,
        pricetype: priceType,
        product,
        ...(needsPrice ? { price } : {}),
        ...(needsTrigger ? { trigger_price: triggerPrice } : {}),
      });
      if (resp.status === "success" && resp.orderid) {
        toast.success(`Paper order placed: ${resp.orderid}`);
        onSuccess?.(resp.orderid);
        onOpenChange(false);
      } else {
        toast.error(resp.message ?? "Order placement failed");
      }
    } catch (err: unknown) {
      toast.error(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const displayQty = quantityMode === "lots" ? lots : totalQty;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm">
            <span>Paper Order —</span>
            <span
              className={
                formAction === "BUY"
                  ? "text-green-700 font-semibold"
                  : "text-red-700 font-semibold"
              }
            >
              {formAction}
            </span>
            <span className="text-muted-foreground font-normal truncate">{symbol}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {user?.role === "user" && <p className="text-sm leading-relaxed text-muted-foreground">Brokerage is 4% of executed trade value on every buy and sell: 3% to your broker and 1% to Super Admin. Charges are deducted from your virtual funds when a fill executes.</p>}
          {ltp !== undefined && (
            <div className="rounded-md bg-muted/50 px-3 py-2 text-xs flex justify-between">
              <span className="text-muted-foreground">LTP</span>
              <span className="font-mono font-semibold">{formatPrice(ltp)}</span>
            </div>
          )}

          {/* Action toggle */}
          <div className="space-y-1.5">
            <span className="text-xs font-medium">Action</span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={formAction === "BUY" ? "default" : "outline"}
                className={cn(
                  "flex-1",
                  formAction === "BUY" && "bg-green-700 text-white hover:bg-green-800"
                )}
                onClick={() => setFormAction("BUY")}
              >
                BUY
              </Button>
              <Button
                type="button"
                variant={formAction === "SELL" ? "default" : "outline"}
                className={cn(
                  "flex-1",
                  formAction === "SELL" && "bg-red-700 text-white hover:bg-red-800"
                )}
                onClick={() => setFormAction("SELL")}
              >
                SELL
              </Button>
            </div>
          </div>

          {/* Quantity */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor={fieldId + "-quantity"} className="text-xs">Quantity</Label>
              <div className="flex gap-1">
                <button
                  type="button"
                  onClick={() => setQuantityMode("lots")}
                  className={cn(
                    "px-2 py-0.5 text-[10px] rounded",
                    quantityMode === "lots"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-muted/80"
                  )}
                >
                  Lots
                </button>
                <button
                  type="button"
                  onClick={() => setQuantityMode("shares")}
                  className={cn(
                    "px-2 py-0.5 text-[10px] rounded",
                    quantityMode === "shares"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-muted/80"
                  )}
                >
                  Shares
                </button>
              </div>
            </div>
            <Input
              id={fieldId + "-quantity"}
              type="number"
              value={displayQty}
              onChange={(e) => handleQuantityChange(e.target.value)}
              min={1}
            />
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>Lot size: {lotSize}</span>
              <span>Total qty: {totalQty}</span>
            </div>
          </div>

          {/* Price type + product */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-price-type"} className="text-xs">Price Type</Label>
              <select
                id={fieldId + "-price-type"}
                value={priceType}
                onChange={(e) => setPriceType(e.target.value as PriceType)}
                className="h-8 w-full rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {PRICE_TYPES.map((pt) => (
                  <option key={pt.value} value={pt.value}>
                    {pt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-product"} className="text-xs">Product</Label>
              <select
                id={fieldId + "-product"}
                value={product}
                onChange={(e) => setProduct(e.target.value as Product)}
                className="h-8 w-full rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {productOptions.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {needsPrice && (
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-price"} className="text-xs">Price</Label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  aria-label="Decrease price by one tick"
                  onClick={() => setPrice(adjustPrice(price, tickSize, "down"))}
                >
                  −
                </Button>
                <Input
                  type="number"
                  id={fieldId + "-price"}
                  value={price}
                  onChange={(e) => setPrice(parseFloat(e.target.value) || 0)}
                  onBlur={() => setPrice(roundToTick(price, tickSize))}
                  className="flex-1 text-center"
                  step={tickSize}
                  min={0}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  aria-label="Increase price by one tick"
                  onClick={() => setPrice(adjustPrice(price, tickSize, "up"))}
                >
                  +
                </Button>
              </div>
              <p className="text-[10px] text-muted-foreground">Tick size: {tickSize}</p>
            </div>
          )}

          {needsTrigger && (
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-trigger-price"} className="text-xs">Trigger Price</Label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  aria-label="Decrease trigger price by one tick"
                  onClick={() => setTriggerPrice(adjustPrice(triggerPrice, tickSize, "down"))}
                >
                  −
                </Button>
                <Input
                  type="number"
                  id={fieldId + "-trigger-price"}
                  value={triggerPrice}
                  onChange={(e) => setTriggerPrice(parseFloat(e.target.value) || 0)}
                  onBlur={() => setTriggerPrice(roundToTick(triggerPrice, tickSize))}
                  className="flex-1 text-center"
                  step={tickSize}
                  min={0}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  aria-label="Increase trigger price by one tick"
                  onClick={() => setTriggerPrice(adjustPrice(triggerPrice, tickSize, "up"))}
                >
                  +
                </Button>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={disabled || !isValid() || submitting}
            className={cn(
              formAction === "BUY"
                ? "bg-green-700 text-white hover:bg-green-800"
                : "bg-red-700 text-white hover:bg-red-800"
            )}
          >
            {submitting ? "Placing…" : `Place ${formAction} Order`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
