import { Field, TextInput } from "./Form";

/** ER-F-11: a human reason stored with the action's audit record. */
export function ReasonField({ id, value, onChange, required = false }: { id: string; value: string; onChange: (value: string) => void; required?: boolean }) {
  return (
    <Field id={id} label={required ? "Reason" : "Reason (optional)"} hint="Saved with the audit record for this action. Do not include passwords or personal data.">
      <TextInput id={id} value={value} onChange={onChange} required={required} />
    </Field>
  );
}
