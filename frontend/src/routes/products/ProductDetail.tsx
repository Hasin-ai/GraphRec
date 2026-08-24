/**
 * `/products/:externalId` — one product, its eligibility, and disabling it.
 *
 * A foreign product and a missing one both arrive here as a 404 and both
 * render `/404` (§13). This page never distinguishes them, which is why the
 * loader's failure is not caught into a nicer message.
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { disableProduct, useProduct, useProductMutation } from '../../api/hooks/catalogue';
import type { Product } from '../../api/hooks/catalogue';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import {
  Banner,
  Breadcrumbs,
  Button,
  DefinitionList,
  Dialog,
  Textarea,
  ToneBadge,
} from '../../ui';
import { ProductForm } from './ProductForm';
import { useSubmit } from '../../lib/useSubmit';
import { formatDateTime, humanise } from '../../lib/format';

export function ProductDetailRoute() {
  const { productId = '' } = useParams();
  const query = useProduct(productId);

  return (
    <div className="page">
      <Breadcrumbs
        crumbs={[{ label: 'Catalogue', to: '/products' }, { label: query.data?.title ?? 'Product' }]}
      />
      <QueryState query={query} label="this product">
        {(product) => <ProductPanel product={product} />}
      </QueryState>
    </div>
  );
}

function ProductPanel({ product }: { product: Product }) {
  const [editing, setEditing] = useState(false);
  const [disabling, setDisabling] = useState(false);

  return (
    <>
      <div className="page__head">
        <h1 className="page__title">{product.title}</h1>
        <p className="page__lede">
          <code>{product.external_id}</code>
        </p>
      </div>

      {/* Eligibility first, because it is the only thing on this page that
          decides whether the product does anything. */}
      <Banner kind={product.eligible ? 'success' : 'warning'}>
        {product.eligible
          ? 'Recommendable. This product can appear in recommendations.'
          : (product.ineligibility ??
            product.exclusion_reason ??
            'Not recommendable. Check that it is active, in stock and priced.')}
      </Banner>

      {editing ? (
        <ProductForm
          existing={product}
          onSaved={() => setEditing(false)}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <DefinitionList
            items={[
              { term: 'Description', value: product.description ?? '—' },
              { term: 'Category', value: product.category ?? '—' },
              { term: 'Brand', value: product.brand ?? '—' },
              { term: 'Price', value: product.price ?? '—' },
              { term: 'Availability', value: humanise(product.availability) },
              {
                term: 'Active',
                value: (
                  <ToneBadge tone={product.active ? 'ok' : 'neu'}>
                    {product.active ? 'active' : 'disabled'}
                  </ToneBadge>
                ),
              },
              { term: 'Created', value: formatDateTime(product.created_at) },
              { term: 'Updated', value: formatDateTime(product.updated_at) },
              ...(product.disabled_at
                ? [
                    { term: 'Disabled', value: formatDateTime(product.disabled_at) },
                    { term: 'Disabled because', value: product.disabled_reason ?? '—' },
                  ]
                : []),
              ...(product.blocked_reason
                ? [{ term: 'Blocked', value: product.blocked_reason }]
                : []),
            ]}
          />

          <div className="action-row">
            <Button onClick={() => setEditing(true)}>Edit</Button>
            <GatedAction
              label="Disable"
              allowed={product.can_disable}
              reason="This product is already disabled."
              onClick={() => setDisabling(true)}
            />
          </div>
        </>
      )}

      {disabling ? (
        <DisableDialog product={product} onClose={() => setDisabling(false)} />
      ) : null}
    </>
  );
}

/**
 * Disabling asks for a reason, and the reason is required.
 *
 * It is not a validation flourish. The row keeps `disabled_reason` and the
 * detail page shows it, so the next person to ask "why is this not being
 * recommended?" reads the answer instead of guessing at a date.
 */
function DisableDialog({ product, onClose }: { product: Product; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const mutation = useProductMutation((body: { reason: string }) =>
    disableProduct(product.external_id, body),
  );
  const form = useSubmit<Product>(
    (body: { reason: string }) => mutation.mutateAsync(body),
    onClose,
  );

  return (
    <Dialog
      title={`Disable ${product.title}`}
      onClose={onClose}
      confirmLabel="Disable"
      confirmVariant="danger"
      busy={form.pending}
      confirmDisabled={reason.trim().length < 4}
      onConfirm={() => form.submit({ reason: reason.trim() })}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p className="page__lede">
        It stops being recommendable immediately. Nothing is deleted — events that reference it keep
        working, and re-enabling it is an edit away.
      </p>
      <Textarea
        label="Reason"
        required
        rows={3}
        value={reason}
        error={form.fieldErrors.reason}
        onChange={(event) => setReason(event.target.value)}
        hint="Kept on the product, and shown to whoever asks why it stopped appearing."
      />
    </Dialog>
  );
}
