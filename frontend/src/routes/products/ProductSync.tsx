/**
 * `/products/sync` — the whole catalogue in one request.
 *
 * The mode selector is the only decision on this page and it is the dangerous
 * one: `upsert_and_disable_missing` disables every product absent from the
 * payload. That is the correct behaviour for a nightly full export and a
 * catastrophe for a partial one, so the two modes are described by what they
 * do to products you did not send, not by their names.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { bulkUpsertProducts, useProductMutation } from '../../api/hooks/catalogue';
import type { Submission } from '../../api/hooks/catalogue';
import type { S } from '../../api/schema';
import { Banner, Breadcrumbs, Button, Select, Textarea } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';

const EXAMPLE = `[
  {
    "external_id": "sku-1",
    "title": "Example product",
    "category": "example",
    "price": "19.99",
    "availability": "in_stock",
    "active": true
  }
]`;

const MODES = [
  { value: 'upsert', label: 'Add and update only — products you leave out are untouched' },
  {
    value: 'upsert_and_disable_missing',
    label: 'Full replace — products you leave out are disabled',
  },
];

export function ProductSyncRoute() {
  const navigate = useNavigate();
  const [text, setText] = useState(EXAMPLE);
  const [mode, setMode] = useState('upsert');
  const [parseError, setParseError] = useState<string | null>(null);

  const mutation = useProductMutation((body: S['BulkUpsertProductsRequest']) =>
    bulkUpsertProducts(body),
  );
  const form = useSubmit<Submission>(
    (body: S['BulkUpsertProductsRequest']) => mutation.mutateAsync(body),
    // `void`: the success callback is typed `(x) => void` and `navigate`
    // returns a promise. Nothing here awaits the transition.
    (submission) => void navigate(`/submissions/${submission.submission_id}`),
  );

  return (
    <div className="page">
      <Breadcrumbs crumbs={[{ label: 'Catalogue', to: '/products' }, { label: 'Bulk sync' }]} />
      <div className="page__head">
        <h1 className="page__title">Bulk sync</h1>
        <p className="page__lede">
          Send your catalogue as a JSON array. The request is accepted for processing rather than
          applied on the spot, so you get a submission to watch and a per-product list of anything
          that was rejected.
        </p>
      </div>

      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          setParseError(null);
          let products: unknown[];
          try {
            const parsed: unknown = JSON.parse(text);
            if (!Array.isArray(parsed)) {
              setParseError('The payload must be a JSON array of products.');
              return;
            }
            products = parsed;
          } catch (caught) {
            setParseError(caught instanceof Error ? caught.message : 'That is not valid JSON.');
            return;
          }
          form.submit({
            // The sync ID is the idempotency key for the whole batch: resending
            // the same one after a timeout confirms the first attempt rather
            // than applying the catalogue twice.
            sync_id: crypto.randomUUID(),
            mode: mode as S['BulkUpsertProductsRequest']['mode'],
            products,
          });
        }}
      >
        {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
        {mode === 'upsert_and_disable_missing' ? (
          <Banner kind="warning">
            Every product not in this payload will be disabled. Use this only when you are sending
            your entire catalogue.
          </Banner>
        ) : null}

        <Select
          label="Mode"
          value={mode}
          options={MODES}
          onChange={(event) => setMode(event.target.value)}
        />
        <Textarea
          label="Products"
          rows={16}
          value={text}
          error={parseError ?? form.fieldErrors.products}
          onChange={(event) => setText(event.target.value)}
        />
        <div className="action-row">
          <Button type="submit" disabled={form.pending}>
            {form.pending ? 'Submitting…' : 'Sync catalogue'}
          </Button>
          <Button type="button" variant="secondary" onClick={() => navigate('/products')}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}
