/**
 * Turn an order webhook into purchase events that are safe to replay.
 *
 * Payment providers and shop platforms retry webhooks. Because each purchase
 * event ID is derived from `(orderId, line)`, GraphRec records every order line
 * exactly once no matter how often the webhook is delivered.
 *
 * The API key needs the `events:write` scope.
 *
 *   npm run build && node examples/order-webhook.ts
 */
import { GraphRec } from "@graphrec/sdk";
import { EventBuilder } from "@graphrec/sdk/ecommerce";

interface OrderLine {
  sku: string;
  quantity: number;
  unit_price: string;
}

interface Order {
  id: string;
  customer_id?: string | null;
  currency?: string;
  lines: OrderLine[];
}

const builder = new EventBuilder({ defaultContext: { channel: "web" } });

export async function handleOrderPaid(client: GraphRec, order: Order): Promise<void> {
  const events = order.lines.map((line, index) =>
    builder.purchase(order.customer_id ?? null, line.sku, {
      orderId: order.id,
      line: index + 1,
      quantity: line.quantity,
      price: line.unit_price,
      currency: order.currency,
    }),
  );
  const result = await client.events.createBatch(events);
  console.log(`order ${order.id}: accepted=${result.accepted_count} duplicates=${result.duplicate_count}`);
}

const sample: Order = {
  id: "ORD-2001",
  customer_id: "customer-42",
  currency: "EUR",
  lines: [
    { sku: "sku-101", quantity: 1, unit_price: "59.00" },
    { sku: "sku-102", quantity: 2, unit_price: "79.00" },
  ],
};

const client = new GraphRec();
await handleOrderPaid(client, sample);
await handleOrderPaid(client, sample); // replay -> duplicates, no double counting
