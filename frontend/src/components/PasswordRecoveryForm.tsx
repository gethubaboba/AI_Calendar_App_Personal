'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiForgotPassword, apiResetPassword, tokens } from '@/lib/api';

export default function PasswordRecoveryForm({ reset = false }: { reset?: boolean }) {
  const [email, setEmail] = useState('');
  const [token, setToken] = useState('');
  const [ready, setReady] = useState(!reset);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!reset) return;
    const readFragment = () => {
      const value = new URLSearchParams(window.location.hash.slice(1)).get('token');
      if (value) { setToken(value); setMessage(''); setError(''); }
      // Keep reset credentials out of history and subsequent referrers.
      if (window.location.hash) window.history.replaceState(null, '', window.location.pathname + window.location.search);
      setReady(true);
    };
    readFragment();
    window.addEventListener('hashchange', readFragment);
    return () => window.removeEventListener('hashchange', readFragment);
  }, [reset]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setError('');
    if (reset && (password.length < 12 || new TextEncoder().encode(password).length > 72)) {
      setError('Пароль должен содержать не менее 12 символов и не более 72 байт UTF-8.'); return;
    }
    if (reset && password !== confirmation) { setError('Пароли не совпадают.'); return; }
    setBusy(true);
    try {
      const result = reset ? await apiResetPassword(token, password) : await apiForgotPassword(email.trim());
      setMessage(result.message);
      if (reset) { tokens.clear(); setToken(''); setPassword(''); setConfirmation(''); }
    } catch (err) { setError(err instanceof Error ? err.message : 'Не удалось выполнить запрос. Попробуйте позже.'); }
    finally { setBusy(false); }
  };
  const inputClass = 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-400';
  const noToken = reset && ready && !token && !message;
  return <main className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
    <section className="w-full max-w-md bg-white rounded-2xl shadow-sm p-6 sm:p-8 space-y-4">
      <h1 className="text-2xl font-semibold text-slate-800">{reset ? 'Новый пароль' : 'Восстановление пароля'}</h1>
      {message ? <p role="status" className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{message}</p> : <>
        <p className="text-sm text-slate-600">{reset ? 'Задайте новый пароль. Все прежние сеансы будут завершены. Если 2FA включена, она останется включённой.' : 'Введите почту аккаунта. Если он зарегистрирован, мы отправим ссылку для восстановления. Ссылка действует 15 минут.'}</p>
        {noToken ? <p role="alert" className="text-sm text-slate-600">Откройте ссылку из письма ещё раз или запросите новую.</p> : <form onSubmit={submit} className="space-y-4">
          {reset ? <>
            <div><label htmlFor="new-password" className="block text-sm mb-1">Новый пароль</label>
              <input id="new-password" type="password" autoComplete="new-password" minLength={12} maxLength={72} required value={password} onChange={e => setPassword(e.target.value)} className={inputClass} /></div>
            <div><label htmlFor="confirm-password" className="block text-sm mb-1">Повторите пароль</label>
              <input id="confirm-password" type="password" autoComplete="new-password" minLength={12} maxLength={72} required value={confirmation} onChange={e => setConfirmation(e.target.value)} className={inputClass} /></div>
            <p className="text-xs text-slate-500">Не менее 12 символов. Для кириллицы и других многобайтных символов действует дополнительный предел 72 байта.</p>
          </> : <div><label htmlFor="recovery-email" className="block text-sm mb-1">Email аккаунта</label>
            <input id="recovery-email" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} className={inputClass} /></div>}
          {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          <button type="submit" disabled={busy || !ready} className="w-full py-2.5 rounded-xl bg-emerald-600 text-white disabled:opacity-60">{busy ? 'Отправка…' : reset ? 'Сохранить новый пароль' : 'Отправить ссылку'}</button>
        </form>}
      </>}
      {reset && <Link href="/forgot-password" className="block text-sm text-emerald-700 hover:underline">Запросить новую ссылку</Link>}
      <Link href="/auth" className="block text-sm text-emerald-700 hover:underline">Вернуться ко входу</Link>
    </section>
  </main>;
}
