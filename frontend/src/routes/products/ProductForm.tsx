/**
 * `/products/new` and the edit form on `/products/:externalId`.
 *
 * One component for both, because the difference between creating and editing
 * a product here is which verb the request uses: `external_id` is the caller's
 * own identifier, so a `PUT` to an ID that does not exist is a create in every
 * sense that matters. Splitting them into two forms would duplicate eight
 * fields to express that one distinction.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createProduct, updateProduct, useProductMutation } from '../../api/hooks/catalogue';
import type { Product } from '../../api/hooks/catalogue';
import type { S } from '../../api/schema';
import { Banner, Breadcrumbs, Button, Input, Select, Textarea } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';

const AVAILABILITY_OPTIONS = [
  { value: 'in_stock', label: 'In stock' },
  { value: 'low_stock', label: 'Low stock' },
  { value: 'out_of_stock', label: 'Out of stock' },
];

export interface ProductFormProps {
  /** Absent on `/products/new`. */
  existing?: Product;
  onSaved?: (product: Product) => void;
  onCancel?: () => void;
}

export function ProductFormRoute() {
  const navigate = useNavigate();
  return (
    <div className="page">
      <Breadcrumbs crumbs={[{ label: 'Catalogue', to: '/products' }, { label: 'Add product' }]} />
      <div className="page__head">
        <h1 className="page__title">Add product</h1>
        <p className="page__lede">
          One product, by hand. This is here so the shape is visible; a real catalogue arrives
          through bulk sync or the API.
        </p>
      </div>
      <ProductForm
        onSaved={(product) => navigate(`/products/${encodeURIComponent(product.external_id)}`)}
        onCancel={() => navigate('/products')}
      />
    </div>
  );
}

export function ProductForm({ existing, onSaved, onCancel }: ProductFormProps) {
  const [externalId, setExternalId] = useState(existing?.external_id ?? '');
  const [title, setTitle] = useState(existing?.title ?? '');
  const [description, setDescription] = useState(existing?.description ?? '');
  const [category, setCategory] = useState(existing?.category ?? '');
  const [brand, setBrand] = useState(existing?.brand ?? '');
  const [price, setPrice] = useState(existing?.price ?? '');
  const [availability, setAvailability] = useState(existing?.availability ?? 'in_stock');
  const [active, setActive] = useState(existing?.active ?? true);

  const mutation = useProductMutation((body: S['CreateProductRequest']) =>
    existing ? updateProduct(existing.external_id, body) : createProduct(body),
  );
  const form = useSubmit<Product>(
    (body: S['CreateProductRequest']) => mutation.mutateAsync(body),
    (product) => onSaved?.(product),
  );

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        form.submit({
          external_id: externalId.trim(),
          title: title.trim(),
          description: description.trim() || null,
          category: category.trim() || null,
          brand: brand.trim() || null,
          // Sent as a string. The price is a decimal on the server and going
          // through a JavaScript number to get there is how a price becomes
          // 19.989999999999998.
          price: price === '' ? null : String(price),
          availability: availability,
          active,
        });
      }}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}

      <Input
        label="Your product ID"
        required
        value={externalId}
        disabled={Boolean(existing)}
        error={form.fieldErrors.external_id}
        onChange={(event) => setExternalId(event.target.value)}
        hint={
          existing
            ? 'The ID cannot change — events already reference it.'
            : 'Whatever identifies this product in your own systems. Events reference this, not an ID we invent.'
        }
      />
      <Input
        label="Title"
        required
        value={title}
        error={form.fieldErrors.title}
        onChange={(event) => setTitle(event.target.value)}
      />
      <Textarea
        label="Description"
        rows={3}
        value={description}
        error={form.fieldErrors.description}
        onChange={(event) => setDescription(event.target.value)}
      />
      <Input
        label="Category"
        value={category}
        error={form.fieldErrors.category}
        onChange={(event) => setCategory(event.target.value)}
      />
      <Input
        label="Brand"
        value={brand}
        error={form.fieldErrors.brand}
        onChange={(event) => setBrand(event.target.value)}
      />
      <Input
        label="Price"
        inputMode="decimal"
        value={String(price)}
        error={form.fieldErrors.price}
        onChange={(event) => setPrice(event.target.value)}
        hint="A product without a price is not recommendable."
      />
      <Select
        label="Availability"
        value={availability}
        options={AVAILABILITY_OPTIONS}
        error={form.fieldErrors.availability}
        onChange={(event) => setAvailability(event.target.value as S['Availability'])}
        hint="Out of stock is not recommendable, and stays in the catalogue rather than disappearing from it."
      />

      <label className="checkline">
        <input
          type="checkbox"
          checked={active}
          onChange={(event) => setActive(event.target.checked)}
        />
        <span>Active — may be recommended, subject to price and stock</span>
      </label>

      <div className="action-row">
        <Button type="submit" disabled={form.pending}>
          {form.pending ? 'Saving…' : existing ? 'Save changes' : 'Add product'}
        </Button>
        {onCancel ? (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}
