import { Link } from "react-router-dom";
import { categoryLabel, money } from "../lib/format";
import { useStore } from "../lib/store";
import type { Product } from "../lib/types";
import { Tile } from "./Tile";

interface Props {
  product: Product;
  /** Rank badge for recommendation shelves. */
  rank?: number;
  /** Show size next to the price (catalog grid). */
  withMeta?: boolean;
  /** Called before navigation when the card came from a recommendation. */
  onOpen?: () => void;
  /** Hide the add button (order page shelves). */
  noAdd?: boolean;
  compact?: boolean;
}

export function ProductCard({ product, rank, withMeta, onOpen, noAdd, compact }: Props) {
  const { addToCart } = useStore();
  const soldOut = !product.available;
  return (
    <article className="fct-card fct-rise">
      <Link to={`/products/${encodeURIComponent(product.externalId)}`} onClick={onOpen} aria-label={`${product.title}, ${money(product.price)}`}>
        <Tile id={product.externalId} category={product.category} accent={product.accent} dim={soldOut}>
          {rank !== undefined && <span className="fct-tile-badge">#{rank}</span>}
          {soldOut && <span className="fct-tile-badge unavailable">Unavailable</span>}
        </Tile>
        <p className="fct-cat">{categoryLabel(product.category)}</p>
        <p className="fct-name" style={compact ? { fontSize: 17 } : undefined}>
          {product.title}
        </p>
        <p className="fct-meta">{withMeta && product.size && !soldOut ? `${money(product.price)} · ${product.size}` : soldOut ? "Currently unavailable" : money(product.price)}</p>
      </Link>
      {!noAdd && (
        <button type="button" className="btn btn-secondary" disabled={soldOut} onClick={() => addToCart(product, 1)} aria-label={`Add ${product.title} to cart`}>
          {soldOut ? "Unavailable" : "Add"}
        </button>
      )}
    </article>
  );
}
