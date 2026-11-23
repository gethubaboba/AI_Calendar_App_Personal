import type { Metadata } from 'next';
import PasswordRecoveryForm from '@/components/PasswordRecoveryForm';

export const metadata: Metadata = { referrer: 'no-referrer', robots: { index: false, follow: false } };

export default function ResetPasswordPage() {
  return <PasswordRecoveryForm reset />;
}
