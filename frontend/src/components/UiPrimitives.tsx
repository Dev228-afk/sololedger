import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';
import { AlertCircle, CheckCircle2, Clock } from 'lucide-react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'accent';
type AlertKind = 'info' | 'warning' | 'danger' | 'success';

const BUTTON_PALETTE: Record<ButtonVariant, { bg: string; color: string; border: string }> = {
  primary: { bg: 'var(--accent)', color: '#ffffff', border: 'transparent' },
  secondary: { bg: 'var(--surface)', color: 'var(--ink)', border: 'var(--line)' },
  ghost: { bg: 'transparent', color: 'var(--ink)', border: 'transparent' },
  danger: { bg: 'var(--danger)', color: '#ffffff', border: 'transparent' },
};

const BADGE_STYLES: Record<BadgeTone, { bg: string; fg: string; border: string }> = {
  neutral: { bg: 'var(--surface-muted)', fg: 'var(--ink)', border: 'var(--line)' },
  accent: { bg: 'var(--accent-soft)', fg: 'var(--accent-hover)', border: '#bfdacf' },
  success: { bg: 'var(--success-soft)', fg: 'var(--accent-hover)', border: '#b7dfd0' },
  warning: { bg: 'var(--warning-soft)', fg: '#7a4d09', border: '#e8d4a2' },
  danger: { bg: 'var(--danger-soft)', fg: '#922f33', border: '#ecc4c6' },
};

const ALERT_STYLES: Record<AlertKind, { bg: string; border: string; fg: string }> = {
  info: { bg: 'var(--accent-soft)', border: '#bfdacf', fg: 'var(--ink)' },
  success: { bg: 'var(--success-soft)', border: '#b7dfd0', fg: 'var(--ink)' },
  warning: { bg: 'var(--warning-soft)', border: '#e8d4a2', fg: 'var(--ink)' },
  danger: { bg: 'var(--danger-soft)', border: '#ecc4c6', fg: 'var(--danger)' },
};

export function Button({
  variant = 'primary',
  size = 'md',
  ref,
  children,
  style,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
  ref?: Ref<HTMLButtonElement>;
}) {
  const colors = BUTTON_PALETTE[variant];
  return (
    <button
      ref={ref}
      type={rest.type ?? 'button'}
      className={rest.className ? `sl-btn ${rest.className}` : 'sl-btn'}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
        minHeight: size === 'sm' ? '36px' : '42px',
        padding: size === 'sm' ? '6px 12px' : '8px 16px',
        borderRadius: 'var(--r-sm)',
        border: `1px solid ${colors.border}`,
        backgroundColor: colors.bg,
        color: colors.color,
        fontFamily: 'inherit',
        fontSize: '14px',
        fontWeight: 600,
        cursor: rest.disabled ? 'not-allowed' : 'pointer',
        opacity: rest.disabled ? 0.55 : 1,
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  );
}

export function StatusBadge({
  tone = 'neutral',
  label,
}: {
  tone?: BadgeTone;
  label: string;
}) {
  const s = BADGE_STYLES[tone];
  const Icon =
    tone === 'success' ? CheckCircle2 : tone === 'warning' || tone === 'danger' ? AlertCircle : Clock;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        padding: '3px 9px',
        borderRadius: '999px',
        border: `1px solid ${s.border}`,
        backgroundColor: s.bg,
        color: s.fg,
        fontSize: '12px',
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      <Icon size={13} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}

export function SignedMoneyCell({
  amount,
  currency = 'USD',
}: {
  amount: string;
  currency?: string;
}) {
  const isNegative = amount.startsWith('-');
  const display = isNegative ? `-$${amount.slice(1)}` : `+$${amount}`;
  return (
    <span
      className="tabular-nums"
      style={{
        fontWeight: 600,
        color: isNegative ? 'var(--ink)' : 'var(--success)',
      }}
    >
      {display} <span style={{ fontSize: '11px', color: 'var(--muted)' }}>{currency}</span>
    </span>
  );
}

export function AlertBanner({
  kind = 'info',
  title,
  message,
  action,
}: {
  kind?: AlertKind;
  title?: string;
  message: string;
  action?: ReactNode;
}) {
  const m = ALERT_STYLES[kind];
  return (
    <div
      role={kind === 'danger' || kind === 'warning' ? 'alert' : 'status'}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        padding: '12px 16px',
        borderRadius: 'var(--r-sm)',
        border: `1px solid ${m.border}`,
        backgroundColor: m.bg,
        color: m.fg,
        fontSize: '14px',
      }}
    >
      <div>
        {title ? <strong style={{ display: 'block', marginBottom: '2px' }}>{title}</strong> : null}
        <span>{message}</span>
      </div>
      {action}
    </div>
  );
}

