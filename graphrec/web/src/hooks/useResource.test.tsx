import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { setTenantSession } from '../auth/session';
import { tokenPair } from '../test/helpers';
import { SessionProvider } from './useSession';
import { useResource } from './useResource';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function Probe({ id, loader }: { id: string; loader: () => Promise<string> }) {
  const data = useResource(loader, [id]);
  return <div>{data.data ?? 'Loading new data'}</div>;
}

describe('resource isolation', () => {
  it('hides old route data while the new route is loading', async () => {
    const next = deferred<string>();
    const view = render(<SessionProvider><Probe id="a" loader={async () => 'Record A'} /></SessionProvider>);
    expect(await screen.findByText('Record A')).toBeInTheDocument();
    view.rerender(<SessionProvider><Probe id="b" loader={() => next.promise} /></SessionProvider>);
    expect(screen.queryByText('Record A')).not.toBeInTheDocument();
    await act(async () => next.resolve('Record B'));
    expect(screen.getByText('Record B')).toBeInTheDocument();
  });
  it('ignores late responses from an earlier identity', async () => {
    const old = deferred<string>(); const next = deferred<string>();
    setTenantSession('a@example.org', tokenPair({ access_token: 'tenant-a' }));
    const view = render(<SessionProvider><Probe id="same" loader={() => old.promise} /></SessionProvider>);
    await act(async () => setTenantSession('b@example.org', tokenPair({ access_token: 'tenant-b' })));
    view.rerender(<SessionProvider><Probe id="different" loader={() => next.promise} /></SessionProvider>);
    await act(async () => old.resolve('Private tenant A record'));
    expect(screen.queryByText('Private tenant A record')).not.toBeInTheDocument();
    await act(async () => next.resolve('Tenant B record'));
    expect(screen.getByText('Tenant B record')).toBeInTheDocument();
  });
  it('clears already loaded data immediately when the session changes', async () => {
    const next = deferred<string>();
    setTenantSession('a@example.org', tokenPair({ access_token: 'a' }));
    let loader = async () => 'Tenant A';
    render(<SessionProvider><Probe id="catalog" loader={() => loader()} /></SessionProvider>);
    expect(await screen.findByText('Tenant A')).toBeInTheDocument();
    loader = () => next.promise;
    await act(async () => setTenantSession('b@example.org', tokenPair({ access_token: 'b' })));
    expect(screen.queryByText('Tenant A')).not.toBeInTheDocument();
    await act(async () => next.resolve('Tenant B'));
    expect(screen.getByText('Tenant B')).toBeInTheDocument();
  });
});
