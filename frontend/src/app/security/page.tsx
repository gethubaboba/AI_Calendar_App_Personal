'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import QRCode from 'qrcode';
import Header from '@/components/Header';
import { apiGetMe, apiMfaStatus, apiMfaSetup, apiMfaEnable, apiMfaDisable, tokens, type MfaStatus } from '@/lib/api';

export default function SecurityPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [recovery, setRecovery] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const load = async () => {
    const [user, mfa] = await Promise.all([apiGetMe(), apiMfaStatus()]);
    setName(user.name);
    setStatus(mfa);
  };
  useEffect(() => {
    if (!tokens.getAccess()) { router.replace('/auth'); return; }
    load().catch(err => setError(err instanceof Error ? err.message : 'Не удалось загрузить настройки'));
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(''); setMessage('');
    try {
      if (status?.enabled) {
        const result = await apiMfaDisable(password, code.trim());
        tokens.set(result.access_token, result.refresh_token);
        setMessage('Двухфакторная аутентификация отключена. Другие сеансы завершены.');
      } else if (setup) {
        const result = await apiMfaEnable(code.trim());
        tokens.set(result.access_token, result.refresh_token);
        setRecovery(result.recovery_codes);
        setSetup(null);
        setMessage('Двухфакторная аутентификация включена. Другие сеансы завершены.');
      } else {
        const result = await apiMfaSetup(password);
        const qr = await QRCode.toDataURL(result.otpauth_uri, { width: 240, margin: 2 });
        setSetup({ secret: result.secret, qr });
      }
      setPassword(''); setCode('');
      setStatus(await apiMfaStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось изменить настройки');
    } finally { setBusy(false); }
  };

  const inputClass = 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-400';
  return <div className="min-h-screen bg-slate-50">
    <Header userName={name} onCreateEvent={() => router.push('/dashboard')} onLogout={() => { tokens.clear(); router.push('/auth'); }} />
    <main className="max-w-xl mx-auto p-4 sm:p-6 pb-24">
      <h1 className="text-2xl font-semibold text-slate-800 mb-5">Безопасность аккаунта</h1>
      <section className="bg-white rounded-2xl border border-slate-100 p-5 space-y-4">
        <h2 className="text-lg font-semibold">Двухфакторная аутентификация</h2>
        <p className="text-sm text-slate-600">После пароля при входе потребуется код из приложения-аутентификатора на телефоне.</p>
        {status && <p className="font-medium">{status.enabled ? `Включена. Резервных кодов осталось: ${status.recovery_codes_remaining}.` : 'Пока отключена.'}</p>}
        {error && <p role="alert" className="text-red-700 bg-red-50 p-3 rounded-xl text-sm">{error}</p>}
        {message && <p role="status" className="text-emerald-800 bg-emerald-50 p-3 rounded-xl text-sm">{message}</p>}
        {!status && <button onClick={() => load().catch(err => setError(err.message))} className="text-emerald-700">Повторить загрузку</button>}
        {recovery.length > 0 ? <div className="space-y-4">
          <h3 className="font-semibold">Сохраните резервные коды</h3>
          <p className="text-sm text-slate-600">Каждый код заменяет код с телефона один раз. Они показываются только сейчас. Сохраните их в менеджере паролей или распечатайте и храните отдельно от телефона.</p>
          <pre className="rounded-xl bg-slate-50 p-4 text-sm whitespace-pre-wrap break-all select-all">{recovery.join('\n')}</pre>
          <button onClick={() => { setRecovery([]); setMessage(''); }} className="px-4 py-2 rounded-xl bg-emerald-600 text-white">Я сохранил резервные коды</button>
        </div> : status && <form onSubmit={submit} className="space-y-4">
          {!setup && <div>
            <label htmlFor="current-password" className="block text-sm mb-1">Текущий пароль</label>
            <input id="current-password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} className={inputClass} />
          </div>}
          {setup && <div className="space-y-3">
            <p className="text-sm">Добавьте аккаунт в приложение-аутентификатор: отсканируйте QR-код или введите ключ вручную.</p>
            {/* QR is generated locally; the shared secret never reaches an image service. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={setup.qr} alt="QR-код для подключения аутентификатора" width={240} height={240} className="max-w-full" />
            <p className="text-xs text-slate-500">Ключ для ручного ввода (TOTP, 6 цифр, 30 секунд):</p>
            <code className="block break-all select-all text-sm bg-slate-50 rounded-lg p-3">{setup.secret}</code>
          </div>}
          {(status.enabled || setup) && <div>
            <label htmlFor="confirmation-code" className="block text-sm mb-1">{status.enabled ? 'Код аутентификатора или резервный код' : 'Шестизначный код аутентификатора'}</label>
            <input id="confirmation-code" autoComplete="one-time-code" inputMode={status.enabled ? 'text' : 'numeric'} maxLength={64} required value={code} onChange={e => setCode(e.target.value)} className={inputClass} />
          </div>}
          <button disabled={busy} type="submit" className="px-4 py-2.5 rounded-xl bg-emerald-600 text-white disabled:opacity-60">{busy ? 'Сохранение…' : status.enabled ? 'Отключить двухфакторную аутентификацию' : setup ? 'Подтвердить и включить' : 'Настроить аутентификатор'}</button>
          {setup && <button disabled={busy} type="button" onClick={() => { setSetup(null); setCode(''); setError(''); }} className="block text-sm text-slate-600">Отменить настройку</button>}
        </form>}
      </section>
    </main>
  </div>;
}
