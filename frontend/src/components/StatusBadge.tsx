type StatusBadgeProps = {
  status: string;
  /** Use when a data table must expose the source-system value verbatim. */
  displayLabel?: string;
};

const labels: Record<string, string> = {
  CONFIRMED: 'Ready to share',
  POTENTIAL: 'Needs confirmation',
  SUSPENDED: 'On hold',
  CLOSED: 'Closed',
  OPEN: 'Needed',
  ELIGIBLE: 'Good fit',
  REVIEW_REQUIRED: 'Check details',
  INELIGIBLE: 'Not suitable',
  REQUESTED: 'Request sent',
  APPROVED: 'Approved',
  RESERVED: 'Held for project',
  IN_TRANSIT: 'On the way',
  RECEIVED: 'Delivered',
  REUSED: 'Reused',
  CANCELLED: 'Cancelled',
  ACCEPTED: 'Checked',
  REJECTED: 'Needs correction',
  SIMULATED: 'Sample record',
  DEMO: 'Estimated',
  INSUFFICIENT_DATA: 'Missing details',
  SUCCEEDED: 'Plans ready',
  PENDING: 'Waiting',
};

export const statusLabel = (status: string) =>
  labels[status] ?? status.replaceAll('_', ' ').toLowerCase();

export default function StatusBadge({ status, displayLabel }: StatusBadgeProps) {
  const tone =
    status === 'CONFIRMED' || status === 'REUSED' || status === 'ELIGIBLE' || status === 'ACCEPTED' || status === 'APPROVED'
      ? 'positive'
      : status === 'RESERVED' || status === 'IN_TRANSIT' || status === 'RECEIVED'
        ? 'progress'
        : status === 'POTENTIAL' || status === 'REVIEW_REQUIRED' || status === 'PENDING' || status === 'INSUFFICIENT_DATA'
        ? 'caution'
        : status === 'INELIGIBLE' || status === 'CANCELLED' || status === 'REJECTED' || status === 'SUSPENDED'
          ? 'negative'
          : 'neutral';

  return <span className={`status status--${tone}`}><i aria-hidden="true" />{displayLabel ?? statusLabel(status)}</span>;
}
