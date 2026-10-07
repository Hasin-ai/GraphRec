import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '../hooks/useToast';
import { Dialog, SecretDialog } from './Dialog';
import { Field, TextInput } from './Form';

describe('modal and form accessibility', () => {
  it('contains keyboard focus in the one-time secret dialog', async () => {
    const user = userEvent.setup(); const close = vi.fn();
    render(<ToastProvider><SecretDialog title="Created" secret="test-only-secret" prefix="test" scopes="1 operation" onClose={close} /></ToastProvider>);
    expect(screen.getByRole('button', { name: 'Copy secret' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'I have stored it' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Copy secret' })).toHaveFocus();
    await user.keyboard('{Escape}'); expect(close).not.toHaveBeenCalled();
  });
  it('prevents duplicate submission and dismissal during a mutation', async () => {
    const user = userEvent.setup(); const close = vi.fn();
    let finish!: () => void;
    const confirm = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    render(<Dialog title="Confirm" body="Change state" onConfirm={confirm} onClose={close} />);
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    await user.keyboard('{Escape}');
    await user.click(document.querySelector('.dialog-backdrop')!);
    expect(close).not.toHaveBeenCalled(); expect(confirm).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    await user.keyboard('{Escape}'); expect(close).toHaveBeenCalledTimes(1);
  });
  it('reports clipboard failure rather than a fake success', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValueOnce(new Error('Denied'));
    render(<ToastProvider><SecretDialog title="Created" secret="test" prefix="test" scopes="1" onClose={() => {}} /></ToastProvider>);
    await user.click(screen.getByRole('button', { name: 'Copy secret' }));
    expect(await screen.findByText(/Could not copy/)).toBeInTheDocument();
    expect(screen.queryByText('Copied to clipboard.')).not.toBeInTheDocument();
  });
  it('associates field errors and hints with their input', () => {
    render(<Field id="email" label="Email" error="Use a valid email" hint="Work email"><TextInput id="email" value="" onChange={() => {}} /></Field>);
    const input = screen.getByLabelText('Email');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription('Use a valid email Work email');
  });
});
