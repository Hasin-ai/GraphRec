import { JOB_STAGES } from '../lib/enums';

export interface StageRailProps {
  /**
   * The stages, in order. Defaults to the nine training stages.
   *
   * Overridden only by the submission page, whose lifecycle is a different
   * four-stage vocabulary from the same generator. The alternative — a second
   * rail component — would have meant two sets of state classes to keep in
   * step, and the stages are the only thing that differs.
   */
  stages?: readonly string[];
  /** Names the list for a screen reader; the vocabulary decides the wording. */
  label?: string;
  /** The stage the server named, e.g. `training`. `null` before the job starts. */
  current: string | null;
  /** True once the job has failed, which paints the current stage as the failure. */
  failed?: boolean;
  /** True once the job has succeeded, which paints every stage as done. */
  complete?: boolean;
}

/**
 * The nine training stages, in the order `scripts/gen_enums.py` extracted them
 * from the prototype. The order is data rather than a literal here so that a
 * tenth stage is a regeneration and not an edit to this file.
 *
 * The rail shows where a job *is*, not how far along it is: there is no
 * percentage, because the backend does not report one and a made-up one is a
 * lie that a reader will time their afternoon by.
 */
export function StageRail({
  current,
  failed = false,
  complete = false,
  stages = JOB_STAGES,
  label = 'Training stages',
}: StageRailProps) {
  const index = current ? stages.indexOf(current) : -1;

  return (
    <ol className="stagerail" aria-label={label}>
      {stages.map((stage, position) => {
        const state = complete
          ? 'done'
          : position < index
            ? 'done'
            : position === index
              ? failed
                ? 'failed'
                : 'current'
              : 'pending';
        return (
          <li
            key={stage}
            className={`stagerail__stage stagerail__stage--${state}`}
            aria-current={state === 'current' || state === 'failed' ? 'step' : undefined}
          >
            <span className="stagerail__index">
              {position + 1}/{stages.length}
            </span>
            <span>{stage.replace(/_/g, ' ')}</span>
            <span className="visually-hidden">
              {state === 'done'
                ? 'completed'
                : state === 'current'
                  ? 'in progress'
                  : state === 'failed'
                    ? 'failed'
                    : 'not started'}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
