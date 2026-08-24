/**
 * One submit handler for every form in the console.
 *
 * Forms here all behave the same way on failure, and it is worth writing down
 * why once rather than in fifteen components:
 *
 * * The banner text is `error.reason` — the server's sentence, resolved from
 *   `graphrec/common/error_copy.py`. The console never writes its own copy for
 *   a refusal, so the API and the UI cannot drift into disagreeing about what
 *   just happened.
 * * `field_errors` are attached to inputs by name, so a correction is made
 *   where it is needed rather than hunted for.
 * * **The form keeps its values.** §7 requires it for `/register` and it is
 *   right everywhere: clearing a form on rejection makes the user retype work
 *   the server has already told them is nearly correct.
 */

import { useCallback, useState } from 'react';
import { ApiError, isApiError } from '../api/errors';

export interface SubmitState<Output> {
  pending: boolean;
  error: ApiError | null;
  fieldErrors: Record<string, string>;
  data: Output | null;
  submit: (input: unknown) => void;
  reset: () => void;
}

export function useSubmit<Output>(
  action: (input: never) => Promise<Output>,
  onSuccess?: (output: Output) => void,
): SubmitState<Output> {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [data, setData] = useState<Output | null>(null);

  const submit = useCallback(
    (input: unknown) => {
      setPending(true);
      setError(null);
      void (async () => {
        try {
          const output = await action(input as never);
          setData(output);
          onSuccess?.(output);
        } catch (caught) {
          if (isApiError(caught)) {
            setError(caught);
          } else {
            // Something that is not a transport failure — a bug in this bundle.
            // It still has to reach the user as a refusal rather than a frozen
            // button, so it is wrapped in the same envelope shape.
            setError(
              new ApiError(0, {
                class: 'internal',
                code: 'console_error',
                reason: 'The console could not complete that. Reload the page and try again.',
                reference: 'console',
                field_errors: [],
                retryable: true,
                retry_after_seconds: null,
              }),
            );
          }
        } finally {
          setPending(false);
        }
      })();
    },
    [action, onSuccess],
  );

  const reset = useCallback(() => {
    setError(null);
    setData(null);
  }, []);

  return {
    pending,
    error,
    fieldErrors: error ? error.fieldErrors() : {},
    data,
    submit,
    reset,
  };
}
